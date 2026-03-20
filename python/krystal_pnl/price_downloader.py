#!/usr/bin/env python3
"""
price_downloader.py
~~~~~~~~~~~~~~~~~~~
Incrementally build / refresh bitget_open_15m.csv, downloading only the
15‑minute candles that are still missing.

Files used
----------
valid_bitget_tickers.csv   ← spot USDT markets (one column "ticker")
price_coverage.json        ← {"AAVEUSDT":[["2025-01-01T00:00:00",
                                           "2025-04-01T23:45:00"], …], …}
bitget_open_15m.csv        ← the price matrix (timestamp index, columns=tickers)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Tuple, Optional, Set

import pandas as pd
from tqdm import tqdm

from datafeed.bitgetfeed import BitgetMarket
from .scan_tickers import build_ticker_timewindows


from pathlib import Path
import dotenv


# ── CONFIG ──────────────────────────────────────────────────────────────────
MODULE_DIR   = Path(__file__).resolve().parent                # …/python/krystal_pnl
ROOT_DIR     = MODULE_DIR.parents[1]                          # LP‑hedging‑strategy
INT_DATA_DIR = MODULE_DIR / "pnl_data"
INT_DATA_DIR.mkdir(exist_ok=True)

dotenv.load_dotenv(ROOT_DIR / ".env")                         # load project env

VALID_TICKERS_CSV = INT_DATA_DIR / "valid_bitget_tickers.csv"
OUTFILE           = INT_DATA_DIR /"bitget_open_15m.csv"
COVERAGE_FILE     = INT_DATA_DIR /"price_coverage.json"
TIMEFRAME         = "15m"
BAR_INTERVAL      = pd.Timedelta(minutes=15)       # must match TIMEFRAME
# ────────────────────────────────────────────────────────────────────────────


# ╭────────────────────────── Helpers ───────────────────────────╮
def load_valid_tickers(csv_path: str = VALID_TICKERS_CSV) -> Set[str]:
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(
            f"{csv_path} not found – run build_valid_bitget_tickers.py first."
        )
    return set(pd.read_csv(csv_path)["ticker"].str.upper())


def load_coverage(path: str = COVERAGE_FILE) -> dict[str, list[list[str]]]:
    """Return {ticker: [[start_iso, end_iso], …]} or {}."""
    if Path(path).is_file():
        with open(path, "r") as f:
            return json.load(f)
    return {}


def save_coverage(coverage: dict[str, list[list[str]]], path: str = COVERAGE_FILE):
    with open(path, "w") as f:
        json.dump(coverage, f, indent=2, sort_keys=True)


def merge_intervals(
    intervals: list[Tuple[pd.Timestamp, pd.Timestamp]]
) -> list[Tuple[pd.Timestamp, pd.Timestamp]]:
    """Return disjoint, sorted, merged closed intervals."""
    if not intervals:
        return []
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    for s, e in intervals[1:]:
        last_s, last_e = merged[-1]
        if s <= last_e + BAR_INTERVAL:             # contiguous / overlapping
            merged[-1] = (last_s, max(last_e, e))
        else:
            merged.append((s, e))
    return merged


def missing_subranges(
    wanted: Tuple[pd.Timestamp, pd.Timestamp],
    have: list[Tuple[pd.Timestamp, pd.Timestamp]],
) -> list[Tuple[pd.Timestamp, pd.Timestamp]]:
    """Return the portions of *wanted* not covered by *have*."""
    s, e = wanted
    gaps: list[Tuple[pd.Timestamp, pd.Timestamp]] = []
    cur = s
    for h_s, h_e in have:
        if h_e < cur:
            continue
        if h_s > e:
            break
        if h_s > cur:
            gaps.append((cur, min(h_s - BAR_INTERVAL, e)))
        cur = max(cur, h_e + BAR_INTERVAL)
        if cur > e:
            break
    if cur <= e:
        gaps.append((cur, e))
    return gaps


def collapse_duplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    """If the DataFrame has duplicated column names, keep element‑wise max."""
    return df.T.groupby(level=0).max().T


# ╭────────────────────── Downloader core ──────────────────────╮
def fetch_bitget_open_prices(
    requests: List[Tuple[str, Tuple[pd.Timestamp, pd.Timestamp]]],
    fill_gaps: Optional[str] = None,   # None ⇒ keep NaNs
) -> pd.DataFrame:
    market = BitgetMarket()

    # Load price matrix (if any) & current coverage
    if Path(OUTFILE).is_file():
        price_matrix = (
            pd.read_csv(OUTFILE, parse_dates=["timestamp"])
            .set_index("timestamp")
        )
    else:
        price_matrix = pd.DataFrame()

    coverage = load_coverage()

    series_to_append = []

    for sym, (start_dt, end_dt) in tqdm(requests, desc="Tickers"):
        start_ts = pd.Timestamp(start_dt)
        end_ts   = pd.Timestamp(end_dt)

        # What do we already have?
        covered_raw = coverage.get(sym, [])
        covered = [(pd.Timestamp(s), pd.Timestamp(e)) for s, e in covered_raw]
        gaps = missing_subranges((start_ts, end_ts), covered)
        if not gaps:
            print(f"[SKIP] {sym}: already covered")
            continue

        # Fetch each gap
        fetched_parts = []
        for g_s, g_e in gaps:
            bars, _ = market.read_bars(
                symbol=sym,
                timeframe=TIMEFRAME,
                start_time=int(g_s.timestamp()),
                end_time=int(g_e.timestamp()),
            )
            if bars is None or bars.empty:
                print(f"[WARN] {sym}: no data for {g_s}–{g_e}")
                continue

            idx = pd.to_datetime(bars.index, unit="s", utc=True).tz_localize(None)
            fetched_parts.append(bars["open"].rename(sym).set_axis(idx))

        if not fetched_parts:
            continue

        new_ser = pd.concat(fetched_parts).sort_index()
        series_to_append.append(new_ser)

        # Update coverage in memory
        covered.extend(gaps)
        coverage[sym] = [
            [s.isoformat(), e.isoformat()] for s, e in merge_intervals(covered)
        ]

    # Nothing new – return what we already had
    if not series_to_append:
        print("No new data fetched.")
        return price_matrix

    # Build DataFrame of the newly fetched pieces
    new_df = pd.concat(series_to_append, axis=1)

    # Merge with existing
    price_matrix = (
        pd.concat([price_matrix, new_df], axis=1, join="outer")
          .sort_index()
    )
    price_matrix = collapse_duplicate_columns(price_matrix)

    if fill_gaps:
        price_matrix = price_matrix.fillna(method=fill_gaps)

    price_matrix.to_csv(OUTFILE, index_label="timestamp")
    save_coverage(coverage)

    print(f"Saved updated prices → {os.path.abspath(OUTFILE)}")
    return price_matrix


# ───────────────────────── Main flow ─────────────────────────
if __name__ == "__main__":
    # 1) Build desired windows from position files
    raw_windows = build_ticker_timewindows(
        closed_csv=INT_DATA_DIR / "krystal_closed_positions.csv",
        open_csv=INT_DATA_DIR / "krystal_open_positions.csv",
    )

    # 2) Filter by valid spot tickers
    valid = load_valid_tickers()
    windows = [w for w in raw_windows if w[0].upper() in valid]

    print("Symbols and intervals to download:")
    for sym, (s, e) in windows:
        print(f"  {sym}: {s} – {e}")

    # 3) Fetch whatever is still missing
    fetch_bitget_open_prices(windows, fill_gaps=None)   
