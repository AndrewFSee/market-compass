"""Nightly brief: Claude reads every module through the analyst tools and writes a brief.
Runs last, after every module has published. Skips (with a log line) when no API key is set.

Every attempt is recorded in ``last_attempt`` so the page can say when the brief it shows is
old because the latest attempt failed (e.g. the key was rejected) rather than leave it silent."""
from __future__ import annotations

from datetime import datetime

from core import store
from modules.analyst import config as cfg


def _record(ok: bool, reason: str | None = None) -> None:
    store.save_json(cfg.MODULE, "last_attempt", {"at": datetime.now().isoformat(timespec="seconds"),
                                                  "ok": ok, "reason": reason})


def _reason(err: Exception) -> str:
    import anthropic
    if isinstance(err, anthropic.AuthenticationError):
        return "the Anthropic API rejected the key (expired or revoked). Replace ANTHROPIC_API_KEY in the hub's .env."
    if isinstance(err, anthropic.PermissionDeniedError):
        return "the Anthropic API refused the key's permissions. Check the key in the Anthropic Console."
    if isinstance(err, anthropic.APIStatusError):
        msg = err.body.get("error", {}).get("message") if isinstance(err.body, dict) else None
        return f"the Anthropic API returned {err.status_code}: {msg or err}"
    if isinstance(err, anthropic.APIConnectionError):
        return "could not reach the Anthropic API (network)."
    return f"{type(err).__name__}: {err}"[:300]


def run(demo: bool = False, log=print) -> dict | None:
    if demo:
        log("  demo mode: no brief (it would call the API on synthetic data)")
        return None
    from modules.analyst import agent

    log(f"  asking {cfg.MODEL} for today's brief...")
    try:
        res = agent.ask([{"role": "user", "content": cfg.BRIEF_REQUEST}], effort=cfg.EFFORT["brief"])
    except agent.NoCredentials:
        log("  skipped: no Anthropic credentials. Add ANTHROPIC_API_KEY=... to the hub's .env file.")
        _record(False, "no Anthropic API key is set. Add ANTHROPIC_API_KEY to the hub's .env.")
        return None
    except Exception as err:
        reason = _reason(err)
        _record(False, reason)
        raise RuntimeError(f"no brief: {reason}") from err
    _record(True)
    brief = {"generated": datetime.now().isoformat(timespec="seconds"),
             "data_as_of": (store.load_json("market", "meta") or {}).get("as_of"), **res}
    store.save_json(cfg.MODULE, "brief", brief)
    history = store.load_json(cfg.MODULE, "brief_history") or []
    history = [b for b in history if b["generated"][:10] != brief["generated"][:10]]  # one per day
    store.save_json(cfg.MODULE, "brief_history", ([brief] + history)[: cfg.BRIEFS_KEPT])
    u = res["usage"]
    log(f"  brief saved: {len(res['text'].split())} words, {len(res['tool_calls'])} tool calls, "
        f"{u.get('input_tokens', 0):,} in / {u.get('output_tokens', 0):,} out tokens "
        f"({u.get('cache_read_input_tokens', 0):,} cached)")
    return brief
