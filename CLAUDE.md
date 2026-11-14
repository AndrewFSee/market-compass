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
  this from the numbers; keep it that way if the recipe changes. Measured 2026-11-13 (scratch
  script, not in the job): an equal-weight vote of 22 standard daily signals (price vs SMA
  20/50/100/200, SMA crosses and slopes, MACD, RSI-14, Williams %R-36, recent MA crosses), on price
  and on the ETF/SPY ratio, 12 sector ETFs since 2000, 338 non-overlapping 4-week periods: IC vs
  next-4-week return over SPY -0.02 (t -0.9; ~0 in both halves); top-3 minus bottom-3 -0.24% per
  4 weeks (t -1.1); sectors with relative vote > +0.3 did no better than the middle.
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
- Sector dispersion (`indicators.dispersion`: std of 4-week sector returns, 63-day average pairwise
  correlation). Measured 2026-11-13 (scratch script; 9 original SPDRs, 340 non-overlapping 4-week
  periods since 2000, each measure z-scored on 52 weeks): no measure, including the spread of
  technical-vote scores, moves leadership persistence (rank corr of last vs next 4-week return over
  SPY, base -0.04; slopes +0.005..+0.021 per z, |t| < 1, ~0 both halves) or makes stretched sectors
  revert more. Only link: high correlation -> wider dispersion next month (t -3.0). The page caption
  states this; the old "rotation matters most" claim was removed.
- Fund flows (`job.fund_flows`, `FLOW_*`): State Street NAV-history xlsx per sector SPDR (needs
  openpyxl), since 2003-12. Flow = change in shares x NAV; splits (Dec 2025 2-for-1s), each
  fund's first 63 days and days moving >50% of assets (XLRE's 2016 spin-off) are excluded;
  signals lag one day. Measured 2026-11-07: no predictive link in either half.
