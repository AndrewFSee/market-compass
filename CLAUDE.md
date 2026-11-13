# Dashboard Hub - notes for Claude Code

Personal Streamlit hub that collects several dashboard projects in one app. The first
module is a market regime/breadth dashboard inspired by indicators seen in RIA's
SimpleVisor. The aim is to build my own versions of those indicators from public data
and extend them over time; do not copy SimpleVisor branding, layouts or proprietary
scores.

## Commands
- Install: `pip install -r requirements.txt` (use the project's `.venv`)
- Refresh data: `python run_jobs.py` (real data) / `python run_jobs.py --demo` (synthetic, no network)
- One job only: `python run_jobs.py --only market`
- Run the app: `streamlit run app.py`, or `python start_apps.py` for the hub plus every project's
  full app (ports 8502-8506; `--status`, `--stop`; logs in `data/logs/apps/`). The sidebar's
  "Other dashboards" links go through the hidden page `views/launch.py` (`/launch?app=<port>`),
  which starts a stopped app (`core/apps.py`, shared with `start_apps.py`) and then forwards to it.
- Tests: `python -m pytest -q` (runs the full pipeline on demo data and renders pages headlessly)

## Architecture - keep this split
- **Jobs compute, pages display.** A job fetches + computes and saves results with
  `core.store.save_frame(module, name, df)` / `save_json(...)` into `data/<module>/`.
  Pages only read with `store.load_frame` / `load_json` (cached on file mtime). Never
  fetch from the network inside a page.
- `registry.py` is the single place to register pages (`PAGES`), sidebar links (`LINKS`)
  and data jobs (`JOBS`). A job is either `"module:function"` (run in the hub's Python as
  `fn(demo=bool, log=callable)`) or `{"cmd": [...], "cwd": ...}` - another project's publish
  script run with **that project's own venv**, so the hub never needs its dependencies. The
  child gets `HUB_DATA_DIR`, the hub on `PYTHONPATH` (`from core import store`) and `--demo`.
- `run_jobs.py` loads secrets from the git-ignored `.env` (`core/env.py`) and holds
  `data/jobs.lock` so a scheduled and a manual refresh can't overlap.
- FRED: set `FRED_API_KEY` in `.env`. The keyless `fredgraph.csv` endpoint resets connections
  from this machine; it is only a slow sequential fallback.
- Windows Smart App Control is on here and can block venv `python.exe`/`pythonw.exe` and
  scheduled tasks (result `0x800711C7`, CodeIntegrity event 3077). Check that before
  debugging a job that "silently" fails.
- New project = new folder under `modules/<name>/` with `config.py`, `job.py`, `page.py`
  (and `indicators.py` for pure calculations), then register it.
- `core/ui.py` holds shared visuals (gauge, donut, tiles) and Streamlit-version shims
  (`ui.chart`, `ui.table`, `ui.choice`). Use these rather than calling `st.plotly_chart` directly.

## Market module conventions
- Each gauge summary carries `trend` (reading N periods back, `GAUGE_TREND`) and `vs_spy`
  (`indicators.market_link`: coincident r, next-period Spearman on non-overlapping periods,
  next-period return by band). Next-period stats use readings `GAUGE_PUBLICATION_LAG`
  periods after their date; keep that when adding gauges built on lagged data.
- SPY is also pulled with full history (`BENCHMARK_LONG_PERIOD`) for the technical gauge
  and those stats; `gauge_history` / `econ_history` include a `spy` column for the charts.
- All tickers, FRED series, indicator recipes, gauge bands and labels live in
  `modules/market/config.py`. Change recipes there, not in the page.
- `indicators.py` is pure pandas (no I/O) so it stays testable. Every gauge returns a
  `Composite(value, raw, scores, extra)`.
- Data sources: FRED API (`FRED_API_KEY`, keyless CSV as fallback), Yahoo Finance via `yfinance`,
  Wikipedia for index members. Breadth uses S&P 500 members as an NYSE proxy.
- Any new input must also get a synthetic version in `modules/market/demo.py` so
  `--demo` and the tests keep working offline.
- Keep `python -m pytest -q` passing after every change; add a test for new calculations.
- Rotation map (`job.rotation`, `indicators` rotation section, settings `ROTATION_*`): weekly
  ETF/SPY ratio; trend = 26-wk gap in sd, momentum = its 4-wk change, overbought/oversold =
  14-wk RSI of the ratio. Uses full-history downloads (`ROTATION_PERIOD`) so `rotation_stats`
  can test candidates before/after `ROTATION_SPLIT`. Measured 2026-11-01: no candidate ranks
  next-4-week winners reliably (best: 12-1 momentum, IC +0.03-0.08, t <= 2); clockwise
  motion is mostly arithmetic (momentum = change in trend); sectors at relative RSI >= 70
  trailed the group ~0.4% over 4 weeks in both halves (55% hit). The page's expander states
  this from the numbers; keep it that way if the recipe changes.
- Sector internals / leadership / cross-asset (`job.sector_internals`, `leadership`, `cross_asset`;
  settings `INTERNALS_*`, `CONTRIBUTION_WINDOWS`, `LEADERSHIP_WEEKS`, `CROSS_ASSET*`): S&P 500 members
  mapped to sector ETFs by GICS (`GICS_TO_ETF`); weights = today's cap with share count held
  fixed, so contributions approximate the ETFs' holdings. Participation test covers only the
  5 years of member prices and today's members (survivorship). Measured 2026-11-07: ranking
  sectors by % of members beating SPY had IC +0.055 (t 1.3); falling momentum with broad
  participation did not trail falling + narrow (the opposite). Cross-asset links (signed corr of
  weekly changes, since ~1999): oil/XLE +0.58, HY spread/offense-defense +0.42, 10Y/XLRE +0.38,
  10Y/XLU +0.28, curve/XLF +0.17, copper-gold/XLB +0.14. Commodity drivers are Yahoo futures
  (CL=F, HG=F, GC=F), downloaded with the rotation history.
- Fund flows (`job.fund_flows`, `FLOW_*`): State Street NAV-history xlsx per sector SPDR (needs
  openpyxl), since 2003-12. Flow = change in shares x NAV; splits (Dec 2025 2-for-1s), each
  fund's first 63 days and days moving >50% of assets (XLRE's 2016 spin-off) are excluded;
  signals lag one day. Measured 2026-11-07: no predictive link in either half.
