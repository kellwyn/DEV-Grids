"""
GridReid Signal Lab — Market Character Analysis

Analyses US30 behaviour AT grid levels:
  - How often does price reverse at each level type (MAJOR / MID / MINOR)?
  - Which 30-min slots see the most level touches and reversals?
  - Distribution of winning/losing grid trades by period and session
  - Average bounce size (points) from each level type
  - Big-move candle frequency per slot (signals when grid can fail)
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd

from config import LabConfig
from periods import build_slot_index, SLOT_LABELS


# ── Level helpers ─────────────────────────────────────────────────────────────

def classify_level(price: float, cfg: LabConfig) -> str:
    rounded = int(round(price))
    if rounded % cfg.major_step == 0:
        return "MAJOR"
    if rounded % cfg.mid_step == 0:
        return "MID"
    return "MINOR"


def grid_levels_in_range(low: float, high: float, cfg: LabConfig) -> list[float]:
    """All grid levels that fall within [low, high]."""
    start = math.floor(low  / cfg.grid_step) * cfg.grid_step
    end   = math.ceil(high  / cfg.grid_step) * cfg.grid_step
    levels = []
    lvl = start
    while lvl <= end:
        if low <= lvl <= high:
            levels.append(float(lvl))
        lvl += cfg.grid_step
    return levels


# ── Level touch detection ─────────────────────────────────────────────────────

def detect_touches(df: pd.DataFrame, cfg: LabConfig) -> pd.DataFrame:
    """
    For each bar, detect which grid levels were touched by price action.
    Returns a flat DataFrame with one row per touch event.

    Columns: time, slot, session, level, level_type, touch_from,
             bar_open, bar_high, bar_low, bar_close, bar_range
    """
    records = []
    tol = cfg.tolerance

    for _, row in df.iterrows():
        h, l, c, o = row["h"], row["l"], row["c"], row["o"]
        levels = grid_levels_in_range(l - tol, h + tol, cfg)

        for lvl in levels:
            # Touched from above (price came DOWN to level) → LONG zone
            from_above = l <= lvl + tol and l >= lvl - tol
            # Touched from below (price came UP to level) → SHORT zone
            from_below = h >= lvl - tol and h <= lvl + tol

            if from_above or from_below:
                records.append({
                    "time":       row.get("time", pd.NaT),
                    "slot":       row.get("slot", -1),
                    "session":    row.get("session", ""),
                    "level":      lvl,
                    "level_type": classify_level(lvl, cfg),
                    "touch_from": "above" if from_above else "below",
                    "bar_open":   o,
                    "bar_high":   h,
                    "bar_low":    l,
                    "bar_close":  c,
                    "bar_range":  h - l,
                })

    return pd.DataFrame(records)


# ── Reversal outcome labelling ────────────────────────────────────────────────

def label_reversals(df: pd.DataFrame, touches: pd.DataFrame,
                    cfg: LabConfig, lookahead: int = 20) -> pd.DataFrame:
    """
    For each touch event, look forward N bars to determine if price
    reversed by at least one grid step (success) or continued through (fail).

    Adds columns: outcome ('WIN'|'LOSS'|'UNKNOWN'), bounce_pts
    """
    outcomes = []
    closes = df["c"].values
    highs  = df["h"].values
    lows   = df["l"].values
    n      = len(closes)

    # Build a time→index map for fast lookup
    df_reset = df.reset_index(drop=True)
    time_to_idx = {t: i for i, t in enumerate(df_reset["time"])}

    for _, touch in touches.iterrows():
        t = touch["time"]
        i = time_to_idx.get(t, -1)
        if i < 0:
            outcomes.append({"outcome": "UNKNOWN", "bounce_pts": 0.0})
            continue

        level      = touch["level"]
        touch_from = touch["touch_from"]
        target     = level + cfg.grid_step if touch_from == "above" else level - cfg.grid_step
        fail_lvl   = level - cfg.grid_step if touch_from == "above" else level + cfg.grid_step

        outcome    = "UNKNOWN"
        bounce_pts = 0.0

        for j in range(i + 1, min(i + 1 + lookahead, n)):
            if touch_from == "above":
                if highs[j] >= target:
                    outcome    = "WIN"
                    bounce_pts = target - level
                    break
                if lows[j] <= fail_lvl:
                    outcome    = "LOSS"
                    bounce_pts = level - lows[j]
                    break
            else:
                if lows[j] <= target:
                    outcome    = "WIN"
                    bounce_pts = level - target
                    break
                if highs[j] >= fail_lvl:
                    outcome    = "LOSS"
                    bounce_pts = highs[j] - level
                    break

        outcomes.append({"outcome": outcome, "bounce_pts": bounce_pts})

    out_df = pd.DataFrame(outcomes)
    return pd.concat([touches.reset_index(drop=True), out_df], axis=1)


# ── Slot-level aggregation ────────────────────────────────────────────────────

def slot_level_stats(labelled: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate touch/reversal stats by 30-min slot.

    Returns DataFrame with: slot, slot_label, touches, wins, losses,
    win_rate, avg_bounce_pts, big_slot (top quartile win rate)
    """
    if labelled.empty:
        return pd.DataFrame()

    grp = labelled[labelled["outcome"].isin(["WIN", "LOSS"])].groupby("slot")

    stats = grp.apply(lambda g: pd.Series({
        "touches":        len(g),
        "wins":           (g["outcome"] == "WIN").sum(),
        "losses":         (g["outcome"] == "LOSS").sum(),
        "win_rate":       (g["outcome"] == "WIN").mean() * 100,
        "avg_bounce_pts": g["bounce_pts"].mean(),
    })).reset_index()

    stats["slot_label"] = stats["slot"].apply(
        lambda s: SLOT_LABELS[s] if 0 <= s < 48 else "??"
    )

    q75 = stats["win_rate"].quantile(0.75)
    stats["big_slot"] = stats["win_rate"] >= q75

    return stats.sort_values("slot").reset_index(drop=True)


