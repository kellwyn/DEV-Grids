"""
GridReid — Psychological Level Grid Strategy  v1.00  (Python bot)

Strategy rules mirrored from GridReid_v1.00.mq5:
  Rule 1  — Build grid levels at every cfg.grid_step points
             Major: every major_step (1000). Mid: every mid_step (250). Minor: every grid_step (50).
  Rule 2  — Daily bias set manually: LONG / SHORT / BOTH / NONE
             LONG  = buy when price comes DOWN to a level (expect bounce up)
             SHORT = sell when price goes UP to a level   (expect drop down)
  Rule 3  — TP = next grid level in bias direction (one step = cfg.tp_pips)
             SL = optional hard stop in pips (0 = rely on loss limit only)
  Rule 4  — Add trades at each subsequent level if price moves against bias
             (pyramid adding) capped at cfg.max_trades
  Rule 5  — Emergency exit if total floating loss exceeds loss limits

NOTE: Python MT5 arrays — index 0 = oldest, -1 = most recent.
      Use copy_rates_from_pos(symbol, tf, 1, n) to skip forming bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List
import math

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

from .signals import GridSetup


# ── Timeframe map ─────────────────────────────────────────────────────────────

_TF_MAP = {
    "M1":  mt5.TIMEFRAME_M1,  "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,  "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}

# ICT session windows (UTC hours) — [start, end) with midnight-wrap support
_SESSIONS = {
    "Asian":  (22, 9),
    "London": (7, 16),
    "NY":     (12, 21),
}


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class GridConfig:
    # Instrument
    symbol:    str  = "US30"
    timeframe: str  = "M5"     # chart timeframe for bar detection

    # Grid geometry
    grid_step:  int  = 50      # points between trading levels
    major_step: int  = 1000    # points between major levels
    mid_step:   int  = 250     # points between mid levels
    tolerance:  float = 15.0   # points tolerance for "at a level"

    # Direction bias — set via REPL
    bias:          str  = "LONG"   # LONG | SHORT | BOTH | NONE
    expected_move: int  = 350      # expected daily range in points (context only)

    # Trade management
    max_trades: int   = 5      # max simultaneous grid trades
    tp_pips:    float = 50.0   # TP distance in points (default = 1 grid step)
    sl_pips:    float = 0.0    # SL distance in points (0 = no hard SL)
    min_rr:     float = 0.0    # minimum R:R ratio (0 = disabled)

    # Risk
    risk_pct:    float = 1.0   # risk % per trade
    max_lots:    float = 5.0   # max lot cap
    fixed_lots:  float = 0.0   # fixed lots (0 = risk-based)

    # Loss limits (all optional — set to 0 to disable)
    loss_limit_pct: float = 5.0   # % of balance max floating loss
    loss_limit_usd: float = 0.0   # $ max floating loss
    exit_level:     float = 0.0   # physical price point of no return

    # Period filter
    use_period_filter: bool       = False
    allowed_periods:   List[int]  = field(default_factory=list)  # slot indices 0-47

    # ICT session filter
    use_session_filter: bool = False
    trade_asian:        bool = False
    trade_london:       bool = True
    trade_ny:           bool = True

    # Trade settings
    magic:    int = 20260426
    slippage: int = 20


# ── Grid level helpers ────────────────────────────────────────────────────────

def get_level_type(level: float, cfg: GridConfig) -> str:
    """Classify a price level as MAJOR, MID, or MINOR."""
    rounded = int(round(level))
    if rounded % cfg.major_step == 0:
        return "MAJOR"
    if rounded % cfg.mid_step == 0:
        return "MID"
    return "MINOR"


def get_grid_levels(center: float, cfg: GridConfig, n_above: int = 15, n_below: int = 15) -> List[float]:
    """Return sorted list of grid levels around center price."""
    base = round(center / cfg.grid_step) * cfg.grid_step
    return [base + i * cfg.grid_step for i in range(-n_below, n_above + 1)]


def nearest_levels(price: float, cfg: GridConfig) -> dict:
    """Return the nearest level above and below current price."""
    step = cfg.grid_step
    above = math.ceil(price / step) * step
    below = math.floor(price / step) * step
    if above == below:
        above += step
    return {
        "above": above,
        "below": below,
        "dist_above": above - price,
        "dist_below": price - below,
        "type_above": get_level_type(above, cfg),
        "type_below": get_level_type(below, cfg),
    }


# ── Session helpers ───────────────────────────────────────────────────────────

def _in_window(hour: int, start: int, end: int) -> bool:
    if start > end:
        return hour >= start or hour < end
    return start <= hour < end


def current_session(cfg: GridConfig) -> str:
    """Return active ICT session name(s) for the current UTC time."""
    h = datetime.now(timezone.utc).hour
    parts = []
    if cfg.trade_asian  and _in_window(h, 22, 9):  parts.append("Asian")
    if cfg.trade_london and _in_window(h, 7, 16):  parts.append("London")
    if cfg.trade_ny     and _in_window(h, 12, 21): parts.append("NY")
    return " / ".join(parts) if parts else "Off-session"


def current_slot() -> int:
    """Return 30-min UTC slot index 0-47."""
    now = datetime.now(timezone.utc)
    return now.hour * 2 + (now.minute // 30)


def is_allowed_time(cfg: GridConfig) -> bool:
    """True if current time passes all active time filters."""
    if not cfg.use_period_filter and not cfg.use_session_filter:
        return True

    slot = current_slot()
    h    = datetime.now(timezone.utc).hour

    if cfg.use_period_filter and cfg.allowed_periods:
        if slot not in cfg.allowed_periods:
            return False

    if cfg.use_session_filter:
        in_asian  = cfg.trade_asian  and _in_window(h, 22, 9)
        in_london = cfg.trade_london and _in_window(h, 7, 16)
        in_ny     = cfg.trade_ny     and _in_window(h, 12, 21)
        if not (in_asian or in_london or in_ny):
            return False

    return True


# ── Data fetch ────────────────────────────────────────────────────────────────

def _fetch(symbol: str, tf_str: str, count: int = 3) -> Optional[pd.DataFrame]:
    """Fetch the last N completed bars (skips forming bar via pos=1)."""
    tf = _TF_MAP.get(tf_str.upper())
    if tf is None:
        return None
    rates = mt5.copy_rates_from_pos(symbol, tf, 1, count)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c"}, inplace=True)
    return df


# ── Level touch detection ─────────────────────────────────────────────────────

def detect_level_touches(df: pd.DataFrame, cfg: GridConfig) -> List[dict]:
    """
    Scan the most recent completed bar for grid-level touches.
    Returns list of {level, level_type, touch_from} dicts.

    touch_from='above' — bar LOW touched the level (price came DOWN to it) → LONG candidate
    touch_from='below' — bar HIGH touched the level (price came UP to it)  → SHORT candidate
    Directional check: prior close must be on the approach side.
    """
    if len(df) < 2:
        return []

    bar_high  = df["h"].iloc[-1]
    bar_low   = df["l"].iloc[-1]
    prev_close = df["c"].iloc[-2]
    tol = cfg.tolerance

    touches = []
    start_level = math.floor(bar_low  / cfg.grid_step) * cfg.grid_step - cfg.grid_step
    end_level   = math.ceil(bar_high  / cfg.grid_step) * cfg.grid_step + cfg.grid_step

    lvl = start_level
    while lvl <= end_level:
        hit_from_above = (bar_low  <= lvl + tol and bar_low  >= lvl - tol and prev_close >= lvl)
        hit_from_below = (bar_high >= lvl - tol and bar_high <= lvl + tol and prev_close <= lvl)

        if hit_from_above or hit_from_below:
            touches.append({
                "level":      lvl,
                "level_type": get_level_type(lvl, cfg),
                "touch_from": "above" if hit_from_above else "below",
            })

        lvl += cfg.grid_step

    return touches


# ── Position queries (used by strategy and loss-limit monitor) ────────────────

def get_open_levels(cfg: GridConfig) -> List[float]:
    """Return list of open-position entry prices for this EA's magic/symbol."""
    levels = []
    for i in range(mt5.positions_total()):
        pos = mt5.positions_get()
        if pos is None:
            break
        for p in pos:
            if p.magic == cfg.magic and p.symbol == cfg.symbol:
                levels.append(p.price_open)
    return levels


