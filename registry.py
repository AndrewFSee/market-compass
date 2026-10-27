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

from pathlib import Path

PROJECTS = Path(__file__).resolve().parent.parent  # my other projects sit next to this one


def venv_python(project: Path) -> str:
    return str(project / ".venv" / "Scripts" / "python.exe")


CREDIT = PROJECTS / "credit-spread-analyzer"
MACRO = PROJECTS / "macro-regime-nowcaster" / "macro-regime-nowcaster"
VOL = PROJECTS / "stochastic-vol-surface" / "stochastic-vol-surface"
TAILRISK = PROJECTS / "tail-risk-scenario-engine"

PAGES = {
    "Hub": [
        {"path": "views/home.py", "title": "Home", "icon": ":material/home:", "default": True},
    ],
    "Markets": [
        {"path": "modules/market/page.py", "title": "Market Environment", "icon": ":material/monitoring:"},
        {"path": "modules/credit/page.py", "title": "Credit", "icon": ":material/account_balance:"},
        {"path": "modules/macro/page.py", "title": "Macro Regime", "icon": ":material/public:"},
        {"path": "modules/vol/page.py", "title": "Volatility", "icon": ":material/ssid_chart:"},
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
    # full project apps, started separately (see each module's config for the command)
    {"title": "Credit Spread Analyzer (full)", "url": "http://localhost:8502"},
    {"title": "Macro Regime Nowcaster (full)", "url": "http://localhost:8503"},
    {"title": "Vol Surface (full)", "url": "http://localhost:8504"},
    {"title": "Tail Risk Engine (full)", "url": "http://localhost:8505"},
]

JOBS = {
    # credit runs first so the market gauges pick up its spliced HY spread history
    "credit": {"cmd": [venv_python(CREDIT), "scripts/publish_to_hub.py"], "cwd": str(CREDIT)},
    "market": "modules.market.job:run",
    "macro": {"cmd": [venv_python(MACRO), "scripts/publish_to_hub.py"], "cwd": str(MACRO), "timeout": 1800},
    "vol": {"cmd": [venv_python(VOL), "scripts/publish_to_hub.py"], "cwd": str(VOL)},
    "tailrisk": {"cmd": [venv_python(TAILRISK), "scripts/publish_to_hub.py"],
                 "cwd": str(TAILRISK)},
}
