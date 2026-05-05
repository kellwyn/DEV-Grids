"""
Grid Reid — Psychological Level Grid Strategy  v1.00  (Python Bot)

This bot is a REPL that:
  1. Connects to MetaTrader 5
  2. Lets you set/change the daily direction bias interactively
  3. Monitors the US30 in a background thread for grid-level touches
  4. Auto-executes (or prompts to confirm) when a setup is detected
  5. Monitors floating P&L and enforces loss limits
  6. Responds to commands typed in the foreground terminal

Usage:
  python main.py                          # uses .env defaults
  python main.py --profile metaquotes    # named broker profile
  python main.py --symbol US30.f         # symbol override
  python main.py --no-confirm            # skip manual confirmation

Environment variables (all overridable via .env):
  SYMBOL          MT5 symbol (default: US30)
  TIMEFRAME       Chart timeframe (default: M5)
  BIAS            LONG | SHORT | BOTH | NONE  (default: LONG)
  GRID_STEP       Points between grid levels (default: 500)
  EXPECTED_MOVE   Expected daily move in points (default: 2500)
  MAX_TRADES      Max simultaneous trades (default: 4)
  RISK_PERCENT    Risk % per trade (default: 1.0)
  MAX_LOTS        Max lot cap (default: 5.0)
  FIXED_LOTS      Fixed lots (0 = risk-based)
  TP_PIPS         TP distance in points (default: 500)
  SL_PIPS         SL distance in points (default: 1200)
  LOSS_LIMIT_PCT  Max floating loss % of balance (default: 5.0)
  LOSS_LIMIT_USD  Max floating loss $ (0 = disabled)
  EXIT_LEVEL      Physical price exit (0 = disabled)
  MANUAL_CONFIRM  true = prompt | false = auto-execute (default: true)
  SCAN_INTERVAL   Seconds between scans (default: 30)
"""

import argparse
import os
import sys
import time
import threading
from datetime import datetime

from dotenv import load_dotenv

# Force UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from bot.connection import connect, disconnect
from bot.strategy   import (
    GridConfig, find_setups, print_dashboard,
    count_open_trades, total_floating_pl,
    current_session, current_slot,
)
from bot.trader     import execute_setup, close_all, close_ticket, monitor_limits

load_dotenv()

# ── CLI arguments ─────────────────────────────────────────────────────────────

_parser = argparse.ArgumentParser(description="Grid Reid Bot v1.00")
_parser.add_argument("--profile",    metavar="NAME",
                     help="Broker profile from .env (e.g. metaquotes)")
_parser.add_argument("--symbol",     metavar="SYM",
                     help="Symbol override (e.g. US30.f, US30Cash)")
_parser.add_argument("--no-confirm", action="store_true",
                     help="Auto-execute without confirmation prompts")
_args = _parser.parse_args()

# ── Profile resolution ────────────────────────────────────────────────────────

if _args.profile:
    key = _args.profile.upper().replace("-", "_")
    for var in ("SYMBOL", "MT5_PATH", "MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
        val = os.getenv(f"PROFILE_{key}_{var.replace('MT5_', '')}" if "MT5_" not in var else
                        f"PROFILE_{key}_{var}")
        if not val:
            val = os.getenv(f"PROFILE_{key}_{var}")
        if val:
            os.environ[var] = val

if _args.symbol:
    os.environ["SYMBOL"] = _args.symbol

# ── Config helpers ────────────────────────────────────────────────────────────

def _bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in ("true", "1", "yes")


def _int(key: str, default: int) -> int:
    return int(os.getenv(key, default))


def _float(key: str, default: float) -> float:
    return float(os.getenv(key, default))


def _str(key: str, default: str) -> str:
    return os.getenv(key, default)


def _periods(key: str) -> list:
    raw = os.getenv(key, "")
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]


# ── Build config ──────────────────────────────────────────────────────────────

