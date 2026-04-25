"""
Order execution and trade management for GridReid v1.00.

Responsibilities:
  - calc_lots()        risk-based or fixed lot sizing
  - send_order()       market order with SL/TP
  - close_all()        emergency close all EA positions
  - close_ticket()     close single position by ticket
  - monitor_limits()   check loss limits and auto-close if breached
"""

import MetaTrader5 as mt5

from .signals  import GridSetup
from .strategy import GridConfig, count_open_trades, total_floating_pl


# ── Lot sizing ────────────────────────────────────────────────────────────────

def calc_lots(setup: GridSetup, cfg: GridConfig) -> float:
    """Risk-based lot sizing capped at cfg.max_lots. Mirrors CalcLots() in the EA."""
    if cfg.fixed_lots > 0:
        return _normalise_lots(cfg.fixed_lots, setup.symbol)

    sym = mt5.symbol_info(setup.symbol)
    if sym is None:
        return 0.01

    acct = mt5.account_info()
    if acct is None:
        return sym.volume_min

    balance  = acct.balance
    risk_amt = balance * cfg.risk_pct / 100.0

    # If no hard SL, size against one grid step of risk
    if setup.stop_loss > 0:
        sl_dist = abs(setup.entry - setup.stop_loss)
    else:
        sl_dist = cfg.grid_step * (sym.point if sym.point > 0 else 1.0)

    if sl_dist == 0 or sym.trade_tick_size == 0 or sym.trade_tick_value == 0:
        return sym.volume_min

    val_per_pt = sym.trade_tick_value / sym.trade_tick_size
    lot        = risk_amt / (sl_dist * val_per_pt)

    return _normalise_lots(lot, setup.symbol)


def _normalise_lots(lots: float, symbol: str) -> float:
    sym = mt5.symbol_info(symbol)
    if sym is None:
        return round(lots, 2)

    min_lot  = sym.volume_min
    max_lot  = sym.volume_max
    lot_step = sym.volume_step if sym.volume_step > 0 else 0.01

    lots = max(min_lot, min(max_lot, lots))
    lots = round(round(lots / lot_step) * lot_step, 8)
    return lots


# ── Order execution ───────────────────────────────────────────────────────────

def send_order(setup: GridSetup, lots: float, cfg: GridConfig) -> bool:
    """Send a market order to MT5. Returns True on success."""
    tick = mt5.symbol_info_tick(setup.symbol)
    if tick is None:
        print(f"  ERROR: no tick for {setup.symbol}")
        return False

    sym = mt5.symbol_info(setup.symbol)
    if sym is None:
        print(f"  ERROR: no symbol_info for {setup.symbol}")
        return False

    if setup.direction == "LONG":
        order_type = mt5.ORDER_TYPE_BUY
        price      = tick.ask
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price      = tick.bid

    # Determine fill mode from broker bitmask
    fm   = sym.filling_mode
    fill = (mt5.ORDER_FILLING_FOK   if fm & 1 else
            mt5.ORDER_FILLING_IOC   if fm & 2 else
            mt5.ORDER_FILLING_RETURN)

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       setup.symbol,
        "volume":       lots,
        "type":         order_type,
        "price":        price,
        "sl":           setup.stop_loss if setup.stop_loss > 0 else 0.0,
        "tp":           setup.target,
        "deviation":    cfg.slippage,
        "magic":        cfg.magic,
        "comment":      f"GridReid_{setup.direction[0]}_{int(setup.level)}",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": fill,
    }

    result = mt5.order_send(request)

    if result is None:
        print(f"  ORDER FAILED: {mt5.last_error()}")
        return False
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"  ORDER FAILED  retcode={result.retcode}  {result.comment}")
        return False

    sep = "=" * 64
    print(f"\n{sep}")
    print(f"  ORDER EXECUTED  #{result.order}")
    print(f"  Symbol    : {setup.symbol}  [{setup.timeframe}]")
    print(f"  Direction : {setup.direction}  |  Level: {setup.level:.0f} ({setup.level_type})")
    print(f"  Volume    : {lots} lots")
    print(f"  Price     : {result.price:.2f}")
    print(f"  Target    : {setup.target:.2f}")
    print(f"  Stop Loss : {setup.stop_loss:.2f}" if setup.stop_loss > 0 else "  Stop Loss : none")
    print(f"  R:R       : 1:{setup.risk_reward:.2f}" if setup.risk_reward > 0 else "  R:R       : N/A")
    print(f"  Session   : {setup.session}  (Slot {setup.slot})")
    print(sep)
    return True


# ── Close operations ──────────────────────────────────────────────────────────

