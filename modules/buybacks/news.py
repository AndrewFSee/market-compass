"""Buyback announcements from 8-Ks: SentIQ finds candidate passages, Claude reads each filing once.

SentIQ's ``scripts/publish_buyback_candidates_to_hub.py`` (job "buyback_news") writes
``buyback_news/candidates``: one row per 8-K whose cover or EX-99 press release mentions a share
repurchase together with an authorization, program, increase, accelerated repurchase or tender
offer. Most such mentions are recaps of a program announced earlier, so a pattern alone can't
tell; Claude classifies each candidate once and the verdict is cached in
``buyback_news/classified`` (keyed by accession), so a filing is never paid for twice.

Daily job ``run``: classifies new candidates from the last ``DAILY_LOOKBACK_DAYS`` (at most
``MAX_PER_RUN``), then rebuilds ``buyback_news/announcements``. History is classified once,
explicitly, through the Batch API (half price):

    python -m modules.buybacks.news estimate             # count tokens, print the cost (free)
    python -m modules.buybacks.news backfill --yes       # submit the batch
    python -m modules.buybacks.news collect              # fetch results when the batch has ended
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from core import store

MODULE = "buyback_news"
MODEL = "claude-haiku-5-5"          # high-volume classification: ~$0.0003 a filing (Opus 5.5 would be ~40x)
EFFORT = "low"
MAX_TOKENS = 1000
DAILY_LOOKBACK_DAYS = 30
MAX_PER_RUN = 300                  # cost guard for the daily job (~$0.10 at most)
PRICE_PER_MTOK = {"input": 0.10, "output": 0.50}  # Haiku 5.5 (prompts under 100K tokens); batches are half
DEDUPE_DAYS = 120                  # same company, kind and amount within this many days = one event

ANNOUNCED = ["new_program", "increase", "replacement", "accelerated_repurchase", "tender_offer"]
KINDS = ANNOUNCED + ["existing_program_mention", "not_share_buyback"]

SYSTEM = """\
You classify passages from a company's SEC 8-K filing (cover page and attached press releases) for a
dashboard that tracks share-buyback announcements. Decide what the filing says about repurchases of the
company's own common stock:

- new_program: the board approved or authorized a new repurchase program or authorization.
- increase: the board added to or increased an existing authorization.
- replacement: a new authorization replaces or supersedes the previous one.
- accelerated_repurchase: the company entered into an accelerated share repurchase (ASR) agreement.
- tender_offer: the company launched or announced a tender offer or Dutch auction for its own shares.
- existing_program_mention: repurchases under an authorization that was announced before this filing
  (amounts bought, remaining capacity, "as previously announced"), with no new action.
