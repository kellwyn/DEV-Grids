"""
GridReid Signal Lab  v1.00

Analyses US30 grid level behaviour: reversal win rates by level type
and 30-min slot, big-candle (momentum) frequency, and macro correlations.

Usage:
  python main.py US30 3M        # US30, 3-month lookback
  python main.py US30Cash 1Y    # alternative symbol, 1-year
  python main.py US30 1M --calendar   # also print economic calendar

Requires MT5 connection for OHLCV data.
Optional: yfinance for macro correlations (pip install yfinance).
"""

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv()

from config import LabConfig, DURATION_LABELS
from fetcher import fetch_ohlcv
from periods import build_slot_index
from market_char import detect_touches, label_reversals, slot_level_stats, level_type_stats, big_candle_by_slot
from correlations import fetch_corr_data, correlation_summary, vix_regime, dxy_bias
from report import print_full_report
from economic_calendar import print_calendar


def _connect():
    import os
    kwargs = {}
    path = os.getenv("MT5_PATH")
    login, password, server = (
        os.getenv("MT5_LOGIN"),
        os.getenv("MT5_PASSWORD"),
        os.getenv("MT5_SERVER"),
    )
    if path:
        kwargs["path"] = path
    if login and password and server:
        kwargs.update(login=int(login), password=password, server=server)

    ok = mt5.initialize(**kwargs) if kwargs else mt5.initialize()
    if not ok:
        raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")


def main():
    parser = argparse.ArgumentParser(description="GridReid Signal Lab v1.00")
    parser.add_argument("symbol",   nargs="?", default="US30",
                        help="MT5 symbol (e.g. US30, US30.f, US30Cash)")
    parser.add_argument("duration", nargs="?", default="3M",
                        choices=DURATION_LABELS,
                        help=f"Lookback duration: {DURATION_LABELS}")
    parser.add_argument("--calendar", action="store_true",
                        help="Print economic calendar reference")
    parser.add_argument("--no-corr", action="store_true",
                        help="Skip macro correlation fetch (faster, no yfinance needed)")
    args = parser.parse_args()

    if args.calendar:
        print_calendar()
        if not args.symbol:
            return

    cfg = LabConfig(symbol=args.symbol)

    print(f"\n  Connecting to MT5...")
    _connect()
    print(f"  Connected. Fetching {cfg.symbol} [{cfg.analysis_tf}] data ({args.duration})...")

    # ── Fetch OHLCV ───────────────────────────────────────────────────────────
    try:
        df = fetch_ohlcv(cfg, args.duration)
    except RuntimeError as e:
        print(f"  ERROR: {e}")
        mt5.shutdown()
        sys.exit(1)

    print(f"  Fetched {len(df):,} bars.")

    # ── Tag periods / sessions ────────────────────────────────────────────────
    df = build_slot_index(df, cfg)

    # ── Detect level touches ──────────────────────────────────────────────────
    print("  Detecting grid level touches...")
    touches = detect_touches(df, cfg)
    print(f"  Found {len(touches):,} level touch events.")

    # ── Label reversal outcomes ───────────────────────────────────────────────
    print("  Labelling reversal outcomes...")
    labelled = label_reversals(df, touches, cfg, lookahead=cfg.tp_lookahead_bars)

    # ── Aggregate stats ───────────────────────────────────────────────────────
    level_stats  = level_type_stats(labelled)
    slot_stats   = slot_level_stats(labelled)
    big_candle   = big_candle_by_slot(df, cfg)

    # ── Macro correlations ────────────────────────────────────────────────────
    corr_summary = {}
    vix_data     = {"vix": None, "regime": "unavailable", "grid_impact": "N/A"}
    dxy_data     = {"dxy": None, "trend": "unavailable", "us30_implication": "N/A"}

    if not args.no_corr:
        print("  Fetching macro correlations (yfinance)...")
        days = {"1W": 60, "1M": 90, "3M": 180, "6M": 365, "1Y": 730, "2Y": 900}
        corr_df = fetch_corr_data(cfg.corr_assets, days=days.get(args.duration, 365))
        if not corr_df.empty:
            import pandas as pd
            corr_summary = correlation_summary(corr_df, base="^DJI")
            vix_data     = vix_regime(corr_df)
            dxy_data     = dxy_bias(corr_df)
        else:
            print("  [No correlation data — yfinance unavailable or no internet]")
            corr_summary = {}
            import pandas as pd
            corr_summary = pd.DataFrame()

    import pandas as pd

    # ── Render report ─────────────────────────────────────────────────────────
    print_full_report(
        cfg          = cfg,
        duration_label = args.duration,
        total_bars   = len(df),
        level_stats  = level_stats,
        slot_stats   = slot_stats,
        big_candle   = big_candle,
        corr_summary = corr_summary if isinstance(corr_summary, pd.DataFrame) else pd.DataFrame(),
        vix_data     = vix_data,
        dxy_data     = dxy_data,
    )

    mt5.shutdown()


if __name__ == "__main__":
    main()
