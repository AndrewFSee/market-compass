"""Network data pulls: FRED (no API key needed), Yahoo Finance via yfinance,
and index membership from Wikipedia."""
from __future__ import annotations

import io
import json
import os
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (personal market dashboard)"}
# With FRED_API_KEY set (e.g. in .env) the official API is used. The keyless CSV
# endpoint sits behind bot protection that blocks bursts, so it is only a fallback.
FRED_API = "https://api.stlouisfed.org/fred/series/observations"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKI_NDX = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"
# The Nasdaq-100 list uses ICB industries; map them onto the S&P list's GICS sectors
# so the treemap doesn't show two boxes for the same sector.
ICB_TO_GICS = {"Technology": "Information Technology", "Telecommunications": "Communication Services",
               "Basic Materials": "Materials"}


def _get(url: str, retries: int = 3, timeout: int = 30, params: dict | None = None) -> str:
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, params=params)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            last = e
            if isinstance(e, requests.HTTPError) and e.response.status_code == 400:
                break  # bad series id or key: retrying won't help
            time.sleep(1.5 * (attempt + 1))
    raise last


# ----------------------------------------------------------------- FRED
def _fred_key() -> str:
    return os.environ.get("FRED_API_KEY", "").strip()


def fetch_fred(series_id: str) -> pd.Series:
    key = _fred_key()
    if key:
        params = {"series_id": series_id, "api_key": key, "file_type": "json"}
        try:
            text = _get(FRED_API, params=params)
        except requests.RequestException as e:  # error text contains the URL: keep the key out of logs
            raise RuntimeError(str(e).replace(key, "***")) from None
        obs = pd.DataFrame(json.loads(text)["observations"])
        s = pd.to_numeric(obs["value"], errors="coerce")  # missing values come as "."
        s.index = pd.to_datetime(obs["date"])
    else:
        df = pd.read_csv(io.StringIO(_get(FRED_CSV.format(sid=series_id))), na_values=".")
        s = pd.to_numeric(df.iloc[:, 1], errors="coerce")
        s.index = pd.to_datetime(df.iloc[:, 0])
    s.name = series_id
    return s.dropna()


def fetch_fred_many(ids: list[str], log=print) -> tuple[dict[str, pd.Series], list[str]]:
    # the API allows ~120 requests/minute; the keyless endpoint wants one at a time
    workers = 4 if _fred_key() else 1
    if not _fred_key():
        log("  FRED_API_KEY not set: using the keyless CSV endpoint (slower, may be blocked)")
    out, missing = {}, []

    def one(sid):
        try:
            return sid, fetch_fred(sid)
        except Exception as e:  # noqa: BLE001 - keep going if one series fails
            log(f"  FRED {sid}: failed ({e})")
            return sid, None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for sid, s in ex.map(one, ids):
            if s is None or s.empty:
                missing.append(sid)
            else:
                out[sid] = s
    log(f"  FRED: {len(out)} series loaded, {len(missing)} missing")
    return out, missing


# ----------------------------------------------------------------- index members
def _find_table(tables, *required):
    for t in tables:
        cols = [str(c) for c in t.columns]
        if all(any(r.lower() == c.lower() for c in cols) for r in required):
            t.columns = cols
            return t
    return None


def _col(t, name):
    return next(c for c in t.columns if c.lower() == name.lower())


def fetch_constituents(log=print) -> pd.DataFrame:
    sp_tables = pd.read_html(io.StringIO(_get(WIKI_SP500)))
    sp = _find_table(sp_tables, "Symbol", "GICS Sector")
    if sp is None:
        raise RuntimeError("Could not find the S&P 500 table on Wikipedia")
    df = pd.DataFrame({
        "symbol": sp[_col(sp, "Symbol")].astype(str).str.strip(),
        "name": sp[_col(sp, "Security")].astype(str) if "Security" in sp.columns else sp[_col(sp, "Symbol")],
        "sector": sp[_col(sp, "GICS Sector")].astype(str),
    })
    df["sp500"] = True
    df["ndx"] = False
    try:
        nd_tables = pd.read_html(io.StringIO(_get(WIKI_NDX)))
        nd = _find_table(nd_tables, "Ticker")
        if nd is None:
            log("  Nasdaq-100 table not found on Wikipedia; treemap will offer S&P 500 only")
        else:
            nd_sym = nd[_col(nd, "Ticker")].astype(str).str.strip()
            df["ndx"] = df["symbol"].isin(set(nd_sym))
            sector_col = next((c for c in nd.columns if "sector" in c.lower() or "industry" in c.lower()), None)
            name_col = next((c for c in nd.columns if c.lower() in ("company", "security", "name")), None)
            extra = nd[~nd_sym.isin(df["symbol"])]
            if len(extra):
                df = pd.concat([df, pd.DataFrame({
                    "symbol": extra[_col(nd, "Ticker")].astype(str).str.strip(),
                    "name": extra[name_col].astype(str) if name_col else extra[_col(nd, "Ticker")],
                    "sector": extra[sector_col].astype(str).replace(ICB_TO_GICS) if sector_col else "Other",
                    "sp500": False, "ndx": True,
                })], ignore_index=True)
    except Exception as e:  # noqa: BLE001
        log(f"  Nasdaq-100 list unavailable ({e}); treemap will offer S&P 500 only")
    df["yf_symbol"] = df["symbol"].str.replace(".", "-", regex=False)
    log(f"  Constituents: {int(df.sp500.sum())} S&P 500, {int(df.ndx.sum())} Nasdaq-100")
    return df.reset_index(drop=True)


# ----------------------------------------------------------------- prices
def _import_yf():
    import yfinance as yf

    # yfinance still uses pandas APIs deprecated in pandas 3, and on import it adds its own
    # filter that re-enables those warnings - so this has to come after the import
    warnings.filterwarnings("ignore", message="The inplace keyword")
    return yf


def download_closes(tickers: list[str], period: str = "5y", chunk: int = 100, log=print) -> pd.DataFrame:
    yf = _import_yf()

    frames = []
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        try:
            raw = yf.download(batch, period=period, auto_adjust=True, progress=False, threads=True)
        except Exception as e:  # noqa: BLE001
            log(f"  prices batch {i // chunk + 1} failed ({e})")
            continue
        if raw is None or raw.empty:
            continue
        if isinstance(raw.columns, pd.MultiIndex):
            closes = raw["Close"]
        else:
            closes = raw[["Close"]].rename(columns={"Close": batch[0]})
        frames.append(closes)
    if not frames:
        return pd.DataFrame()
    closes = pd.concat(frames, axis=1)
    closes = closes.loc[:, ~closes.columns.duplicated()]
    closes.index = pd.to_datetime(closes.index)
    if closes.index.tz is not None:
        closes.index = closes.index.tz_localize(None)
    closes = closes.sort_index().dropna(how="all").dropna(axis=1, how="all")
    log(f"  prices: {closes.shape[1]}/{len(tickers)} tickers, through {closes.index[-1]:%Y-%m-%d}")
    return closes


def fetch_market_caps(symbols: list[str], log=print) -> pd.Series:
    yf = _import_yf()

    def one(sym):
        try:
            v = yf.Ticker(sym).fast_info.market_cap
            return float(v) if v else None
        except Exception:  # noqa: BLE001
            return None

    with ThreadPoolExecutor(max_workers=12) as ex:
        caps = dict(zip(symbols, ex.map(one, symbols)))
    s = pd.Series(caps, dtype=float, name="market_cap")
    log(f"  market caps: {int(s.notna().sum())}/{len(symbols)}")
    return s
