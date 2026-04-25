"""
30-min period framework: 48 UTC slots per 24h, ICT session tagging,
NYSE RTH filter, and US30-specific session context.

Slot index: 0 = 00:00 UTC, 28 = 14:00 UTC, 34 = 17:00 UTC, 47 = 23:30 UTC
"""

from __future__ import annotations

import pandas as pd
from config import LabConfig

# Slot labels: '00:00', '00:30', '01:00', ... '23:30'
SLOT_LABELS: list[str] = [
    f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)
]

# Named US30 / NYSE trading periods (UTC)
US30_PERIODS = {
    "Asian Pre":    (22, 0,  23, 30),   # 22:00-23:30 UTC
    "Asian":        (23, 30,  9, 0),    # 23:30-09:00 UTC (overnight)
    "London Open":  ( 7, 0,   9, 0),    # 07:00-09:00 UTC
    "London AM":    ( 9, 0,  12, 0),    # 09:00-12:00 UTC
    "NYSE Pre-mkt": (12, 0,  14, 30),   # 12:00-14:30 UTC (Futures session)
    "NYSE RTH":     (14, 30, 21, 0),    # 14:30-21:00 UTC (Regular Trading Hours)
    "NYSE AM":      (14, 30, 17, 0),    # 14:30-17:00 UTC (opening hour block)
    "NYSE PM":      (17, 0,  21, 0),    # 17:00-21:00 UTC (afternoon block)
    "After-hours":  (21, 0,  22, 0),    # 21:00-22:00 UTC
}

# Key US30 liquidity slots (high activity / level-touch frequency)
HIGH_LIQUIDITY_SLOTS = [14, 15, 28, 29, 30, 31, 32, 33]  # London open + NYSE open + NYSE AM


def tag_slot(ts: pd.Timestamp) -> int:
    """Return slot index 0–47 for a UTC timestamp."""
    return ts.hour * 2 + (ts.minute // 30)


def slot_label(idx: int) -> str:
    """Human-readable label for slot index 0-47."""
    return SLOT_LABELS[idx] if 0 <= idx < 48 else "??"


def _in_window(h: int, m: int, start_h: int, start_m: int, end_h: int, end_m: int) -> bool:
    """True if time (h:m) is within [start, end), handling overnight windows."""
    t     = h * 60 + m
    start = start_h * 60 + start_m
    end   = end_h   * 60 + end_m

    if start > end:   # overnight window (e.g. 22:00-09:00)
        return t >= start or t < end
    return start <= t < end


def tag_session(ts: pd.Timestamp, cfg: LabConfig) -> str:
    """Return active ICT session(s) for a UTC timestamp."""
    h, m = ts.hour, ts.minute
    parts = []

    if _in_window(h, m, cfg.asian_start_h, 0, cfg.asian_end_h, 0):
        parts.append("Asian")
    if _in_window(h, m, cfg.london_start_h, 0, cfg.london_end_h, 0):
        parts.append("London")
    if _in_window(h, m, cfg.ny_start_h, 0, cfg.ny_end_h, 0):
        parts.append("NY")

    return "/".join(parts) if parts else "Off"


def tag_rth(ts: pd.Timestamp, cfg: LabConfig) -> bool:
    """True if the bar falls within NYSE RTH (14:30-21:00 UTC by default)."""
    start_m = cfg.rth_start_h * 60 + cfg.rth_start_m
    end_m   = cfg.rth_end_h   * 60 + cfg.rth_end_m
    bar_m   = ts.hour * 60 + ts.minute
    if start_m <= end_m:
        return start_m <= bar_m < end_m
    return bar_m >= start_m or bar_m < end_m


def tag_us30_period(ts: pd.Timestamp) -> str:
    """Return the named US30 trading period for a UTC timestamp."""
    h, m = ts.hour, ts.minute
    for name, (sh, sm, eh, em) in US30_PERIODS.items():
        if _in_window(h, m, sh, sm, eh, em):
            return name
    return "Off"


def is_high_liquidity_slot(idx: int) -> bool:
    """True if this slot is a known high-liquidity period for US30."""
    return idx in HIGH_LIQUIDITY_SLOTS


def build_slot_index(df: pd.DataFrame, cfg: LabConfig) -> pd.DataFrame:
    """
    Add period columns to a DataFrame with a UTC-aware 'time' column.

    Adds:
      slot        int 0-47
      slot_label  str '14:00'
      session     str 'London/NY'
      is_rth      bool
      period_name str 'NYSE RTH'
      is_high_liq bool
    """
    df = df.copy()
    df["slot"]        = df["time"].apply(tag_slot)
    df["slot_label"]  = df["slot"].apply(slot_label)
    df["session"]     = df["time"].apply(lambda t: tag_session(t, cfg))
    df["is_rth"]      = df["time"].apply(lambda t: tag_rth(t, cfg))
    df["period_name"] = df["time"].apply(tag_us30_period)
    df["is_high_liq"] = df["slot"].apply(is_high_liquidity_slot)
    return df