- `core.store` retries `os.replace` on PermissionError: on Windows a reader (the running hub)
  briefly blocks replacing a file, which once failed a market run.

## Integrating my other Streamlit projects
- Quick: add the project's script to `PAGES` with an absolute path and remove its
  `st.set_page_config` call (the hub sets it once).
- Preferred: split it into a job that publishes into the hub data folder plus a page that
  only reads (see the status below for the four already done this way).

## Integrated projects (2026-10-26)
Each has `scripts/publish_to_hub.py` in its own repo (on `main`, pushed 2026-10-31), run by `run_jobs.py` with that project's
venv (see `JOBS` in `registry.py`), a read-only page `modules/<name>/page.py`, and its full app
as a `LINKS` entry with an `app` launch spec (ports 8502-8506, started by `start_apps.py`).
Publishers are thin: they call the project's own validated functions, never re-implement them.
- **credit** (credit-spread-analyzer) -> `data/credit/`: spreads, spreads_bps, stress,
  exposure, tiers, forecast, summary.json. Runs before "market". That project stores spreads
  in **bps**; `spreads` is converted to % points for `CREDIT_OVERRIDE` (on). HY is spliced to
  1996 from a licensed file. Its fetcher writes a new ~1.7 MB `data/market_data_*.parquet`
  cache per day (not pruned). Its stress HMM (3 states on Baa levels, refitted each January)
  is near-binary and its regime flips cluster on refit days (6 of 35 year starts vs 0.5% of
  other days, with the spread unchanged): a property of that model, shown as-is on the page.
- **macro** (macro-regime-nowcaster) -> `data/macro/`: walk_forward (copied from its
  `data/features.csv`), summary.json (live nowcast, config from `config/settings.yaml` as in
  `run_nowcast.py`). Only the walk-forward panel is used as history: a single
  `Nowcaster.run()` history is in-sample. The panel is not rebuilt by the job
  (`scripts/build_features.py --start 1967-01-31`, ~3 h); the monthly task below rebuilds it,
  and the page warns when it is >45 days old.
- **vol** (stochastic-vol-surface) -> `data/vol/`: overview, history, market, forecasts,
  summary.json. No network: reads what the project's own scheduled scrapers wrote, so the
  page flags missed sessions (the scrapers are the Task Scheduler jobs DailyScraper /
  PrecloseScraper).
