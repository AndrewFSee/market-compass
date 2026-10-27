"""Hub entry point:  streamlit run app.py"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def forget_changed_modules(prefixes=("core", "modules", "registry")) -> list[str]:
    """Drop the hub's own modules whose source changed since they were imported.

    Streamlit re-reads page scripts on every run but keeps imported modules, so editing
    e.g. modules/credit/config.py while the server runs leaves pages on the old config
    (AttributeError on anything new). Dropped modules are imported fresh by the pages."""
    dropped = []
    for name, mod in list(sys.modules.items()):
        path = getattr(mod, "__file__", None)
        if not path or name.split(".")[0] not in prefixes or not path.startswith(str(ROOT)):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        loaded = mod.__dict__.setdefault("__hub_mtime__", mtime)
        if mtime > loaded:
            del sys.modules[name]
            dropped.append(name)
    return dropped


forget_changed_modules()
from registry import LINKS, PAGES  # noqa: E402

st.set_page_config(page_title="Dashboard Hub", page_icon=":material/dashboard:", layout="wide")

nav = {}
for section, pages in PAGES.items():
    entries = []
    for p in pages:
        path = Path(p["path"])
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            st.sidebar.warning(f"Page not found: {p['path']}")
            continue
        if str(path.parent) not in sys.path:  # lets another project's page import its own modules
            sys.path.append(str(path.parent))
        # every page gets a readable, unique URL (many projects name their script app.py)
        slug = p.get("url_path") or re.sub(r"[^a-z0-9]+", "-", p["title"].lower()).strip("-")
        default = p.get("default", False)
        entries.append(st.Page(str(path), title=p["title"], icon=p.get("icon"), default=default,
                               url_path=None if default else slug))
    if entries:
        nav[section] = entries

page = st.navigation(nav)

if LINKS:
    with st.sidebar:
        st.caption("Other dashboards")
        for link in LINKS:
            st.markdown(f"[{link['title']}]({link['url']})")

page.run()