cfg = GridConfig(
    symbol        = _str("SYMBOL",       "US30"),
    timeframe     = _str("TIMEFRAME",    "M5"),

    # Grid
    grid_step     = _int("GRID_STEP",    500),
    major_step    = _int("MAJOR_STEP",   10000),
    mid_step      = _int("MID_STEP",     2500),
    tolerance     = _float("TOLERANCE",  150.0),

    # Bias
    bias          = _str("BIAS",         "BOTH").upper(),
    expected_move = _int("EXPECTED_MOVE", 2500),

    # Trade management
    max_trades    = _int("MAX_TRADES",   4),
    tp_pips       = _float("TP_PIPS",   500.0),
    sl_pips       = _float("SL_PIPS",   1200.0),
    min_rr        = _float("MIN_RR",    0.0),

    # Risk
    risk_pct      = _float("RISK_PERCENT", 1.0),
    max_lots      = _float("MAX_LOTS",     5.0),
    fixed_lots    = _float("FIXED_LOTS",   0.0),

    # Loss limits
    loss_limit_pct = _float("LOSS_LIMIT_PCT", 5.0),
    loss_limit_usd = _float("LOSS_LIMIT_USD", 0.0),
    exit_level     = _float("EXIT_LEVEL",     0.0),

    # Filters
    use_period_filter  = _bool("USE_PERIOD_FILTER",  False),
    allowed_periods    = _periods("ALLOWED_PERIODS"),
    use_session_filter = _bool("USE_SESSION_FILTER", False),
    trade_asian        = _bool("TRADE_ASIAN",        False),
    trade_london       = _bool("TRADE_LONDON",       True),
    trade_ny           = _bool("TRADE_NY",           True),

    magic    = _int("MAGIC_NUMBER", 20260426),
    slippage = _int("SLIPPAGE",     20),
)

MANUAL_CONFIRM  = _bool("MANUAL_CONFIRM", True)   if not _args.no_confirm else False
SCAN_INTERVAL   = _int("SCAN_INTERVAL",   30)      # seconds between background scans

# ── Session-level state ───────────────────────────────────────────────────────

_entered_levels: set      = set()   # levels entered today (reset at day boundary)
_last_day:       int      = -1
_stop_event:     threading.Event = threading.Event()
_print_lock:     threading.Lock  = threading.Lock()


def _safe_print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)


# ── Background monitor thread ─────────────────────────────────────────────────

def _monitor_loop():
    global _entered_levels, _last_day

    while not _stop_event.is_set():
        try:
            # Reset entered levels at day boundary
            today = datetime.utcnow().day
            if today != _last_day:
                _entered_levels = set()
                _last_day = today

            # Loss limit check (every scan)
            if monitor_limits(cfg):
                _entered_levels.clear()

            # Scan for new setups
            setups = find_setups(cfg, _entered_levels)

            for setup in setups:
                executed = execute_setup(setup, cfg, MANUAL_CONFIRM)
                if executed:
                    _entered_levels.add(setup.level)

        except Exception as exc:
            _safe_print(f"  [monitor error] {exc}")

        _stop_event.wait(SCAN_INTERVAL)


# ── REPL command handler ──────────────────────────────────────────────────────

_VALID_BIASES = {"LONG", "SHORT", "BOTH", "NONE"}

HELP_TEXT = """
  ─── Grid Reid Commands ──────────────────────────────────────────
  bias long|short|both|none     Set daily direction bias
  move <points>                 Set expected daily move (context)
  step <points>                 Change grid step size
  risk <pct>                    Set risk % per trade
  lots <size>                   Set fixed lot size (0 = risk-based)
  maxlots <size>                Set max lot cap
  tp <points>                   Set TP distance in points
  sl <points>                   Set SL in points  (0 = none)
  rr <ratio>                    Set min R:R  (0 = disabled)
  loss <pct>%|$<amount>         Set loss limit  e.g. "5%" or "$200"
  exit <price>                  Set physical exit level  (0 = none)
  periods <0,1,...>             Set allowed 30-min slots (e.g. 28,29,30)
  sessions asian|london|ny      Toggle ICT session filter  (comma-sep)
  interval <seconds>            Change scan interval
  status                        Show open positions and account
  close all                     Close all EA positions
  close <ticket>                Close specific position by ticket
  dash                          Print dashboard
  help                          Show this help
  quit / exit                   Disconnect and exit
  ─────────────────────────────────────────────────────────────────
"""