- **tailrisk** (tail-risk-scenario-engine) -> `data/tailrisk/`: fan, pnl_hist, summary.json
  (incl. hedges with puts priced at the VIX, and stress scenarios from its configs/scenarios).
  One simulation feeds metrics, hedges and the CVaR optimiser. Venv rebuilt 2026-10-26.
  Fixed there 2026-10-26/27: GARCH-t `mu` used as drift; single-asset copula crash;
  marginals/copula fitted on raw returns instead of GARCH-standardized residuals (double-
  counted fat tails, kurtosis 20-120); regime paths started from the long-run mix instead of
  today; 1-day backtest recursion fed each shock in twice; fixed 1.2% put premium; hedge P&L
  mixed log and simple returns; parametric stress scenarios were never applied. It now has
  `tailrisk stress` and `tailrisk validate` (walk-forward of the full 21-day engine). Results
  move ~0.2 pts run to run because Yahoo's adjusted prices differ slightly per download.
- **revisions** (TickerLake) -> `data/revisions/`: sector_revisions, revisions_history,
  revisions_names, summary.json. TickerLake's `analyst` stage (yfinance, no key) snapshots every
  member's EPS consensus daily into `analyst_estimates` and keeps broker rating changes since
  ~2012 in `analyst_ratings` (`tickerlake backfill analyst` for all past members). The publisher
  reads the lake only. The stage runs right after ohlcv in TickerLake-Daily (17:30) so the 18:15
  hub refresh gets the same day's snapshot. Rating changes were backtested there
  (`scripts/backtest_analyst_ratings.py`, 2026-11-07): the move happens before the next open;
  drift after it doesn't beat costs.
- **augury** (augury, added 2026-11-10) -> `data/augury/`: forecast (ticker x horizon 1/5/21: VaR/ES,
  90% price range, vol_ann, gjr_vol_ann, realised_vol_21d, iv), bands (21-day price quantiles), prices
  (last 260 closes), track (every walk-forward forecast since 2016 with outcome: y, var_1/var_5, hit_*,
  cov_*, crps, pit; models "augury" and, for IV tickers, "gjr"), summary.json (groups, models, iv_views,
  per-ticker scores incl. last-250-day Basel zone, errors). The publisher downloads from Yahoo, cuts
  partial bars (`augury.monitoring.last_final_session`, 4:15 PM New York) and extends the stored track
  record, recomputing only ~40 trailing origins on the original refit schedule (first run ~7 min for
  28 tickers, then ~25 s; `--rebuild` starts over, `--only SPY,QQQ` merges). The page (Risk Forecasts)
  complements Volatility: full return distribution at 1/5/21 days and a daily VaR backtest, not a vol
  level. Full app: augury's `dashboard/app.py` on port 8506 (any ticker, drift/vol views).
- **breadth** (TickerLake, job before "market") -> `data/breadth/`: nyse (the hub's own
  `indicators.breadth` on dividend-adjusted closes of every NYSE common stock, plus `stocks`,
  `provisional`), summary.json. TickerLake's `listings` stage snapshots Nasdaq Trader's symbol
  directories daily (classifies common/preferred/warrant/unit/right/note/etf); `listed_ohlcv`
  (subclass of its ohlcv fetcher, own dataset, never the membership table) keeps bars since 2016.
  Yahoo posts most NYSE names' daily bar hours after the close (11 of 40 at 21:30 on 11-12), so
  the 17:30 run builds missing bars from hourly bars (source `yfinance_1h`), replaced next run.
  Raw closes understate breadth (high-payout CEFs/REITs/MLPs): 11-12 above 20/50/200 = 50.8/47.8/
  41.9 raw, 51.8/50.1/46.2 adjusted vs SimpleVisor 55/53/49 (S&P members 66.9/70.6/65.1). The
  market page defaults to NYSE; gauges still use S&P member breadth.