def close_all(cfg: GridConfig, reason: str = "manual") -> int:
    """Close all EA positions on this symbol. Returns number of closed trades."""
    positions = mt5.positions_get(symbol=cfg.symbol)
    if positions is None:
        return 0

    closed = 0
    for pos in positions:
        if pos.magic != cfg.magic:
            continue

        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            continue

        if pos.type == mt5.POSITION_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price      = tick.bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price      = tick.ask

        sym  = mt5.symbol_info(pos.symbol)
        fm   = sym.filling_mode if sym else 3
        fill = (mt5.ORDER_FILLING_FOK if fm & 1 else
                mt5.ORDER_FILLING_IOC if fm & 2 else
                mt5.ORDER_FILLING_RETURN)

        req = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       pos.symbol,
            "volume":       pos.volume,
            "type":         order_type,
            "position":     pos.ticket,
            "price":        price,
            "deviation":    cfg.slippage,
            "magic":        cfg.magic,
            "comment":      f"GridReid_close_{reason}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": fill,
        }
        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            closed += 1
        else:
            err = mt5.last_error() if result is None else (result.retcode, result.comment)
            print(f"  CLOSE FAILED ticket={pos.ticket}  {err}")

    if closed:
        print(f"  Closed {closed} position(s) — reason: {reason}")
    return closed


def close_ticket(ticket: int, cfg: GridConfig) -> bool:
    """Close a single position by ticket number."""
    if not mt5.positions_get():
        return False

    positions = mt5.positions_get(symbol=cfg.symbol)
    if positions is None:
        return False

    for pos in positions:
        if pos.ticket != ticket or pos.magic != cfg.magic:
            continue

        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return False

        order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price      = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask

        sym  = mt5.symbol_info(pos.symbol)
        fm   = sym.filling_mode if sym else 3
        fill = (mt5.ORDER_FILLING_FOK if fm & 1 else
                mt5.ORDER_FILLING_IOC if fm & 2 else
                mt5.ORDER_FILLING_RETURN)

        req = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       pos.symbol,
            "volume":       pos.volume,
            "type":         order_type,
            "position":     ticket,
            "price":        price,
            "deviation":    cfg.slippage,
            "magic":        cfg.magic,
            "comment":      "GridReid_close_manual",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": fill,
        }
        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"  Closed ticket #{ticket}")
            return True
        err = mt5.last_error() if result is None else (result.retcode, result.comment)
        print(f"  CLOSE FAILED #{ticket}  {err}")
        return False

    print(f"  Ticket #{ticket} not found in open positions.")
    return False


# ── Loss limit monitor ────────────────────────────────────────────────────────

def monitor_limits(cfg: GridConfig) -> bool:
    """
    Check all loss limits. Auto-close all trades if any limit is breached.
    Returns True if limits were breached and trades closed.
    """
    float_pl = total_floating_pl(cfg)
    reason   = None

    if cfg.loss_limit_pct > 0:
        acct = mt5.account_info()
        if acct and float_pl < -(acct.balance * cfg.loss_limit_pct / 100.0):
            reason = f"loss_limit_{cfg.loss_limit_pct:.1f}pct"

    if reason is None and cfg.loss_limit_usd > 0 and float_pl < -cfg.loss_limit_usd:
        reason = f"loss_limit_{cfg.loss_limit_usd:.2f}usd"

    if reason is None and cfg.exit_level > 0:
        tick = mt5.symbol_info_tick(cfg.symbol)
        if tick:
            bid = tick.bid
            if cfg.bias == "LONG"  and bid < cfg.exit_level:
                reason = f"exit_level_{cfg.exit_level:.0f}"
            if cfg.bias == "SHORT" and bid > cfg.exit_level:
                reason = f"exit_level_{cfg.exit_level:.0f}"

    if reason:
        print(f"\n  !! LOSS LIMIT BREACHED — reason: {reason}")
        print(f"     Float P&L: {float_pl:+.2f}  |  Closing all trades...")
        close_all(cfg, reason=reason)
        return True

    return False


# ── Execute a detected setup ──────────────────────────────────────────────────

def execute_setup(setup: GridSetup, cfg: GridConfig, manual_confirm: bool) -> bool:
    """
    Calculate lots, optionally prompt for confirmation, then send the order.
    Returns True if order was placed.
    """
    lots = calc_lots(setup, cfg)
    acct = mt5.account_info()
    balance  = acct.balance if acct else 0.0
    currency = acct.currency if acct else ""
    risk_usd = balance * cfg.risk_pct / 100.0

    sep  = "=" * 64
    sep2 = "-" * 64

    print(f"\n{sep}")
    print(f"  ═══  GRID REID  v1.00  —  {setup.direction} SIGNAL  ═══")
    print(sep2)
    for note in setup.notes:
        print(f"  {note}")
    print(sep2)
    print(f"  Lots      : {lots:.2f}  "
          f"(risk {cfg.risk_pct}% = {risk_usd:.2f} {currency}, cap {cfg.max_lots})")
    print(sep)

    if not manual_confirm:
        print("  [AUTO] Executing order...")
        setup.lots = lots
        return send_order(setup, lots, cfg)

    while True:
        try:
            ans = input("  Execute?  [y / n / q]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return False

        if ans == "y":
            setup.lots = lots
            return send_order(setup, lots, cfg)
        elif ans == "n":
            print("  Setup skipped.")
            return False
        elif ans == "q":
            raise SystemExit(0)
        else:
            print("  Enter  y  n  or  q")