def _show_status():
    import MetaTrader5 as mt5
    positions = mt5.positions_get(symbol=cfg.symbol) or []
    ea_pos    = [p for p in positions if p.magic == cfg.magic]
    float_pl  = total_floating_pl(cfg)
    acct      = mt5.account_info()

    sep = "─" * 64
    _safe_print(f"\n{sep}")
    _safe_print(f"  STATUS  |  {cfg.symbol}  |  Bias: {cfg.bias}")
    _safe_print(sep)

    if not ea_pos:
        _safe_print("  No open positions.")
    else:
        _safe_print(f"  {'Ticket':>10}  {'Dir':>5}  {'Open':>10}  {'TP':>10}  {'SL':>10}  {'P&L':>10}")
        for p in ea_pos:
            dir_str = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
            _safe_print(f"  {p.ticket:>10}  {dir_str:>5}  {p.price_open:>10.2f}"
                        f"  {p.tp:>10.2f}  {p.sl:>10.2f}  {p.profit:>+10.2f}")

    _safe_print(sep)
    _safe_print(f"  Total float P&L : {float_pl:+.2f}")
    if acct:
        _safe_print(f"  Balance         : {acct.balance:,.2f}  |  Equity: {acct.equity:,.2f}  {acct.currency}")
    _safe_print(sep)


