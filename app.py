"""Hub entry point:  streamlit run app.py"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