- Global markets and headline economy (added 2026-11-13; descriptive, no gauge uses them):
  `GLOBAL_MARKETS` (~57 US-listed ETFs: equities by region, bonds, commodities, currencies/bitcoin,
  `GLOBAL_PERIOD` 2y download) -> `ind.market_snapshot` -> `global_markets` (returns 1D/1W/MTD/YTD/1Y on
  adjusted closes, 52-wk range position, vs 50/200-day, 200-day slope, RSI-14, weekly sparkline).
  `HEADLINE_ECON` (fed funds target range, 10Y, 10Y-2Y, unemployment, payrolls change, CPI/core CPI/
  core PCE y/y, real GDP q/q SAAR) -> `ind.headline_econ` -> `headline_econ.json`; daily series compare
  with a month earlier, others with the prior release; the page takes each next release date from
  TickerLake's `events/calendar` (`release` key).
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
  41.9 raw, 51.8/50.1/46.2 adjusted (S&P members 66.9/70.6/65.1; the comparison with the trial
  service's readings lives in git-ignored `data/simplevisor/`). The
  market page defaults to NYSE; gauges still use S&P member breadth.
- **events** (TickerLake) -> `data/events/`: calendar, odds, fed, assets, other, history,
  summary.json; page `modules/events` (Events & Odds). TickerLake `econ_calendar` (FRED release
  dates for a curated list in its config; FOMC/ISM dates from Kalshi close times; FRED dates
  "FOMC Press Release" every day, so a calendar built from FRED alone lists FOMC daily) and
  `prediction_markets` (Kalshi + Polymarket public APIs, daily snapshot; `tickerlake.analytics.
  prediction` turns ladders into implied medians). Odds history starts 2026-11-12, but both venues
  serve past prices: Kalshi `/historical/markets` + `/historical/markets/{t}/candlesticks` (hourly
  bid/ask; daily KXINX/KXNASDAQ100 since 2022-04, ~1,100 days) and Polymarket CLOB `prices-history`
  (needs startTs/endTs; `interval=max` returns nothing for closed markets; gamma `/events/keyset`
  past offset 500). Measured 2026-11-12 on Polymarket daily "Up or Down" (17 tickers, 3,888 markets
  since 2025-10, median volume $2.7k): price at the prior close sits at ~0.50 (mean |p-0.5| 0.017)
  and predicts nothing (slope 0.02, t 0.1); at the open it is worse than a normal model from the gap
  and trailing vol (Brier 0.214 vs 0.202) and its deviations from that model add nothing (t 1.0).
  Measured 2026-11-13 on Kalshi daily S&P 500 / Nasdaq-100 ranges read at 11:30 ET (899 / 865 days
  since 2022-12; older events have no strike fields; series INX/INXD/KXINX, NASDAQ100/D/KX...):
  ranges too wide (central 50% held the close 60% / 56% of days, 80% held 88% / 86%; partly
  mid-quotes of empty-bid buckets). Size of the rest-of-day move: Kalshi IQR rank corr 0.35, about
  VIX1D at 11:30 (0.37, QLIKE -10.12 vs -10.07) and adds nothing beyond it (t 1.2 vs 2.6); beats VIX
  and VXN prev close. Direction (median vs Yahoo 11:30 level, ~680 days): S&P slope +0.5 (t 1.2),
  Nasdaq -0.1 (t -1.2). Kalshi minute candles exist only for minutes with a change; historical
  per-market candles use `close`, live ones `close_dollars`; ~4 requests/s.
- **style** (TickerLake, added 2026-11-13) -> `data/style/`: stocks (latest value/growth, quadrant, each
  factor raw and z), stock_history and sectors (month-ends since 2012-12 + latest session), summary.json
  (incl. the backtest). Method in TickerLake `tickerlake.analytics.style` (tests `tests/test_style.py`):
  CRSP-style factors from `filings_facts`, first-reported values usable the day after filing (a quarter
  counts only once every input it uses has been filed: 22% of quarters had an input, e.g. assets or cash
  flow, first filed as a later comparative, median 282 days after net income), quarterly flows from
  3-month or differenced YTD facts, share counts (period averages, not differenced) on today's split
  basis; value = B/P, trailing E/P, S/P, D/P; growth = 3-yr EPS and sales-per-share trend, capex/assets,
  ROA. The analyst-forecast factors are left out until the estimate snapshots (since 2026-11-07) have
  history. Each factor clipped 2.5/97.5%, z vs the cap-weighted mean; latest caps from
  `market/market_caps` when present. ~2.5 min per run (1M facts). Backtest (2026-11-13, 167 month-ends,
  353-503 members with prices): stock-level rank IC next 1m value +0.004 (t 0.2), growth +0.004 (t 0.4),
  ~0 both halves; cheap-and-growing corner -0.17%/month (t -1.2); sector next-3m IC value -0.05 (t -1.0),
  growth +0.07 (t 1.5). TickerLake's membership file has GICS sectors only for current members, so
  removed members drop out of sector averages (never compare against sector medians for history: a
  blank sector then flags exactly the stocks that later left the index). The page (Value & Growth) states
  this from summary.json and calls itself descriptive; keep it that way if the recipe changes.
- **buybacks** (TickerLake, added 2026-11-13) -> `data/buybacks/`: stocks (current members: last quarter's and
  trailing-year buybacks from `PaymentsForRepurchaseOfCommonStock`, buyback yield, 1-yr split-adjusted share
  count change, remaining authorization and when an increase was last reported, estimated blackout status,
  reopen / next-shut dates, release behind them and its source), blackout_share (business days 2010 -> 90
  days ahead, share of members and of today's cap estimated in blackout, `projected`), summary.json. Method in
  TickerLake `tickerlake.analytics.buybacks` (tests `tests/test_buybacks.py`): window shuts 14 days before
  the fiscal close, reopens 2 business days after the release. Release dates: TickerLake
  `scripts/backfill_earnings_releases.py` (one-off, ~4 min; full SEC submissions incl. older pages, same
  rule as the announcements stage: last Item 2.02 8-K 7..75 days after the close and before the 10-Q/10-K;
  41.6k quarters, 630 companies, 97% matched, median 29 days) -> `data/earnings_releases/`, topped up
  from the announcements stage's dated surprises; upcoming from Finnhub calendar rows, else the company's
  median lag. Membership history starts 2010. Measured 2026-11-13 (scratch `style/buyback_test.py`; numbers
  in `modules/buybacks/config.py` TEST, which the page states): share in blackout vs S&P next 20 days rank
  corr +0.12 (t 1.5, the opposite of the "blackout = weak market" lore); next day t 0.6; heavy buyers (top
  fifth, yield >~5%) open-minus-shut vs the rest +2.75 bp/day (t 1.2; 2010-17 +5.3, 2018-26 +1.3). Rerun
  the backfill now and then (new companies; the stage only dates quarters with a Finnhub surprise).
- **buyback_news** (SentIQ + Claude, added 2026-11-13) -> `data/buyback_news/`: candidates, classified,
  announcements, classify_summary.json; shown in the Buybacks page's "Recently announced" section. No new
  SEC fetcher (rate limits): SentIQ's `scripts/publish_buyback_candidates_to_hub.py` (job "buyback_news",
  read-only over SentIQ's store) reads each stored 8-K's primary document + exhibits from its raw store
  (`body_text` is truncated) and keeps passages where a share repurchase sits near an authorization /
  program / increase / ASR / tender word (repo agreements dropped). Full rescan (`--rebuild`) took ~100 min
  for 61k 8-Ks since 2019 -> 14.7k candidates (~400/month in 2026); daily runs rescan 3 days.
  `modules/buybacks/news.py` (job "buyback_news_classify") has Claude Haiku 5.5 (thinking off, structured
  output, no server-side fallback for Haiku) classify each candidate once, cached by accession: kind, first
  disclosed here, amounts. Daily: last 30 days, at most 300 (~$0.0003 each, ~1.4 s serial). History via the
  Batch API (`python -m modules.buybacks.news estimate|backfill --yes|collect`; estimate ~$1.74 for 14.7k);
  paid runs need the user's OK. Opus 5.5 would cost ~40x (~$106 backfill, ~$130/yr). Checked 2026-11-13 on
  300 filings: ~92% of flagged announcements were real first disclosures (misses: recaps of ASRs executed
  earlier, "intent" to use remaining capacity); ~7% of verdicts change on a rerun. Announcements dedupe on
  (company, amount) within 120 days. Backfill done 2026-11-13: 14.7k classified, $2.06 in total, 1,909
  announcements. Event study the same day (scratch `bb_event.py` / `bb_open.py`; numbers in
  `modules/buybacks/config.py` ANNOUNCE_TEST, which the page states): last close -> first close after the
  filing +1.30% over SPY (t 7.5); in earnings releases +1.52% vs same-week earnings releases that only recap a
  program (t 4.2); nothing after (next 20 / 60 days ~0); filed outside the session, next open -> close still
  +0.41% (t 4.5, buyback-only 8-Ks) / +0.57% (t 2.6, in earnings releases), recaps ~0, before costs.
  `tradable_at` is the next tradable moment (after-close filings map to the next 9:30); filing times
  (`published_at`): 44% 6:00-9:30 ET, 49% 16:00-18:15, so only the evening half is on the page before the
  open with the 18:15 refresh.
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
- `scripts/register_buyback_task.ps1` registers `\MarketCompass\BuybackPreOpen` (weekdays 9:20 AM, S4U, no
  catch-up): `run_jobs.py --only buyback_news buyback_news_classify` (~20 s), so pre-open 8-Ks are on the
  Buybacks page before 9:30. Checked 2026-11-13: SentIQ polls EDGAR every 2 min (live since 2026-10-13),
  median 4 min from acceptance to first seen; 87% of 6:00-9:30 filings seen before the open. EDGAR
  disseminates nothing after 17:30 ET, so later filings appear at ~6:00 next day (not a SentIQ gap); the one
  real outage was 2026-10-28/29 (~250 filings hours late).
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
- Stock scores, research only (2026-11-13, scratch scripts `style/scores_*.py`, not a job): Piotroski F (9
  signals), Mohanram G (8, medians across all members), gross profit/assets, net share issuance, asset
  growth, 12-1 momentum, 1-yr volatility, a 7-check trend list (above 50/200-day, 50 > 200, RSI 40-70,
  volume ratio > 1, 1m and 3m up) and an equal-weight composite of the five literature ones; S&P members at
  167 month-ends 2012-12..2026-10, same point-in-time rules as style. Rank IC with next-month return, all
  |t| < 2: F -0.005, G +0.001, trend -0.013, gross prof +0.007, buybacks +0.019 (t 1.9; 3m +0.037, t 2.0,
  both halves positive: the only one in line with its paper, and one of nine), asset growth -0.006,
  momentum -0.004, low vol -0.027 (t -1.5, wrong sign), composite -0.009. F among the cheapest third
  (where Piotroski applied it): high minus low -0.76%/month (t -1.1). A first pass showed low-G stocks
  trailing 1%/month (t -10): that was the blank-sector look-ahead above, gone once fixed.
- Pairs trading, research only (2026-11-13, scratch `pairs/pairs_test.py`, not a job): each month-end, Engle-Granger
  on the trailing 252 sessions (log prices, ADF 1 lag, 5% = t < -3.34, 1% = t < -3.90); trade |z| > 2, hold 20
  sessions or until z crosses 0 (max 60); returns per gross dollar; costs 2 bp/side ETFs, 5 bp stocks. ETFs: 96
  sector/style/global/bond/commodity ETFs, 2001-2026, ~3,650 pairs/month: 8.3% pass at 5% (chance 5%), and passing
  one year barely raises the next year's pass rate (12.8% vs 9.7%). Stretched 5% pairs -0.2 bp per 20 days gross
  (t 0.4); 1% pairs +26 bp (t 1.7; since 2014 t 0.5; 37 of 945 trades IVV/SPY); stretched non-cointegrated pairs
  kept diverging (-17 bp, t -1.9). S&P 500 stocks within GICS sub-industry, 2011-2026, ~1,300 pairs/month (today's
  members only, which flatters reversion): 7.1% pass, persistence 8.6% vs 7.9%, 5% pairs -10 bp (t -0.6), 1% pairs
  -32 bp (t -1.0); exit-at-mean variants t < 0.7; negative after costs. Full grid (`pairs/pairs_grid.py`, Gatev-style
  monthly cohorts, committed capital, net of costs): methods EG 5% / 1%, distance (20 smallest SSD), Kalman beta (EG 5%
  selection) x formation 63/126/252 x entry 1-3 sd x execution at the signal close / next open / next close x trading
  period 21/63 sessions = 360 variants each. Stocks: 0 with t > 2, 60 with t < -2, 24% positive. ETFs: 41 with t > 2,
  45 with t < -2; every strong one is Kalman entering at the signal close (k = 1, t up to 4.5), which is mostly
  closing-print noise: per trade 52 bp net at the signal close, 20 bp at the next open, 8 bp at the next close (F 126,
  T 63). Best implementable variant chosen on 2001-13 (Kalman F 126, k 1, next open, T 63): 2014-26 t 1.4, ~3 bp/month
  on committed capital, spread over 2,600 pairs (largest in foreign-country and commodity ETFs, i.e. time-zone
  staleness); at 10 bp/side ~0. Intraday timing untestable (1-minute bars only since 2026-08-27). No page built.
- Possible additions: put/call ratio component, 52-week high/low
  history panel, sector/factor relative-strength analysis page, alerts when a gauge
  crosses a band.

## GitHub
- Public at github.com/AndrewFSee/market-compass. The README is written for visitors: it explains
  cloning the four companion repos next to this one, and embeds `docs/screenshots/*.png`.
- Screenshots were taken from the running hub (real data, dark theme) with headless Chrome via Playwright in a
  throwaway venv, then cropped to the main column. Retake them if a page's layout changes a lot.
- `.env.example` lists the keys; `.env` stays git-ignored. Never commit data/ or keys.