- not_share_buyback: anything else (debt or note repurchases, repo agreements, preferred stock,
  another company's shares, boilerplate).

Set first_disclosed_here to false when the passage reports an action that was announced earlier (for
example a quarterly release recapping "in December the board authorized..."), and give that earlier date
in announced_on when the passage states it. An ASR or tender offer is first disclosed here only when
this filing announces entering into or launching it; one described as executed or completed in a past
quarter was disclosed earlier. Plans to use capacity remaining under an existing authorization are
existing_program_mention. Amounts are US dollars as plain numbers (2.5 billion ->
2500000000): amount_usd is the size of the new action itself (the new authorization, the increase, the
ASR or tender size), total_authorized_usd the total authorization after it when stated, and shares the
share count when the authorization is stated in shares rather than dollars. Use null when not stated.
Keep summary under 25 words."""

SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": KINDS},
        "first_disclosed_here": {"type": "boolean"},
        "announced_on": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "amount_usd": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "total_authorized_usd": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "shares": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "summary": {"type": "string"},
    },
    "required": ["kind", "first_disclosed_here", "announced_on", "amount_usd", "total_authorized_usd", "shares",
                 "summary"],
    "additionalProperties": False,
}


class NoCredentials(RuntimeError):
    pass


def prompt(c: pd.Series) -> str:
    when = pd.Timestamp(c["tradable_at"]).tz_convert("America/New_York")
    return (f"Company: {c['company']} ({c['tickers'] or 'no ticker'})\nFiled: {when:%Y-%m-%d %H:%M} ET\n"
            f"8-K items: {c['items'] or 'n/a'}\n\nPassages (separated by ---):\n{c['passages']}")


def params(c: pd.Series) -> dict:
    return {"model": MODEL, "max_tokens": MAX_TOKENS, "system": SYSTEM,
            "messages": [{"role": "user", "content": prompt(c)}],
            "thinking": {"type": "disabled"},
            "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}}}


def parse(message, accession: str, batch: bool = False) -> dict:
    """One classified row from a response (or a row recording why there is no verdict)."""
    row = {"accession": accession, "model": getattr(message, "model", MODEL), "stop_reason": message.stop_reason,
           "classified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "batch": batch,
           "input_tokens": message.usage.input_tokens, "output_tokens": message.usage.output_tokens}
    text = next((b.text for b in message.content if b.type == "text"), "")
    if message.stop_reason in ("end_turn", "stop_sequence") and text:
        try:
            row.update(json.loads(text))
        except json.JSONDecodeError:
            row["kind"] = None
    else:
        row["kind"] = None
    return row


def client():
    import anthropic
    try:
        return anthropic.Anthropic()
    except Exception as e:  # noqa: BLE001
        raise NoCredentials(str(e)) from None


def classify_one(api, c: pd.Series) -> dict:
    try:
        msg = api.messages.create(**params(c))   # Haiku has no server-side fallback; a refusal leaves kind empty
    except TypeError as e:  # raised locally, before any request, when nothing can authenticate
        if "authentication" in str(e).lower():
            raise NoCredentials(str(e)) from None
        raise
    return parse(msg, c["accession"])


def load_classified() -> pd.DataFrame:
    df = store.load_frame(MODULE, "classified")
    return df if df is not None else pd.DataFrame(columns=["accession", "kind", "first_disclosed_here", "batch",
                                                           "input_tokens", "output_tokens"])


def save_classified(rows: list[dict]) -> pd.DataFrame:
    old = load_classified()
    new = pd.DataFrame(rows)
    out = pd.concat([old[~old["accession"].isin(new["accession"])], new], ignore_index=True) if len(new) else old
    store.save_frame(MODULE, "classified", out.reset_index(drop=True))
    return out


def announcements(cand: pd.DataFrame, cls: pd.DataFrame) -> pd.DataFrame:
    """First disclosures of new / increased / replacement programs, ASRs and tender offers, one row
    per event: a company repeating the same amount (or, without one, the same kind) within DEDUPE_DAYS
    counts once, whatever kind each filing was given."""
    if cand is None or cand.empty or cls.empty or "kind" not in cls:
        return pd.DataFrame()
    a = cls[cls["kind"].isin(ANNOUNCED) & cls["first_disclosed_here"].fillna(False).astype(bool)]
    a = a.merge(cand[["accession", "company", "tickers", "cik", "items", "tradable_at", "url"]], on="accession")
    a = a.sort_values("tradable_at")
    keep, last = [], {}
    for r in a.itertuples():
        amount = r.amount_usd if pd.notna(r.amount_usd) and r.amount_usd else None
        key = (r.cik, round(amount, -6)) if amount else (r.cik, r.kind)
        prev = last.get(key)
        if prev is not None and (r.tradable_at - prev).days < DEDUPE_DAYS:
            continue
        last[key] = r.tradable_at
        keep.append(r.Index)
    cols = ["tradable_at", "tickers", "company", "kind", "amount_usd", "total_authorized_usd", "shares", "summary",
            "url", "accession", "cik", "items"]
    return a.loc[keep, cols].sort_values("tradable_at", ascending=False).reset_index(drop=True)


def cost(cls: pd.DataFrame) -> float:
    if cls.empty or "input_tokens" not in cls:
        return 0.0
    k = cls["batch"].fillna(False).astype(bool).map({True: 0.5, False: 1.0})
    usd = (cls["input_tokens"].fillna(0) * PRICE_PER_MTOK["input"] + cls["output_tokens"].fillna(0)
           * PRICE_PER_MTOK["output"]) / 1e6
    return float((usd * k).sum())


def publish(cand: pd.DataFrame, cls: pd.DataFrame, log=print) -> None:
    ann = announcements(cand, cls)
    store.save_frame(MODULE, "announcements", ann)
    store.save_json(MODULE, "classify_summary", {
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": MODEL,
        "candidates": int(len(cand)) if cand is not None else 0, "classified": int(cls["kind"].notna().sum()),
        "announcements": int(len(ann)), "first": str(ann["tradable_at"].min()) if len(ann) else None,
        "kinds": {k: int(v) for k, v in cls["kind"].value_counts().items()} if "kind" in cls else {},
        "spent_usd": round(cost(cls), 4)})
    log(f"  {len(ann)} announcements from {int(cls['kind'].notna().sum())} classified filings "
        f"(spent so far ~${cost(cls):.2f}).")


def run(demo: bool = False, log=print, api=None) -> dict | None:
    cand = store.load_frame(MODULE, "candidates")
    if cand is None or cand.empty:
        log("  no candidates yet (SentIQ's publish_buyback_candidates_to_hub.py hasn't run)")
        return None
    cls = load_classified()
    done = set(cls["accession"][cls["kind"].notna()]) if "kind" in cls else set()
    since = pd.Timestamp.now(tz="UTC") - timedelta(days=DAILY_LOOKBACK_DAYS)
    todo = cand[(pd.to_datetime(cand["tradable_at"], utc=True) >= since) & ~cand["accession"].isin(done)]
    if demo:
        log(f"  demo mode: {len(todo)} candidates would be classified; nothing sent")
    elif len(todo):
        todo = todo.sort_values("tradable_at", ascending=False).head(MAX_PER_RUN)
        rows: list[dict] = []
        try:
            api = api or client()
            for _, c in todo.iterrows():
                rows.append(classify_one(api, c))
        except NoCredentials:
            log("  skipped: no Anthropic credentials (ANTHROPIC_API_KEY in the hub's .env)")
        finally:
            if rows:  # keep what was paid for even if a later request failed
                cls = save_classified(rows)
        log(f"  classified {len(rows)} new filings with {MODEL}")
    publish(cand, cls, log)
    return {"classified": len(cls)}


# ------------------------------------------------------------------ one-off history (Batch API)
def _history_todo() -> pd.DataFrame:
    cand = store.load_frame(MODULE, "candidates")
    cls = load_classified()
    done = set(cls["accession"][cls["kind"].notna()]) if "kind" in cls else set()
    return cand[~cand["accession"].isin(done)]


def estimate(sample: int = 40) -> dict:
    """Token count of a sample (free endpoint) scaled to everything unclassified; output assumed ~150
    tokens a filing (thinking off)."""
    api = client()
    todo = _history_todo()
    s = todo.sample(min(sample, len(todo)), random_state=0) if len(todo) else todo
    toks = [api.messages.count_tokens(model=MODEL, system=SYSTEM, messages=params(c)["messages"]).input_tokens
            for _, c in s.iterrows()]
    per = sum(toks) / max(len(toks), 1)
    usd = len(todo) * (per * PRICE_PER_MTOK["input"] + 150 * PRICE_PER_MTOK["output"]) / 1e6 * 0.5
    return {"filings": int(len(todo)), "avg_input_tokens": round(per), "batch_usd": round(usd, 2)}


def backfill() -> str:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    api = client()
    todo = _history_todo()
    reqs = [Request(custom_id=c["accession"], params=MessageCreateParamsNonStreaming(**params(c)))
            for _, c in todo.iterrows()]
    batch = api.messages.batches.create(requests=reqs)
    store.save_json(MODULE, "batch", {"id": batch.id, "submitted": datetime.now(timezone.utc).isoformat(),
                                      "requests": len(reqs)})
    return batch.id


def collect(wait: bool = True) -> int:
    api = client()
    info = store.load_json(MODULE, "batch")
    if not info:
        raise SystemExit("no batch submitted")
    while True:
        b = api.messages.batches.retrieve(info["id"])
        if b.processing_status == "ended" or not wait:
            break
        print(f"  {b.request_counts.processing} still processing...", flush=True)
        time.sleep(60)
    if b.processing_status != "ended":
        return 0
    rows = []
    for r in api.messages.batches.results(info["id"]):
        if r.result.type == "succeeded":
            rows.append(parse(r.result.message, r.custom_id, batch=True))
    cls = save_classified(rows)
    publish(store.load_frame(MODULE, "candidates"), cls)
    return len(rows)


if __name__ == "__main__":
    from core import env
    env.load()
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["estimate", "backfill", "collect"])
    p.add_argument("--yes", action="store_true", help="confirm the spend for backfill")
    a = p.parse_args()
    if a.command == "estimate":
        print(estimate())
    elif a.command == "backfill":
        e = estimate()
        print(f"{e['filings']:,} filings, ~{e['avg_input_tokens']:,} input tokens each: ~${e['batch_usd']:.2f} via the "
              "Batch API.")
        if not a.yes:
            sys.exit("Not submitted: rerun with --yes to confirm the spend.")
        print("submitted batch", backfill())
    else:
        print(f"collected {collect()} results")
