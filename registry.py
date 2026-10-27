"""The one place to register projects with the hub.

PAGES  - what appears in the sidebar, grouped by section. "path" is a page script,
         relative to this folder or absolute (e.g. an existing project's app file).
LINKS  - dashboards you'd rather keep running on their own; shown as sidebar links.
JOBS   - data refresh run by `python run_jobs.py`. Either
           "module.path:function"  - imported and called in the hub's own Python as
                                     fn(demo=bool, log=callable), or
           {"cmd": [python, script, ...], "cwd": folder}
                                   - another project's publish script, run with that
                                     project's own venv. It gets HUB_DATA_DIR and the hub
                                     folder on PYTHONPATH (so `from core import store`
                                     works), plus `--demo` when the hub runs with --demo.
"""

PAGES = {
    "Hub": [
        {"path": "views/home.py", "title": "Home", "icon": ":material/home:", "default": True},
    ],
    "Markets": [
        {"path": "modules/market/page.py", "title": "Market Environment", "icon": ":material/monitoring:"},
    ],
    # Example - add your existing Streamlit projects like this:
    # "Credit": [
    #     {"path": "/Users/you/projects/credit_spreads/app.py", "title": "Credit Spreads",
    #      "icon": ":material/trending_up:"},
    # ],
}

LINKS = [
    # {"title": "Old options dashboard", "url": "http://localhost:8502"},
]

JOBS = {
    "market": "modules.market.job:run",
    # "credit": "credit_spreads.publish:run",   # once that project publishes into the hub
}
