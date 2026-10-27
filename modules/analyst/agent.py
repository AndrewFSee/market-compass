"""Claude with the dashboard's read-only tools, via the SDK's tool runner."""
from __future__ import annotations

import json
from collections import Counter

import anthropic
from anthropic import beta_tool

from modules.analyst import config as cfg
from modules.analyst import tools as T


class NoCredentials(RuntimeError):
    """No Anthropic API key / token / profile is configured."""


def _json(obj) -> str:
    return json.dumps(obj, separators=(",", ":"))


@beta_tool
def data_freshness() -> str:
    """When each dashboard module last published, and each module's own as-of date. Check this first."""
    return _json(T.data_freshness())


@beta_tool
def market_overview() -> str:
    """The four regime gauges (fear/greed, liquidity, technical, economic) with value, band, trend vs 1 week
    and 1 month ago, and each gauge's measured link to the next period's S&P 500 return; S&P 500 breadth;
    style/size returns; leading and lagging sectors."""
    return _json(T.market_overview())


@beta_tool
def gauge_detail(gauge: str) -> str:
    """One regime gauge in full: its components with readings and scores, and the S&P 500's next-period
    return by gauge band.

    Args:
        gauge: One of fear_greed, liquidity, technical, economic.
    """
    return _json(T.gauge_detail(gauge))


@beta_tool
def credit_overview() -> str:
    """Credit spreads (bps, with 20-day changes and percentiles), the real-time credit-stress regime
    probabilities, the equity-overlay weight, the 5-day Baa spread forecast, rating-tier spreads and
    CCC-B decompression, and Fed net liquidity."""
    return _json(T.credit_overview())


@beta_tool
def macro_overview() -> str:
    """The live recession probability and its component signals, the GDP nowcast with its interval, latent
    macro factors, and recent walk-forward recession probabilities."""
    return _json(T.macro_overview())


@beta_tool
def vol_overview(tickers: list[str] | None = None) -> str:
    """Market volatility indices (VIX family, VVIX, MOVE, OVX) with 5-day changes, the biggest 5-day moves
    in 30-day implied vol across 41 tickers, and implied vol, skew, term structure, variance premium and
    the 21-day vol forecast for chosen tickers.

    Args:
        tickers: Tickers to detail (e.g. ["SPY", "NVDA"]); defaults to SPY, QQQ, IWM, TLT, HYG.
    """
    return _json(T.vol_overview(tickers))


@beta_tool
def tail_risk_overview() -> str:
    """Simulated 21-day VaR and CVaR for the configured multi-asset portfolio next to the same measures from
    history, hedge comparisons, CVaR-optimal weights and the current crisis-regime probability."""
    return _json(T.tail_risk_overview())


@beta_tool
def lookalikes() -> str:
    """Today's closest historical market states (distinct episodes since 1997) and what the S&P 500 did
    over the following 1 and 3 months, versus all days; plus the method's walk-forward track record."""
    return _json(T.lookalikes())


@beta_tool
def series_history(name: str, years: float = 2.0) -> str:
    """A published time series sampled to about 60 points, with its latest value, range and where today
    sits in its full history.

    Args:
        name: One of spy, vix, fear_greed, technical, liquidity, yield_curve_10y3m, economic, pct_above_50d,
            hy_spread_pts, baa_spread_bps, credit_stress_prob, macro_p_recession.
        years: How many years back to sample (default 2).
    """
    return _json(T.series_history(name, years))


TOOLS = [data_freshness, market_overview, gauge_detail, credit_overview, macro_overview, vol_overview,
         tail_risk_overview, lookalikes, series_history]


def ask(messages: list[dict], effort: str, client: anthropic.Anthropic | None = None) -> dict:
    """Run Claude with the tools until it answers. `messages` are plain role/content turns.

    Returns {"text", "stop_reason", "tool_calls", "usage", "model"}. Raises NoCredentials when no
    API key/token/profile is configured; other API errors propagate."""
    client = client or anthropic.Anthropic()
    calls, usage, last = [], Counter(), None
    try:
        runner = client.beta.messages.tool_runner(
            model=cfg.MODEL,
            max_tokens=cfg.MAX_TOKENS,
            system=cfg.SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
            output_config={"effort": effort},
            max_iterations=cfg.MAX_TOOL_ROUNDS,
            cache_control={"type": "ephemeral"},   # system prompt + tools are identical every call
            betas=[cfg.FALLBACK_BETA],
            fallbacks="default",
        )
        for message in runner:
            last = message
            calls += [{"name": b.name, "input": b.input} for b in message.content if b.type == "tool_use"]
            for field in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                usage[field] += getattr(message.usage, field, None) or 0
    except TypeError as e:  # raised locally, before any request, when nothing can authenticate
        if "authentication" in str(e).lower():
            raise NoCredentials(str(e)) from None
        raise
    if last is None:
        raise RuntimeError("no response from the model")
    text = "".join(b.text for b in last.content if b.type == "text").strip()
    if last.stop_reason == "refusal":
        text = text or "The model declined to answer this request."
    elif last.stop_reason == "max_tokens":
        text += "\n\n*(Cut off at the output limit.)*"
    elif last.stop_reason == "tool_use":  # stopped by max_iterations with tools still pending
        text += "\n\n*(Stopped after the maximum number of tool rounds.)*"
    return {"text": text, "stop_reason": last.stop_reason, "tool_calls": calls, "usage": dict(usage),
            "model": last.model}
