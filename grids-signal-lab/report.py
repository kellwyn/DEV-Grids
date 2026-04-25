"""
GridReid Signal Lab — Console Report Renderer

Formats and prints all analysis tables to the terminal.
"""

from __future__ import annotations

import pandas as pd
from datetime import datetime, timezone

from config import LabConfig
from periods import SLOT_LABELS


SEP  = "─" * 72
SEP2 = "═" * 72


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pct_bar(pct: float, width: int = 20) -> str:
    """Render a simple ASCII percentage bar."""
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _fmt(val, fmt=".1f", default="N/A") -> str:
    try:
        return format(float(val), fmt)
    except (ValueError, TypeError):
        return default


# ── Header ────────────────────────────────────────────────────────────────────

def print_header(cfg: LabConfig, duration_label: str, total_bars: int):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{SEP2}")
    print(f"  GRID REID SIGNAL LAB  |  {cfg.symbol}  [{cfg.analysis_tf}]")
    print(f"  Duration: {duration_label}  |  Bars: {total_bars:,}  |  Run: {now}")
    print(f"  Grid step: {cfg.grid_step} pts  |  Major: {cfg.major_step} pts  |  Mid: {cfg.mid_step} pts")
    print(SEP2)


# ── Level type win rates ──────────────────────────────────────────────────────

def print_level_type_stats(df: pd.DataFrame):
    """Print win rate by level type (MAJOR / MID / MINOR)."""
    if df.empty:
        print("  [Level type stats: no data]")
        return

    print(f"\n  REVERSAL WIN RATE BY LEVEL TYPE")
    print(SEP)
    print(f"  {'Type':<8}  {'Touches':>7}  {'Wins':>6}  {'Win%':>7}  {'Avg Bounce':>10}  Bar")
    print(SEP)

    for _, row in df.iterrows():
        bar = _pct_bar(float(row.get("win_rate", 0)))
        print(f"  {row['level_type']:<8}  {int(row.get('touches',0)):>7}  "
              f"{int(row.get('wins',0)):>6}  {_fmt(row.get('win_rate')):>6}%  "
              f"{_fmt(row.get('avg_bounce_pts',0), '.1f'):>9}pts  {bar}")
    print(SEP)


# ── Slot win rate table ───────────────────────────────────────────────────────

def print_slot_stats(df: pd.DataFrame, top_n: int = 15):
    """Print top N slots by win rate."""
    if df.empty:
        print("  [Slot stats: no data]")
        return

    top = df.nlargest(top_n, "win_rate")

    print(f"\n  TOP {top_n} SLOTS BY REVERSAL WIN RATE")
    print(SEP)
    print(f"  {'Slot':>5}  {'Label':>6}  {'Touches':>7}  {'Wins':>5}  {'Win%':>6}  {'Avg Bounce':>10}  Bar")
    print(SEP)

    for _, row in top.iterrows():
        star  = " ★" if row.get("big_slot") else ""
        bar   = _pct_bar(float(row.get("win_rate", 0)))
        label = SLOT_LABELS[int(row["slot"])] if 0 <= int(row["slot"]) < 48 else "??"
        print(f"  {int(row['slot']):>5}  {label:>6}  {int(row.get('touches',0)):>7}  "
              f"{int(row.get('wins',0)):>5}  {_fmt(row.get('win_rate')):>5}%{star}  "
              f"{_fmt(row.get('avg_bounce_pts',0), '.1f'):>9}pts  {bar}")

    print(SEP)
    print("  ★ = top-quartile slots")


# ── Big candle frequency ──────────────────────────────────────────────────────

def print_big_candle_slots(df: pd.DataFrame, threshold: float = 15.0):
    """Print slots where big-candle frequency exceeds threshold %."""
    if df.empty:
        print("  [Big candle data: no data]")
        return

    danger = df[df["big_pct"] >= threshold].sort_values("big_pct", ascending=False)

    print(f"\n  HIGH MOMENTUM SLOTS  (big candle freq >= {threshold:.0f}%)  — grid failure risk")
    print(SEP)
    print(f"  {'Slot':>5}  {'Label':>6}  {'Total Bars':>10}  {'Big Candles':>12}  {'Big%':>7}  {'Avg Body%':>10}")
    print(SEP)

    for _, row in danger.iterrows():
        label = SLOT_LABELS[int(row["slot"])] if 0 <= int(row["slot"]) < 48 else "??"
        print(f"  {int(row['slot']):>5}  {label:>6}  {int(row.get('total_bars',0)):>10}  "
              f"{int(row.get('big_candles',0)):>12}  {_fmt(row.get('big_pct')):>6}%  "
              f"{_fmt(row.get('avg_body_pct'), '.3f'):>9}%")

    print(SEP)


# ── Correlation table ─────────────────────────────────────────────────────────

def print_correlations(df: pd.DataFrame):
    """Print macro correlation summary table."""
    if df.empty:
        print("  [Correlations: yfinance not available or no data]")
        return

    print(f"\n  US30 MACRO CORRELATIONS  (vs {df.get('asset', pd.Series()).iloc[0] if not df.empty else 'N/A'})")
    print(SEP)
    print(f"  {'Asset':<12}  {'Current':>8}  {'30d':>8}  {'90d':>8}  Interpretation")
    print(SEP)

    for _, row in df.iterrows():
        print(f"  {row.get('asset',''):<12}  "
              f"{str(row.get('current_corr','N/A')):>8}  "
              f"{str(row.get('30d_corr','N/A')):>8}  "
              f"{str(row.get('90d_corr','N/A')):>8}  "
              f"{str(row.get('interpretation',''))[:50]}")

    print(SEP)


# ── VIX / DXY macro context ───────────────────────────────────────────────────

def print_macro_context(vix_data: dict, dxy_data: dict):
    print(f"\n  MACRO CONTEXT FOR GRID TRADING")
    print(SEP)

    if vix_data.get("vix") is not None:
        print(f"  VIX            : {vix_data['vix']:.2f}  (30d avg: {vix_data.get('vix_30d_avg', 0):.2f})")
        print(f"  Regime         : {vix_data.get('regime')}")
        print(f"  Grid impact    : {vix_data.get('grid_impact')}")
    else:
        print("  VIX            : unavailable")

    print()

    if dxy_data.get("dxy") is not None:
        print(f"  DXY            : {dxy_data['dxy']:.2f}  (20d MA: {dxy_data.get('ma20', 0):.2f})")
        print(f"  Trend          : {dxy_data.get('trend')}")
        print(f"  US30 impact    : {dxy_data.get('us30_implication')}")
    else:
        print("  DXY            : unavailable")

    print(SEP)


# ── Full report orchestrator ──────────────────────────────────────────────────

def print_full_report(
    cfg: LabConfig,
    duration_label: str,
    total_bars: int,
    level_stats: pd.DataFrame,
    slot_stats: pd.DataFrame,
    big_candle: pd.DataFrame,
    corr_summary: pd.DataFrame,
    vix_data: dict,
    dxy_data: dict,
):
    print_header(cfg, duration_label, total_bars)
    print_level_type_stats(level_stats)
    print_slot_stats(slot_stats)
    print_big_candle_slots(big_candle)
    print_macro_context(vix_data, dxy_data)
    print_correlations(corr_summary)
    print(f"\n{SEP2}\n")
