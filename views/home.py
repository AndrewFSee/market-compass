"""Hub home: what's registered and how fresh each project's data is."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from core import store, ui
from registry import JOBS, LINKS, PAGES

st.title("Dashboard hub")
st.write("One place for all your project dashboards. Pages are in the sidebar; "
         "data refreshes when `run_jobs.py` runs.")

st.subheader("Data freshness")
m = store.manifest()
if not m:
    st.info("No project has published data yet. Run `python run_jobs.py` "
            "(or `python run_jobs.py --demo`) from the project folder.")
else:
    now = datetime.now(timezone.utc)
    rows = []
    for module, datasets in sorted(m.items()):
        latest = max(pd.Timestamp(t) for t in datasets.values())
        hours = (now - latest.to_pydatetime()).total_seconds() / 3600
        rows.append({"Project": module, "Datasets": len(datasets),
                     "Last updated": latest.tz_convert(None).strftime("%Y-%m-%d %H:%M UTC"),
                     "Age": f"{hours:.0f} h" if hours < 48 else f"{hours / 24:.0f} days",
                     "Status": "Fresh" if hours < 30 else "Stale"})
    ui.table(pd.DataFrame(rows), hide_index=True)

st.subheader("Registered")
c1, c2 = st.columns(2)
with c1:
    st.markdown("**Pages**")
    for section, pages in PAGES.items():
        st.markdown(f"{section}: " + ", ".join(p["title"] for p in pages))
    if LINKS:
        st.markdown("**Linked dashboards:** " + ", ".join(f"[{l['title']}]({l['url']})" for l in LINKS))
with c2:
    st.markdown("**Data jobs**")
    for name, target in JOBS.items():
        st.markdown(f"`{name}` → `{target}`")

with st.expander("Adding a project"):
    st.markdown(
        "1. **Quickest:** add the project's Streamlit script to `PAGES` in `registry.py` (absolute path is fine). "
        "Remove any `st.set_page_config` call from it - the hub sets that once.\n"
        "2. **Better, over time:** split the project into a *job* that saves results with "
        "`core.store.save_frame(...)` and a *page* that only reads them. Register the job in `JOBS` "
        "so `run_jobs.py` refreshes it, and other pages can reuse its data.\n"
        "3. **Keep it separate:** add it to `LINKS` and it shows up as a sidebar link."
    )