def count_open_trades(cfg: GridConfig) -> int:
    positions = mt5.positions_get(symbol=cfg.symbol)
    if positions is None:
        return 0
    return sum(1 for p in positions if p.magic == cfg.magic)


def total_floating_pl(cfg: GridConfig) -> float:
    positions = mt5.positions_get(symbol=cfg.symbol)
    if positions is None:
        return 0.0
    return sum(p.profit for p in positions if p.magic == cfg.magic)


def level_has_open_trade(level: float, cfg: GridConfig) -> bool:
    """True if any open EA position was opened near this level."""
    tol = cfg.tolerance
    positions = mt5.positions_get(symbol=cfg.symbol)
    if positions is None:
        return False
    return any(
        abs(p.price_open - level) <= tol
        for p in positions
        if p.magic == cfg.magic
    )


# ── Setup finder ──────────────────────────────────────────────────────────────

def find_setups(cfg: GridConfig, entered_levels: set) -> List[GridSetup]:
    """
    Fetch the latest bars, detect level touches, and build GridSetup objects.
    Returns empty list if no valid setup found.
    """
    if cfg.bias == "NONE":
        return []

    if not is_allowed_time(cfg):
        return []

    if count_open_trades(cfg) >= cfg.max_trades:
        return []

    df = _fetch(cfg.symbol, cfg.timeframe, count=3)
    if df is None or len(df) < 2:
        return []

    touches = detect_level_touches(df, cfg)
    if not touches:
        return []

    tick = mt5.symbol_info_tick(cfg.symbol)
    if tick is None:
        return []

    sym_info = mt5.symbol_info(cfg.symbol)
    if sym_info is None:
        return []

    setups = []
    for touch in touches:
        level      = touch["level"]
        touch_from = touch["touch_from"]
        level_type = touch["level_type"]

        # Skip already-entered levels this session
        if level in entered_levels:
            continue

        # Skip if an open trade is already at this level
        if level_has_open_trade(level, cfg):
            continue

        # Determine if this touch matches the bias
        can_long  = cfg.bias in ("LONG",  "BOTH")
        can_short = cfg.bias in ("SHORT", "BOTH")

        direction: Optional[str] = None
        if touch_from == "above" and can_long:
            direction = "LONG"
        elif touch_from == "below" and can_short:
            direction = "SHORT"
        else:
            continue

        # Compute entry, TP, SL
        entry = tick.ask if direction == "LONG" else tick.bid
        point = sym_info.point if sym_info.point > 0 else 1.0

        tp_dist = cfg.tp_pips * point
        sl_dist = cfg.sl_pips * point if cfg.sl_pips > 0 else 0.0

        if direction == "LONG":
            target    = level + tp_dist
            stop_loss = (entry - sl_dist) if sl_dist > 0 else 0.0
        else:
            target    = level - tp_dist
            stop_loss = (entry + sl_dist) if sl_dist > 0 else 0.0

        # R:R check
        rr = 0.0
        if stop_loss > 0:
            risk   = abs(entry - stop_loss)
            reward = abs(target - entry)
            rr     = round(reward / risk, 2) if risk > 0 else 0.0
            if cfg.min_rr > 0 and rr < cfg.min_rr:
                continue

        slot    = current_slot()
        session = current_session(cfg)

        notes = [
            f"Session     : {session}",
            f"Direction   : {direction}",
            f"Grid level  : {level:.0f} ({level_type})",
            f"Touch from  : {touch_from}",
            f"Entry       : {entry:.2f}",
            f"TP          : {target:.2f}  (+{tp_dist:.0f} pts)",
            f"SL          : {stop_loss:.2f}" if stop_loss > 0 else "SL          : none (use loss limit)",
            f"R:R         : 1:{rr:.2f}" if rr > 0 else "R:R         : N/A",
        ]

        setups.append(GridSetup(
            symbol=cfg.symbol, timeframe=cfg.timeframe,
            direction=direction,
            level=level, level_type=level_type, touch_from=touch_from,
            entry=entry, stop_loss=stop_loss, target=target, risk_reward=rr,
            lots=0.0,  # filled by trader.calc_lots()
            session=session, slot=slot,
            notes=notes,
        ))

    return setups


