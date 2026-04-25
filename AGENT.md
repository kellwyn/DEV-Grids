# AGENT.md — GridReid Strategy Project

> Cross-agent reference. Claude Code reads `CLAUDE.md` which imports this file.
> Other agents (Cursor, Copilot, etc.) read this file directly.

Applies to: **DEV-Grids**

---

## Strategy Identity

**GridReid** is a grid trading strategy based on US30 psychological price levels.

```
grids-mq5-ea/        MQL5 Expert Advisor (MetaTrader 5 — backtesting + live)
grids-python-bot/    Python bot — REPL-based live execution via MT5 Python API
grids-signal-lab/    Historical analysis — level win rates, slot stats, macro context
```

---

## Strategy Playbook (4 Rules)

1. **Grid levels** — Major every 1000 pts (solid lines), Mid every 250 pts (dashed),
   Minor every 50 pts (fib-derived). These are psychological round numbers where US30
   historically reverses. US30 average daily move: ~350 points.

2. **Direction bias** — Set manually at session start: LONG, SHORT, BOTH, or NONE.
   LONG = buy when price comes DOWN to a level (expect bounce UP).
   SHORT = sell when price goes UP to a level (expect drop DOWN).
   Intraday, you can trade both directions or switch bias as conditions change.

3. **Take Profit** — Always set at the NEXT grid level (50 points away).
   You are only predicting one 50-point move at a time.

4. **If wrong (adding trades)** — If price moves against bias, add another trade at
   each subsequent level. When price reverses, later entries become profitable
   and earlier entries move toward break-even, resulting in net profit.

   Example (LONG bias):
   - Buy at 38,500 → TP 38,550
   - Price drops to 38,450 → Buy again → TP 38,500
   - Price bounces to 38,500:
     · Trade at 38,450 → WIN (+50 pts)
     · Trade at 38,500 → break-even
   - Continue to 38,550 → both trades WIN

5. **Exit rules** — Emergency exit if:
   - Floating loss > N% of account balance (InpLossLimitPct)
   - Floating loss > $X (InpLossLimitUSD)
   - Price crosses physical exit level (InpExitLevel — point of no return)

---

## Repo Structure

```
root/
├── grids-mq5-ea/
│   └── GridReid_v1.00.mq5      EA for MT5 backtesting and live trading
├── grids-python-bot/
│   ├── main.py                  REPL entry point — connect, set bias, auto-execute
│   ├── bot/
│   │   ├── connection.py        MT5 connect/disconnect
│   │   ├── signals.py           GridSetup dataclass
│   │   ├── strategy.py          GridConfig + grid calculation + touch detection
│   │   └── trader.py            Lot sizing + order execution + loss limit monitor
│   └── requirements.txt
├── grids-signal-lab/
│   ├── main.py                  CLI: python main.py US30 3M [--calendar] [--no-corr]
│   ├── config.py                LabConfig dataclass
│   ├── fetcher.py               MT5 OHLCV fetch → UTC timestamps
│   ├── periods.py               48-slot 30-min framework + ICT sessions + NYSE RTH
│   ├── market_char.py           Level touch detection + reversal outcome labelling
│   ├── correlations.py          DXY/VIX/bonds/gold correlations via yfinance
│   ├── economic_calendar.py     US30 high-impact event reference + blackout windows
│   └── report.py                Console report renderer
├── .env.example
├── .gitignore
├── CREDENTIALS.md
├── AGENT.md                     (this file)
└── CLAUDE.md
```

---

## Commands

```bash
# Run the bot (REPL)
python grids-python-bot/main.py
python grids-python-bot/main.py --profile metaquotes
python grids-python-bot/main.py --symbol US30.f --no-confirm

# Signal lab
python grids-signal-lab/main.py US30 3M
python grids-signal-lab/main.py US30 1Y --calendar
python grids-signal-lab/main.py US30 6M --no-corr

# Lint
flake8 grids-python-bot/ grids-signal-lab/ --max-line-length=100
```

## Bot REPL Commands

```
bias long|short|both|none    Set daily direction bias
move <points>                Set expected daily move
step <points>                Change grid step size
tp <points>                  Set TP distance (default 50)
sl <points>                  Set SL (0 = loss limit only)
rr <ratio>                   Set min R:R (0 = disabled)
risk <pct>                   Set risk % per trade
lots <size>                  Fixed lots (0 = risk-based)
maxlots <size>               Max lot cap
loss <pct>%|$<amount>        Set loss limit
exit <price>                 Set physical exit level
periods <0,1,...>            Set allowed 30-min slot indices
sessions asian|london|ny     Toggle ICT session filter
close all                    Emergency close all trades
close <ticket>               Close specific trade
status                       Show open positions
dash                         Print dashboard
help                         Show all commands
quit                         Exit
```

---

## Key Period Indices (UTC Slots)

| Slot | Time  | Session          | Notes                   |
|------|-------|------------------|-------------------------|
| 0    | 00:00 | Asian            |                         |
| 14   | 07:00 | London           | London open             |
| 17   | 08:30 | London           | Key liquidity window    |
| 24   | 12:00 | NY pre-market    | Futures open            |
| 28   | 14:00 | NYSE pre-market  | Pre-market opens        |
| 29   | 14:30 | NYSE RTH         | NYSE regular open       |
| 34   | 17:00 | NYSE PM          | Afternoon session       |
| 41   | 20:30 | NYSE close area  |                         |
| 42   | 21:00 | After-hours      | NYSE close              |

High-liquidity periods for US30: **slots 14-17** (London) and **slots 28-34** (NYSE AM).

---

## Verification Checklist

| Change | How to verify |
|--------|---------------|
| EA edit | Compile in MetaTrader (0 errors, 0 warnings) |
| Bot edit | Run `python main.py` — confirm no startup errors |
| New filter | Signal lab on ≥3M data: check win-rate delta |
| Credential | `python -c "import keyring; print(keyring.get_password('mt5', 'default_password'))"` |

---

## Non-Obvious Behaviours

- US30 point ≠ pip. For `US30` on most brokers: 1 point = $1 per standard lot (0.01 lots = $0.01/pt).
- `MT5 copy_rates_from_pos(symbol, tf, 1, n)` — pos=1 skips the forming bar.
- Python MT5 arrays: index 0 = oldest (opposite of MQL5 AsSeries).
- Level touch tolerance (15 pts default) must match between EA and bot or historical lab data is misaligned.
- BOTH bias: same level can trigger both a LONG and SHORT — be careful with max_trades cap.
- After NFP/FOMC: grid levels remain valid but spread widens. Avoid first 15 min post-release.
