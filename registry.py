"""The one place to register projects with the hub.

PAGES  - what appears in the sidebar, grouped by section. "path" is a page script,
         relative to this folder or absolute (e.g. an existing project's app file).
LINKS  - dashboards you'd rather keep running on their own; shown as sidebar links. With an
         "app" entry ({"cmd", "cwd"}), clicking the link starts it on the link's port if it's
         down (views/launch.py), and `python start_apps.py` starts them all.
JOBS   - data refresh run by `python run_jobs.py`. Either
           "module.path:function"  - imported and called in the hub's own Python as
                                     fn(demo=bool, log=callable), or
           {"cmd": [python, script, ...], "cwd": folder}
                                   - another project's publish script, run with that
                                     project's own venv. It gets HUB_DATA_DIR and the hub
                                     folder on PYTHONPATH (so `from core import store`
                                     works), plus `--demo` when the hub runs with --demo.
"""

import os
from pathlib import Path

# my other projects sit next to this one, unless HUB_PROJECTS_DIR says otherwise
PROJECTS = Path(os.environ.get("HUB_PROJECTS_DIR") or Path(__file__).resolve().parent.parent)


def project(name: str) -> Path:
    """A project's folder: PROJECTS/<name>, or PROJECTS/<name>/<name> when it was cloned
    into a folder of the same name. A repo whose package shares its name (augury/augury/)
    has its .git in the outer folder, so that one is the project."""
    outer = PROJECTS / name
    nested = outer / name
    return nested if nested.is_dir() and not (outer / ".git").exists() else outer


def venv_python(project: Path) -> str:
    """The project's own venv interpreter (Windows or macOS/Linux layout)."""
    if os.name == "nt":
        return str(project / ".venv" / "Scripts" / "python.exe")
    return str(project / ".venv" / "bin" / "python")


def streamlit_app(project: Path, script: str, port: int) -> dict:
    """Launch spec for a project's own Streamlit app, run with that project's venv."""
    return {"cmd": [venv_python(project), "-m", "streamlit", "run", script, "--server.port", str(port),
                    "--server.headless", "true"], "cwd": str(project)}


CREDIT = project("credit-spread-analyzer")
MACRO = project("macro-regime-nowcaster")
VOL = project("stochastic-vol-surface")
TAILRISK = project("tail-risk-scenario-engine")
TICKERLAKE = project("TickerLake")
AUGURY = project("augury")

PAGES = {
    "Hub": [
        {"path": "views/home.py", "title": "Home", "icon": ":material/home:", "default": True},
    ],
    "Markets": [
        {"path": "modules/market/page.py", "title": "Market Environment", "icon": ":material/monitoring:"},
        {"path": "modules/credit/page.py", "title": "Credit", "icon": ":material/account_balance:"},
        {"path": "modules/macro/page.py", "title": "Macro Regime", "icon": ":material/public:"},
        {"path": "modules/vol/page.py", "title": "Volatility", "icon": ":material/ssid_chart:"},
        {"path": "modules/augury/page.py", "title": "Risk Forecasts", "icon": ":material/query_stats:"},
    ],
    "Research": [
        {"path": "modules/analogs/page.py", "title": "Look-alikes", "icon": ":material/history:"},
        {"path": "modules/analyst/page.py", "title": "Analyst", "icon": ":material/psychology:"},
    ],
    "Portfolio": [
        {"path": "modules/tailrisk/page.py", "title": "Tail Risk", "icon": ":material/warning:"},
    ],
    # Example - add your existing Streamlit projects like this:
    # "Credit": [
    #     {"path": "/Users/you/projects/credit_spreads/app.py", "title": "Credit Spreads",
    #      "icon": ":material/trending_up:"},
    # ],
}

LINKS = [
    # each project's full app; its sidebar link starts it if it isn't running
    {"title": "Credit Spread Analyzer (full)", "url": "http://localhost:8502",
     "app": streamlit_app(CREDIT, "src/dashboard/app.py", 8502)},
    {"title": "Macro Regime Nowcaster (full)", "url": "http://localhost:8503",
     "app": streamlit_app(MACRO, "src/dashboard/app.py", 8503)},
    {"title": "Vol Surface (full)", "url": "http://localhost:8504",
     "app": streamlit_app(VOL, "src/dashboard/app.py", 8504)},
    {"title": "Tail Risk Engine (full)", "url": "http://localhost:8505",
     "app": streamlit_app(TAILRISK, "app/streamlit_app.py", 8505)},
    {"title": "Augury Risk Monitor (full)", "url": "http://localhost:8506",
     "app": streamlit_app(AUGURY, "dashboard/app.py", 8506)},
]

JOBS = {
    # credit runs first so the market gauges pick up its spliced HY spread history
    "credit": {"cmd": [venv_python(CREDIT), "scripts/publish_to_hub.py"], "cwd": str(CREDIT)},
    "market": "modules.market.job:run",
    "analogs": "modules.analogs.job:run",  # reads market + credit output, so after both
    "macro": {"cmd": [venv_python(MACRO), "scripts/publish_to_hub.py"], "cwd": str(MACRO), "timeout": 1800},
    "vol": {"cmd": [venv_python(VOL), "scripts/publish_to_hub.py"], "cwd": str(VOL)},
    "tailrisk": {"cmd": [venv_python(TAILRISK), "scripts/publish_to_hub.py"],
                 "cwd": str(TAILRISK)},
    # 1/5/21-day forecast distributions + daily VaR track record; first run builds the record (~6 min)
    "augury": {"cmd": [venv_python(AUGURY), "scripts/publish_to_hub.py"], "cwd": str(AUGURY), "timeout": 1800},
    # sector EPS revisions and analyst actions from the lake (TickerLake's daily analyst stage fetches)
    "revisions": {"cmd": [venv_python(TICKERLAKE), "scripts/publish_to_hub.py"], "cwd": str(TICKERLAKE)},
    "analyst": "modules.analyst.job:run",  # last: reads everything the others published
}
