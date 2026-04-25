"""
MT5 OHLCV data fetcher for the GridReid signal lab.
All timestamps returned in UTC.
"""

from __future__ import annotations

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timezone, timedelta

from config import LabConfig, DURATIONS


_TF_MAP = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}


def fetch_ohlcv(cfg: LabConfig, duration_label: str = "3M") -> pd.DataFrame:
    """
    Fetch OHLCV bars for cfg.symbol at cfg.analysis_tf for the specified duration.

    duration_label: one of DURATIONS keys ("1W", "1M", "3M", "6M", "1Y", "2Y")
    Returns DataFrame with UTC timestamps and columns: time, o, h, l, c, v, tick_volume
    """
    days = DURATIONS.get(duration_label, 90)
    tf   = _TF_MAP.get(cfg.analysis_tf.upper())
    if tf is None:
        raise ValueError(f"Unknown timeframe: {cfg.analysis_tf}")

    now      = datetime.now(timezone.utc)
    from_dt  = now - timedelta(days=days)

    rates = mt5.copy_rates_range(cfg.symbol, tf, from_dt, now)

    if rates is None or len(rates) == 0:
        err = mt5.last_error()
        raise RuntimeError(
            f"No data for {cfg.symbol} [{cfg.analysis_tf}] over {duration_label}: {err}"
        )

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.rename(columns={
        "open":        "o",
        "high":        "h",
        "low":         "l",
        "close":       "c",
        "tick_volume": "v",
    }, inplace=True)

    # Drop the forming (most-recent) bar
    df = df.iloc[:-1].reset_index(drop=True)

    return df


def fetch_daily(cfg: LabConfig, duration_label: str = "3M") -> pd.DataFrame:
    """Fetch daily OHLCV bars (D1 timeframe)."""
    days    = DURATIONS.get(duration_label, 90)
    now     = datetime.now(timezone.utc)
    from_dt = now - timedelta(days=days)

    rates = mt5.copy_rates_range(cfg.symbol, mt5.TIMEFRAME_D1, from_dt, now)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No D1 data for {cfg.symbol}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.rename(columns={"open": "o", "high": "h", "low": "l",
                        "close": "c", "tick_volume": "v"}, inplace=True)
    return df.iloc[:-1].reset_index(drop=True)
