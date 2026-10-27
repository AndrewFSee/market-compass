"""Analyst page: the nightly brief plus a chat.

The brief is read from the hub data folder like any page. The chat is the one deliberate
exception to "pages never call the network": each question goes to the Claude API, whose
tools in turn only read the hub data folder."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from core import env, store
from modules.analyst import config as cfg

MODULE = cfg.MODULE
env.load()  # ANTHROPIC_API_KEY from the hub's .env


@st.cache_data(show_spinner=False)
def _cached(name: str, stamp):
    return store.load_json(MODULE, name)


def load(name: str):
    return _cached(name, store.stamp(MODULE, name))


def usage_note(res: dict) -> str:
    u = res.get("usage") or {}
    tools = sorted({c["name"] for c in res.get("tool_calls", [])})
    return (f"{len(res.get('tool_calls', []))} tool calls ({', '.join(tools) or 'none'}) · "
            f"{u.get('input_tokens', 0):,} in / {u.get('output_tokens', 0):,} out tokens"
            + (f" ({u.get('cache_read_input_tokens', 0):,} cached)" if u.get("cache_read_input_tokens") else ""))


SETUP = ("Add your Anthropic API key to the hub's `.env` file as `ANTHROPIC_API_KEY=...`, then run "
         "`python run_jobs.py --only analyst` (it also runs in the nightly refresh).")

# ================================================================= brief
st.title("Analyst")
history = load("brief_history") or []
brief = load("brief")
if not brief:
    st.info("No brief yet. " + SETUP)
else:
    options = [b["generated"] for b in history] or [brief["generated"]]
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    with c2:
        pick = st.selectbox("Brief", options, format_func=lambda g: datetime.fromisoformat(g).strftime("%a %b %d, %H:%M"),
                            key="an_brief", label_visibility="collapsed")
    shown = next((b for b in history if b["generated"] == pick), brief)
    with c1:
        st.caption(f"Written {datetime.fromisoformat(shown['generated']):%b %d, %Y %I:%M %p} by {shown['model']} "
                   f"from data through {shown.get('data_as_of')}. Every figure comes from the dashboard's own data; "
                   "check anything that matters on its page.")
    with st.container(border=True):
        st.markdown(shown["text"])
    with st.expander("What the analyst looked at"):
        st.caption(usage_note(shown))
        for c in shown.get("tool_calls", []):
            args = ", ".join(f"{k}={v!r}" for k, v in (c.get("input") or {}).items())
            st.markdown(f"- `{c['name']}({args})`")

# ================================================================= chat
st.subheader("Ask about the data")
st.caption(f"Each question is answered live by {cfg.MODEL} using the same read-only tools and is billed to your "
           "API key; the tokens used are shown under each answer. The conversation resets when you reload the page.")
chat = st.session_state.setdefault("analyst_chat", [])
for turn in chat:
    with st.chat_message(turn["role"]):
        st.markdown(turn.get("display", turn["content"]))
        if turn.get("note"):
            st.caption(turn["note"])

question = st.chat_input("e.g. Why is liquidity tight? Is credit agreeing with the equity gauges?")
if question:
    with st.chat_message("user"):
        st.markdown(question)
    api_messages = [{"role": t["role"], "content": t["content"]} for t in chat]
    first = question
    if not chat and brief:  # give the first question this morning's brief as context
        first = (f"For context, this is today's brief (written {brief['generated']}):\n\n{brief['text']}\n\n"
                 f"My question: {question}")
    api_messages.append({"role": "user", "content": first})
    from modules.analyst import agent

    with st.chat_message("assistant"):
        try:
            with st.spinner("Looking at the data..."):
                res = agent.ask(api_messages, effort=cfg.EFFORT["chat"])
        except agent.NoCredentials:
            st.error("No Anthropic credentials. " + SETUP)
            st.stop()
        except Exception as e:  # noqa: BLE001 - show API errors in the chat rather than a traceback
            st.error(f"The request failed: {type(e).__name__}: {e}")
            st.stop()
        st.markdown(res["text"])
        st.caption(usage_note(res))
    chat.append({"role": "user", "content": first, "display": question})
    chat.append({"role": "assistant", "content": res["text"], "note": usage_note(res)})
