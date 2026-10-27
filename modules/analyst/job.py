"""Nightly brief: Claude reads every module through the analyst tools and writes a brief.
Runs last, after every module has published. Skips (with a log line) when no API key is set."""
from __future__ import annotations

from datetime import datetime

from core import store
from modules.analyst import config as cfg


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
        return None
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
