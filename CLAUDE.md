@AGENT.md

## Critical Rules

- Never hardcode credentials — use `keyring` for secrets, `.env` (gitignored) for non-sensitive config
- Set `MANUAL_CONFIRM=true` until the strategy is validated on demo
- Validate new grid parameters in the signal lab on ≥3M data before enabling live
- Commit format: `v1.00 — description` with trailer `Co-Authored-By: KSE`

## Commands

```bash
# Bot
python grids-python-bot/main.py --profile metaquotes
python grids-python-bot/main.py --symbol US30.f --no-confirm

# Signal lab
python grids-signal-lab/main.py US30 3M
python grids-signal-lab/main.py US30 1Y --calendar

# Lint
flake8 grids-python-bot/ grids-signal-lab/ --max-line-length=100
```

## Verification — Required Before Marking Done

| Change | How to verify |
|--------|---------------|
| EA (.mq5) edit | Compile in MetaTrader (0 errors, 0 warnings); run `/deploy-ea` |
| Bot edit | Run `python main.py`; confirm dashboard prints; no exceptions |
| New grid param | Signal lab on ≥3M: check win-rate delta by level type |
| Credential change | `python -c "import keyring; print(keyring.get_password('mt5','default_password'))"` |

## Subagents — Invoke When Relevant

| Task | Command |
|------|---------|
| Review changed code | `use the code-reviewer subagent` |
| Security scan | `use the security-reviewer subagent` |
| Check if bot is live | `use the bot-health-check subagent` |
| Deploy EA to MetaTrader | `use the ea-deployer subagent` |
| Commit and push | `use the git-push subagent` |

## Non-Obvious Behaviours

- US30 point: 1 point ≠ 1 pip. Confirm tick_size and tick_value via `mt5.symbol_info("US30")`.
- MT5 Python arrays: index 0 = oldest (opposite of MQL5 AsSeries).
- `copy_rates_from_pos(symbol, tf, 1, n)` — pos=1 skips the forming bar.
- Level touch tolerance (15 pts) is tunable — smaller = stricter, larger = more false touches.
- BOTH bias at the same level can open a LONG and SHORT simultaneously — use max_trades cap carefully.
- Economic calendar blackout: pause new entries 30 min before NFP, CPI, FOMC.
