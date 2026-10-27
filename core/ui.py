"""Reusable dashboard pieces: gauges, donuts, performance tiles, and small
wrappers that keep working across Streamlit versions."""
from __future__ import annotations

import html
import inspect
import math

import plotly.graph_objects as go
import streamlit as st

PALETTE = {"red": "#E4572E", "amber": "#F2C14E", "teal": "#2BB5A6", "grey": "#9AA5B1"}
BADGE_COLOR = {"red": "red", "amber": "orange", "teal": "green", "grey": "gray"}
_INK = "#0E1A22"

_HAS_WIDTH = "width" in inspect.signature(st.plotly_chart).parameters


# ----------------------------------------------------------------- compat
def chart(fig, key: str | None = None) -> None:
    kw = {"width": "stretch"} if _HAS_WIDTH else {"use_container_width": True}
    st.plotly_chart(fig, key=key, config={"displayModeBar": False}, **kw)


def table(df, **kwargs) -> None:
    if "width" in inspect.signature(st.dataframe).parameters:
        st.dataframe(df, width="stretch", **kwargs)
    else:
        st.dataframe(df, use_container_width=True, **kwargs)


def choice(label: str, options: list[str], key: str, default: str | None = None) -> str:
    """Compact single-choice control (segmented buttons when available)."""
    default = default or options[0]
    if hasattr(st, "segmented_control"):
        value = st.segmented_control(label, options, default=default, key=key, label_visibility="collapsed")
        return value or default
    return st.radio(label, options, index=options.index(default), key=key, horizontal=True,
                    label_visibility="collapsed")


def badge(label: str, color: str) -> None:
    c = BADGE_COLOR.get(color, "gray")
    if hasattr(st, "badge"):
        st.badge(label, color=c)
    else:
        st.markdown(f":{c}-background[{label}]")


# ----------------------------------------------------------------- figures
def band_index(value: float | None, cuts: list[float]) -> int | None:
    if value is None:
        return None
    return sum(value > c for c in cuts)


def gauge(value: float | None, lo: float, hi: float, cuts: list[float], colors: list[str],
          height: int = 180) -> go.Figure:
    edges = [lo, *cuts, hi]
    steps = [{"range": [a, b], "color": PALETTE[c]} for a, b, c in zip(edges[:-1], edges[1:], colors)]
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value if value is not None else lo,
        number={"valueformat": ".2f", "font": {"size": 30}},
        gauge={
            "axis": {"range": [lo, hi], "tickvals": edges, "ticktext": [f"{e:g}".replace("-", "\u2212") for e in edges],
                     "ticks": "", "tickfont": {"size": 11}},
            "bar": {"color": "rgba(0,0,0,0)"},
            "steps": steps,
            "borderwidth": 0,
            "threshold": {"line": {"color": _INK, "width": 5}, "thickness": 0.95,
                          "value": value if value is not None else lo},
        },
    ))
    fig.update_layout(height=height, margin={"l": 34, "r": 34, "t": 22, "b": 4},
                      paper_bgcolor="rgba(0,0,0,0)")
    return fig


def donut(labels: list[str], values: list[float], colors: list[str], center: str = "",
          height: int = 230) -> go.Figure:
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.64, sort=False, direction="clockwise",
                           marker={"colors": [PALETTE[c] for c in colors]}, textinfo="none",
                           hovertemplate="%{label}: %{percent}<extra></extra>"))
    fig.update_layout(height=height, margin={"l": 0, "r": 0, "t": 6, "b": 6}, showlegend=True,
                      legend={"orientation": "h", "y": -0.05, "x": 0.5, "xanchor": "center"},
                      paper_bgcolor="rgba(0,0,0,0)",
                      annotations=[{"text": center, "showarrow": False, "font": {"size": 22}}] if center else [])
    return fig


# ----------------------------------------------------------------- tiles
_TILE_CSS = """
<style>
.mh-grid{display:grid;gap:8px;margin:4px 0 6px}
.mh-tile{border-radius:8px;padding:10px 8px;text-align:center;color:#0E1A22;min-width:0}
.mh-v{font-weight:700;font-size:1.02rem;font-variant-numeric:tabular-nums}
.mh-t{font-size:.8rem;line-height:1.2;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mh-s{font-size:.7rem;opacity:.75}
.mh-legend{display:flex;gap:14px;font-size:.75rem;opacity:.8;justify-content:flex-end}
.mh-legend span::before{content:"";display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px;background:var(--c)}
</style>
"""

# lead/lag in two strengths; dark ink reads on all of them in light and dark themes
_TILE_SHADES = {"lead_strong": "#22A595", "lead": "#7FD6CB", "flat": "#F2C14E",
                "lag": "#F09A82", "lag_strong": "#DB5235", "none": "#C9D1D9"}


def tile_shade(v: float | None, flat_band: float) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return _TILE_SHADES["none"]
    if abs(v) <= flat_band:
        return _TILE_SHADES["flat"]
    strong = abs(v) > flat_band * 5
    if v > 0:
        return _TILE_SHADES["lead_strong" if strong else "lead"]
    return _TILE_SHADES["lag_strong" if strong else "lag"]


def tiles(items: list[tuple[str, str, float | None]], flat_band: float, columns: int = 4) -> None:
    """items: (title, subtitle, % change)."""
    cells = []
    for title, sub, v in items:
        txt = "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:+.2f}%"
        sub_html = f'<div class="mh-s">{html.escape(sub)}</div>' if sub else ""
        cells.append(f'<div class="mh-tile" style="background:{tile_shade(v, flat_band)}" '
                     f'title="{html.escape(title)}"><div class="mh-v">{txt}</div>'
                     f'<div class="mh-t">{html.escape(title)}</div>{sub_html}</div>')
    legend = (f'<div class="mh-legend"><span style="--c:{_TILE_SHADES["lag"]}">lagging</span>'
              f'<span style="--c:{_TILE_SHADES["flat"]}">flat (±{flat_band:g}%)</span>'
              f'<span style="--c:{_TILE_SHADES["lead"]}">leading</span></div>')
    st.markdown(_TILE_CSS + f'<div class="mh-grid" style="grid-template-columns:repeat({columns},minmax(0,1fr))">'
                + "".join(cells) + "</div>" + legend, unsafe_allow_html=True)