def level_type_stats(labelled: pd.DataFrame) -> pd.DataFrame:
    """Aggregate win rate and bounce size by level type (MAJOR / MID / MINOR)."""
    if labelled.empty:
        return pd.DataFrame()

    grp = labelled[labelled["outcome"].isin(["WIN", "LOSS"])].groupby("level_type")

    return grp.apply(lambda g: pd.Series({
        "touches":        len(g),
        "wins":           (g["outcome"] == "WIN").sum(),
        "win_rate":       (g["outcome"] == "WIN").mean() * 100,
        "avg_bounce_pts": g["bounce_pts"].mean(),
    })).reset_index()


# ── Big-candle frequency per slot ─────────────────────────────────────────────

def big_candle_by_slot(df: pd.DataFrame, cfg: LabConfig) -> pd.DataFrame:
    """
    For each 30-min slot, compute the frequency of big-move candles.
    Big move: bar body >= cfg.big_move_pct % of bar midpoint price.
    These are candles where the grid strategy is most likely to fail
    (price blows straight through a level without reversing).
    """
    df = df.copy()
    df["body_pct"] = (df["c"] - df["o"]).abs() / ((df["h"] + df["l"]) / 2) * 100
    df["is_big"]   = df["body_pct"] >= cfg.big_move_pct

    grp = df.groupby("slot")
    result = grp.apply(lambda g: pd.Series({
        "total_bars":    len(g),
        "big_candles":   g["is_big"].sum(),
        "big_pct":       g["is_big"].mean() * 100,
        "avg_body_pct":  g["body_pct"].mean(),
    })).reset_index()

    result["slot_label"] = result["slot"].apply(
        lambda s: SLOT_LABELS[s] if 0 <= s < 48 else "??"
    )
    return result.sort_values("slot").reset_index(drop=True)
