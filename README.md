# Dashboard Hub

One Streamlit app that brings all your project dashboards together. The first
module, **Market Environment**, covers market regime and breadth:

- **Four gauges:** Fear/Greed, Liquidity Regime, Technical Regime, Economic Regime. Each one has a components table and a history chart.
- **Breadth (S&P 500 members):** advance/decline with the cumulative A/D line, % of stocks above their 20/50/200-day averages, and new 52-week highs and lows.
- **Style/size grid:** large/mid/small × value/core/growth.
- **Sector & factor tiles:** the 11 sectors plus SPY, and 22 factor ETFs.
- **Market map:** S&P 500 or Nasdaq 100 treemap, sized by market cap.

All data comes from free sources: FRED (no API key needed), Yahoo Finance via `yfinance`, and Wikipedia for index membership.

## Quick start

```bash
cd market_hub
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python run_jobs.py --demo          # synthetic data, to see it working right away
streamlit run app.py

python run_jobs.py                 # real data: about 2-4 minutes the first time
```

The first real run pulls 5 years of prices for roughly 520 stocks and 45 ETFs, about
35 FRED series, and market caps. Later runs reuse cached market caps for a week.

## How it's organized

```
app.py                 Hub entry point (sidebar navigation)
registry.py            The one place to register pages, links and data jobs
run_jobs.py            Refreshes data for every registered job
core/store.py          Shared data folder: save_frame / load_frame / save_json
core/ui.py             Reusable pieces: gauge, donut, performance tiles
views/home.py          Hub home page: data freshness for every project
modules/market/
    config.py          Tickers, FRED series, indicator recipes, gauge bands  <- tweak here
    sources.py         Network pulls (FRED, Yahoo, Wikipedia)
    indicators.py      Pure calculations, no network
    job.py             Fetch -> compute -> save
    page.py            Streamlit page (reads saved data only)
    demo.py            Synthetic inputs for testing
tests/test_smoke.py    End-to-end test on demo data:  python -m pytest -q
```

**Jobs compute, pages display.** Data jobs save their results into `data/`, and pages
only read from there. The dashboard loads instantly, a failed refresh leaves
yesterday's numbers in place, and any page can reuse another project's data.

## Adding your existing projects

You have three options, from least to most effort:

1. **Link it.** Add `{"title": ..., "url": "http://localhost:8502"}` to `LINKS` in
   `registry.py`. It stays a separate app and gets a sidebar link.
2. **Mount it as a page.** Add its script to `PAGES` with an absolute path:
   ```python
   "Credit": [{"path": "/path/to/credit_spreads/app.py", "title": "Credit Spreads",
               "icon": ":material/trending_up:"}],
   ```
   Remove `st.set_page_config(...)` from that script, since the hub sets it once. The
   project's folder is added to the import path, so its own imports still work.
3. **Split it into job + page.** Move the data work into a `run(demo=False, log=print)`
   function that ends with `store.save_frame("credit", "spreads", df)`, register it in
   `JOBS`, and have the page read with `store.load_frame`. This is the best long-term
   setup: one scheduled refresh for everything, and other pages can use the data.

### Using your credit spread project in the gauges

The Liquidity and Fear/Greed gauges use FRED's ICE BofA high-yield and
investment-grade spreads by default. Once your credit project publishes a table, for
example `data/credit/spreads.parquet` with a date index and columns `hy_oas` and
`ig_oas` in percentage points, point the market module at it in `modules/market/config.py`:

```python
CREDIT_OVERRIDE = {"module": "credit", "name": "spreads", "hy": "hy_oas", "ig": "ig_oas"}
```

If all your projects share one data folder somewhere else, set the `HUB_DATA_DIR`
environment variable for both the hub and the projects.

## Scheduling the refresh

Run `run_jobs.py` once each weekday evening, after the close (FRED and Yahoo are updated by then).

- **macOS / Linux (cron):** `crontab -e`, then
  `15 18 * * 1-5 cd /path/to/market_hub && .venv/bin/python run_jobs.py`
- **Windows (Task Scheduler):** create a daily task on weekdays at 6:15 PM.
  Program: `C:\path\to\market_hub\.venv\Scripts\python.exe`, arguments: `run_jobs.py`,
  start in: `C:\path\to\market_hub`.

Logs go to `data/logs/jobs.log`. The hub's Home page shows how fresh each project's data is.

## How the gauges work

All recipes live in `modules/market/config.py` and `indicators.py`.

| Gauge | Scale | Method |
|---|---|---|
| Fear / Greed | 0 to 100 | Six components, each ranked against its trailing 2 years: S&P vs its 125-day average, net new 52-week highs, % of stocks above their 50-day average, VIX vs its 50-day average (inverted), stocks minus bonds over 20 days, and the HY minus IG spread (inverted). |
| Technical | 0 to 100 | S&P 500 RSI(14), stochastic(14), MACD histogram, and distance from the 50- and 200-day averages. |
| Liquidity | −100 to +100 | Eight factors, each z-scored against its trailing 3 years and signed so that higher means looser: HY and IG spreads, the 3-month change in the 2-year yield, the 10-year real yield, the Fed's net liquidity (balance sheet minus TGA minus reverse repo), bank reserves, the broad dollar, and NFCI. |
| Economic | −100 to +100 | Sixteen monthly leading indicators. Each indicator's 6-month change is z-scored over 20 years and weighted by its historical correlation with real GDP growth 6 months later. The gauge shows the latest month with at least 75% of indicators reported; later months are marked provisional. |

Breadth uses S&P 500 members as a proxy for the NYSE, since free NYSE-wide
advance/decline data is hard to find. There is no put/call ratio component for the same
reason. If you find a source, it can be added as one more entry in `fear_greed()`.

## Calibrating against SimpleVisor during the trial

Your numbers won't match theirs exactly, and they don't need to. Log both side by side
for a couple of weeks. If a gauge consistently runs hotter or colder than theirs, adjust
its lookback windows, components, or band cut-offs in `config.py`.