def _handle_command(line: str) -> bool:
    """Parse and execute a REPL command. Returns False to quit."""
    global SCAN_INTERVAL

    parts = line.strip().split()
    if not parts:
        return True

    cmd = parts[0].lower()

    if cmd in ("quit", "exit"):
        return False

    elif cmd == "help":
        _safe_print(HELP_TEXT)

    elif cmd == "status":
        _show_status()

    elif cmd == "dash":
        print_dashboard(cfg)

    elif cmd == "bias" and len(parts) >= 2:
        b = parts[1].upper()
        if b in _VALID_BIASES:
            cfg.bias = b
            _safe_print(f"  Bias set to: {cfg.bias}")
        else:
            _safe_print(f"  Unknown bias '{b}'. Use: long / short / both / none")

    elif cmd == "move" and len(parts) >= 2:
        try:
            cfg.expected_move = int(parts[1])
            _safe_print(f"  Expected move: {cfg.expected_move} pts")
        except ValueError:
            _safe_print("  Usage: move <points>")

    elif cmd == "step" and len(parts) >= 2:
        try:
            cfg.grid_step = int(parts[1])
            _safe_print(f"  Grid step: {cfg.grid_step} pts")
        except ValueError:
            _safe_print("  Usage: step <points>")

    elif cmd == "risk" and len(parts) >= 2:
        try:
            cfg.risk_pct = float(parts[1].rstrip("%"))
            _safe_print(f"  Risk per trade: {cfg.risk_pct}%")
        except ValueError:
            _safe_print("  Usage: risk <pct>")

    elif cmd == "lots" and len(parts) >= 2:
        try:
            cfg.fixed_lots = float(parts[1])
            mode = "fixed" if cfg.fixed_lots > 0 else "risk-based"
            _safe_print(f"  Fixed lots: {cfg.fixed_lots}  ({mode})")
        except ValueError:
            _safe_print("  Usage: lots <size>")

    elif cmd == "maxlots" and len(parts) >= 2:
        try:
            cfg.max_lots = float(parts[1])
            _safe_print(f"  Max lots: {cfg.max_lots}")
        except ValueError:
            _safe_print("  Usage: maxlots <size>")

    elif cmd == "tp" and len(parts) >= 2:
        try:
            cfg.tp_pips = float(parts[1])
            _safe_print(f"  TP distance: {cfg.tp_pips} pts")
        except ValueError:
            _safe_print("  Usage: tp <points>")

    elif cmd == "sl" and len(parts) >= 2:
        try:
            cfg.sl_pips = float(parts[1])
            mode = f"{cfg.sl_pips} pts" if cfg.sl_pips > 0 else "none (loss limit only)"
            _safe_print(f"  SL: {mode}")
        except ValueError:
            _safe_print("  Usage: sl <points>  (0 = none)")

    elif cmd == "rr" and len(parts) >= 2:
        try:
            cfg.min_rr = float(parts[1])
            mode = f"min 1:{cfg.min_rr:.2f}" if cfg.min_rr > 0 else "disabled"
            _safe_print(f"  Min R:R: {mode}")
        except ValueError:
            _safe_print("  Usage: rr <ratio>  (0 = disabled)")

    elif cmd == "loss" and len(parts) >= 2:
        raw = parts[1]
        try:
            if raw.startswith("$"):
                cfg.loss_limit_usd = float(raw[1:])
                _safe_print(f"  Loss limit: ${cfg.loss_limit_usd:.2f}")
            elif raw.endswith("%"):
                cfg.loss_limit_pct = float(raw[:-1])
                _safe_print(f"  Loss limit: {cfg.loss_limit_pct:.1f}%")
            else:
                cfg.loss_limit_pct = float(raw)
                _safe_print(f"  Loss limit: {cfg.loss_limit_pct:.1f}%")
        except ValueError:
            _safe_print("  Usage: loss 5%  or  loss $200")

    elif cmd == "exit" and len(parts) >= 2:
        try:
            cfg.exit_level = float(parts[1])
            mode = f"{cfg.exit_level:.0f}" if cfg.exit_level > 0 else "disabled"
            _safe_print(f"  Physical exit level: {mode}")
        except ValueError:
            _safe_print("  Usage: exit <price>  (0 = disabled)")

    elif cmd == "periods" and len(parts) >= 2:
        raw = " ".join(parts[1:])
        slots = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]
        slots = [s for s in slots if 0 <= s <= 47]
        cfg.allowed_periods    = slots
        cfg.use_period_filter  = len(slots) > 0
        if slots:
            _safe_print(f"  Period filter ON — slots: {slots}")
        else:
            _safe_print("  Period filter OFF")

    elif cmd == "sessions" and len(parts) >= 2:
        chosen = {p.lower() for p in " ".join(parts[1:]).split(",")}
        cfg.trade_asian        = "asian"  in chosen
        cfg.trade_london       = "london" in chosen
        cfg.trade_ny           = "ny"     in chosen
        cfg.use_session_filter = any([cfg.trade_asian, cfg.trade_london, cfg.trade_ny])
        active = [s for s, v in [("Asian", cfg.trade_asian), ("London", cfg.trade_london),
                                   ("NY",    cfg.trade_ny)] if v]
        _safe_print(f"  Session filter: {', '.join(active) if active else 'OFF'}")

    elif cmd == "interval" and len(parts) >= 2:
        try:
            SCAN_INTERVAL = int(parts[1])
            _safe_print(f"  Scan interval: {SCAN_INTERVAL}s")
        except ValueError:
            _safe_print("  Usage: interval <seconds>")

    elif cmd == "close":
        if len(parts) >= 2 and parts[1].lower() == "all":
            n = close_all(cfg, reason="manual")
            _entered_levels.clear()
            _safe_print(f"  Closed {n} position(s).")
        elif len(parts) >= 2:
            try:
                ticket = int(parts[1])
                close_ticket(ticket, cfg)
            except ValueError:
                _safe_print("  Usage: close all  or  close <ticket>")
        else:
            _safe_print("  Usage: close all  or  close <ticket>")

    else:
        _safe_print(f"  Unknown command: '{line}'.  Type 'help' for commands.")

    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def _print_banner():
    mode = "AUTO-EXECUTE" if not MANUAL_CONFIRM else "MANUAL CONFIRM"
    print(f"""
  ╔══════════════════════════════════════════════════════════════╗
  ║  GRID REID  v1.00  —  US30 Psychological Level Grid Bot     ║
  ╚══════════════════════════════════════════════════════════════╝
  Symbol        : {cfg.symbol}  [{cfg.timeframe}]
  Bias          : {cfg.bias}  |  Expected move: {cfg.expected_move} pts
  Grid step     : {cfg.grid_step} pts  |  Tolerance: {cfg.tolerance:.0f} pts
  Max trades    : {cfg.max_trades}
  TP            : {cfg.tp_pips:.0f} pts  |  SL: {'none' if cfg.sl_pips == 0 else f'{cfg.sl_pips:.0f} pts'}
  Risk / trade  : {cfg.risk_pct}%  |  Max lots: {cfg.max_lots}  |  Fixed: {cfg.fixed_lots if cfg.fixed_lots else 'no'}
  Loss limit    : {cfg.loss_limit_pct:.1f}%  |  ${cfg.loss_limit_usd:.2f}
  Mode          : {mode}  |  Scan every {SCAN_INTERVAL}s
  Type 'help' for commands.  Ctrl+C to stop.
""")


def main():
    try:
        connect()
        _print_banner()
        print_dashboard(cfg)

        monitor_thread = threading.Thread(target=_monitor_loop, daemon=True)
        monitor_thread.start()

        while True:
            try:
                line = input("\n  > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Stopped by user.")
                break

            if not _handle_command(line):
                break

    finally:
        _stop_event.set()
        disconnect()


if __name__ == "__main__":
    main()
