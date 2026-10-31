"""Opens a linked project app (LINKS in registry.py), starting it first if it isn't running.

The sidebar links point here as /launch?app=<port>, so one click starts the app, waits for
it to answer and then forwards the tab to it."""
import time

import streamlit as st

from core import apps
from registry import LINKS

WAIT_SECONDS = 90  # a cold Streamlit start with heavy imports can take a while


@st.cache_resource
def launched() -> dict:
    """port -> Popen for apps started from here, shared by all sessions (no double starts)."""
    return {}


def forward(url: str) -> None:
    st.html(f"<script>window.location.replace({url!r});</script>", unsafe_allow_javascript=True)
    st.link_button("Open it", url, icon=":material/open_in_new:")  # if the redirect is blocked


port = st.query_params.get("app", "")
link = next((l for l in LINKS if l.get("app") and str(apps.port_of(l["url"])) == port), None)
if link is None:
    st.error("Unknown app. Use the links in the sidebar.")
    st.stop()

st.title(link["title"])
if apps.is_up(int(port)):
    forward(link["url"])
    st.stop()

gone = apps.missing(link["app"])
if gone:
    st.error(f"Can't start it: {gone} doesn't exist.", title="Missing project files")
    st.stop()

procs = launched()
proc = procs.get(port)
if proc is None or proc.poll() is not None:
    proc = procs[port] = apps.start(link["app"], int(port))

with st.spinner("Starting the app..."):
    deadline = time.time() + WAIT_SECONDS
    while not apps.is_up(int(port)) and proc.poll() is None and time.time() < deadline:
        time.sleep(0.5)

if apps.is_up(int(port)):
    forward(link["url"])
else:
    log = apps.log_path(int(port))
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:] if log.exists() else []
    reason = (f"exited with code {proc.returncode}" if proc.poll() is not None
              else f"isn't answering after {WAIT_SECONDS} s")
    st.error(f"The app {reason}. Last lines of {log}:", title="Didn't start")
    st.code("\n".join(tail) or "(empty log)")
    if st.button("Try again", icon=":material/refresh:"):
        st.rerun()