# ── Dashboard print ───────────────────────────────────────────────────────────

def print_dashboard(cfg: GridConfig):
    from datetime import datetime
    sep = "─" * 64
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tick = mt5.symbol_info_tick(cfg.symbol)
    price = tick.bid if tick else 0.0

    lvls  = nearest_levels(price, cfg)
    open_cnt  = count_open_trades(cfg)
    float_pl  = total_floating_pl(cfg)
    session   = current_session(cfg)
    slot      = current_slot()
    acct      = mt5.account_info()
    balance   = acct.balance if acct else 0.0

    print(f"\n{sep}")
    print(f"  GRID REID  v1.00  |  {cfg.symbol} [{cfg.timeframe}]")
    print(f"  Scan : {now}  |  Slot {slot}/47  —  {session}")
    print(sep)
    print(f"  Price       : {price:,.0f}")
    print(f"  Bias        : {cfg.bias}  |  Expected move: {cfg.expected_move} pts")
    print(f"  Grid step   : {cfg.grid_step} pts  |  Tolerance: {cfg.tolerance:.0f} pts")
    print(f"  Level above : {lvls['above']:,.0f}  (+{lvls['dist_above']:.0f} pts)  [{lvls['type_above']}]")
    print(f"  Level below : {lvls['below']:,.0f}  (-{lvls['dist_below']:.0f} pts)  [{lvls['type_below']}]")
    print(sep)
    print(f"  Open trades : {open_cnt} / {cfg.max_trades}")
    print(f"  Float P&L   : {float_pl:+.2f}")
    print(f"  Balance     : {balance:,.2f}")
    if cfg.loss_limit_pct > 0:
        limit = balance * cfg.loss_limit_pct / 100.0
        print(f"  Loss limit  : {cfg.loss_limit_pct:.1f}%  =  {limit:,.2f}  (float: {float_pl:+.2f})")
    if cfg.exit_level > 0:
        print(f"  Exit level  : {cfg.exit_level:,.0f}")
    print(sep)