- **events** (TickerLake) -> `data/events/`: calendar, odds, fed, assets, other, history,
  summary.json; page `modules/events` (Events & Odds). TickerLake `econ_calendar` (FRED release
  dates for a curated list in its config; FOMC/ISM dates from Kalshi close times; FRED dates
  "FOMC Press Release" every day, which is what broke SimpleVisor's calendar) and
  `prediction_markets` (Kalshi + Polymarket public APIs, daily snapshot; `tickerlake.analytics.
  prediction` turns ladders into implied medians). Odds history starts 2026-11-12.
- Projects are found next to the hub (`registry.project()`: `<name>` or `<name>/<name>`; override
  with `HUB_PROJECTS_DIR`). A job whose project or venv is missing is skipped, not failed.
- Tests here use synthetic data in each publisher's schema; if a publisher's output changes,
  update the matching fake in `tests/test_smoke.py`.

## Scheduling
- `scripts/register_task.ps1` registers `\MarketCompass\HubRefresh` (weekdays 6:15 PM, pythonw,
  S4U), after the vol scrapers (`\StochasticVolSurface\DailyScraper` 4:30 PM). The user runs
  it; registering persistent tasks needs their approval.
- `scripts/register_panel_task.ps1` registers `\MarketCompass\MacroPanelRebuild` (20th of each
  month, 8 PM, S4U; registered 2026-11-08, needs an elevated prompt). It is XML-defined (the cmdlets
  have no monthly trigger) and runs `scripts/rebuild_macro_panel.py`: deletes a features.partial.csv
  older than a day (resuming pins that run's FRED cache), keeps features.prev.csv and restores it
  if the new panel is shorter, then runs `run_jobs.py --only macro`. Log: `data/logs/macro_panel.log`.
- Task triggers created with a UTC offset (`...T16:30:00-04:00`) fire an hour early after DST
  ends. `scripts/fix_task_timezones.ps1` strips the offset so they follow local time; S4U tasks
  (HubRefresh, DailyScraper, PrecloseScraper, TickerLake-Daily) need an elevated prompt.

## Look-alikes (modules/analogs)
- Job "analogs" runs after "market" (reads `market/long_history` and `credit/spreads`, no
  network). `engine.py` is pure: `build_state` (features in `config.FEATURES`, each shifted by
  its publication lag), `find_analogs` (z-scores on data up to the test date, weighted RMS
  distance, distinct episodes >= `SEPARATION_DAYS` apart, candidates end `PATH_DAYS` before
  the date so outcomes are known), `evaluate` (walk-forward, non-overlapping months).
- Measured 2026-10-27: no skill on direction (rank corr -0.03, 297 months); next-month vol
  0.48 vs 0.58 for "last month's vol continues", adding 0.21 beyond it. The page states
  this from the numbers; keep it that way if features change.
- The economic gauge is deliberately not a feature (revised data, full-sample weights).

## Analyst (modules/analyst)
- Claude (`config.MODEL`, claude-opus-5-5) via the SDK tool runner with read-only tools in
  `tools.py` (plain functions over the hub store; `agent.py` wraps them with `@beta_tool`).
  Server-side refusal fallback is on (`fallbacks="default"` + `config.FALLBACK_BETA`).
- Job "analyst" runs last and writes `analyst/brief.json` + `brief_history.json` (one per
  day, `BRIEFS_KEPT`). Without credentials it logs a skip, it doesn't fail the run.
- The page's chat is the one deliberate exception to "pages never call the network".
- Each brief attempt writes `analyst/last_attempt.json` (ok + a one-line reason, e.g. a 401 means the
  key was rejected). The page warns when the latest attempt failed after the brief it shows; the job
  still raises so run_jobs logs it as FAILED.
- Tools say what lag is normal so briefs don't report it as missing data: the economic gauge's
  final month trails by 1-2 months (75% coverage rule); the macro panel is a monthly-rebuilt
  walk-forward history (~3 h, rows knowable 60 days after their month); HYG's thin chain often
  misses the 30-day fit, so `vol_overview` adds the last available reading with its date.
- Needs `ANTHROPIC_API_KEY` in `.env` (app.py and run_jobs.py load it). Tests never call
  the API: they fake the client / `agent.ask`.

## Data quirks
- Yahoo can serve today's row half-filled after the close (e.g. VIX but not SPY);
  `job.last_complete_session` cuts all market prices to the last complete session.

## Open items / ideas
- Liquidity gauge never reached its LOOSE band (>35) in 5 years of real history (max ~34):
  the band cut-offs or the averaging of 8 z-scores probably need calibrating.
- Technical gauge ranks components against a mostly-bullish 2 years, so ordinary pullbacks
  read BEARISH (e.g. 25 with SPY 5.7% above its 200-day). Consider a longer window.
- Calibrate gauges against SimpleVisor readings during the trial (log both daily).
- FMP (checked 2026-11-07): no fund-flow endpoint; analyst estimates are current consensus only
  (Starter: annual, US); Starter has historical analyst grades for US stocks, which Yahoo also
  serves free (TickerLake `analyst_ratings`), so there is nothing to backtest before buying.
- Test whether gauges built on NYSE breadth track SimpleVisor better than S&P member breadth.
- Possible additions: put/call ratio component, 52-week high/low
  history panel, sector/factor relative-strength analysis page, alerts when a gauge
  crosses a band.

## GitHub
- Public at github.com/AndrewFSee/market-compass. The README is written for visitors: it explains
  cloning the four companion repos next to this one, and embeds `docs/screenshots/*.png`.
- Screenshots were taken from the running hub (real data, dark theme) with headless Chrome via Playwright in a
  throwaway venv, then cropped to the main column. Retake them if a page's layout changes a lot.
- `.env.example` lists the keys; `.env` stays git-ignored. Never commit data/ or keys.
