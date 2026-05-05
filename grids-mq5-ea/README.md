# GridReid — MQL5 Expert Advisor

US30 psychological level grid strategy. Versions share the same core logic with each build layering additional management on top.

---

## Files

| File | Description |
|------|-------------|
| `GridReid_v1.00.mq5` | Initial release — core grid strategy |
| `GridReid_v1.1.mq5`  | Cross-trade management build |
| `GridReid_v1.2.mq5`  | v1.3 code (4 targeted improvements — see v1.3 section) |

---

## Strategy Rules (both versions)

### 1. Grid Levels

Price levels are drawn at fixed intervals from the current price:

| Level type | Spacing | Line style |
|------------|---------|------------|
| Major      | 1000 pts | Solid |
| Mid        | 250 pts  | Dashed |
| Minor      | 50 pts   | Dotted |

US30 average daily move ~350 points. Minor levels (50 pts) are the active trading levels.

### 2. Direction Bias

Set once per session via the `InpBias` input:

| Bias | Action |
|------|--------|
| LONG  | Buy when price comes **down** to a level (expect bounce up) |
| SHORT | Sell when price goes **up** to a level (expect drop down) |
| BOTH  | Long at lower touches, short at upper touches |
| NONE  | Monitor grid only — no entries |

### 3. Take Profit

Every trade targets the **next grid level** in the bias direction — always 50 points away. You are only predicting one 50-point move at a time.

- LONG trade TP = entry level + 50 pts
- SHORT trade TP = entry level − 50 pts

### 4. Adding Trades (Pyramid)

If price moves against bias, a new trade is added at each subsequent level touched (subject to `InpMaxTrades` cap). When price reverses:

- Later entries become profitable first
- Earlier entries move toward break-even
- Net result is a profit once all TPs are hit

**Example — LONG bias, 3 trades:**

```
Price falls:  Buy @ 38,500  TP = 38,550
              Buy @ 38,450  TP = 38,500
              Buy @ 38,400  TP = 38,450

Price bounces:
  38,450 → Trade #3 wins  (+50 pts)
  38,500 → Trade #2 wins  (+50 pts)
  38,550 → Trade #1 wins  (+50 pts)
```

### 5. Emergency Exit Rules

All positions are closed immediately if any of these fire:

| Trigger | Input |
|---------|-------|
| Floating loss > X% of balance | `InpLossLimitPct` (default 5%) |
| Floating loss > $X | `InpLossLimitUSD` (default 0 = off) |
| Price crosses physical exit level | `InpExitLevel` (default 0 = off) |

### 6. Period & Session Filters

- **30-min slot filter** — only trade in selected UTC slots (0–47). Slot 28 = 14:00 UTC (NYSE pre-market), slot 29 = 14:30 (NYSE open).
- **ICT session filter** — toggle Asian (22:00–09:00 UTC), London (07:00–16:00 UTC), NY (12:00–21:00 UTC).

### 7. Risk Sizing

- Risk-based: `InpRiskPct` % of balance per trade, capped at `InpMaxLots`.
- Fixed: set `InpFixedLots > 0` to override.
- One entry per level per day — level is marked as entered and skipped for the rest of the day.

---

## Exit Criteria — Per Trade

Every trade (1st, 2nd, 3rd, …) has the **same** individual exit structure:

| Exit | Value |
|------|-------|
| Take Profit | Fixed at next grid level (+/− `InpTPPoints`, default 50 pts) |
| Stop Loss | Optional hard stop (`InpSLPoints`); default 0 = no individual SL |
| Emergency close | Portfolio-level — closes ALL trades if loss limit or exit level breached |

There is **no difference** in TP/SL between the first trade and any subsequent trade. The emergency close is the only per-portfolio exit; individual TPs fire independently at the broker.

---

## v1.00 — Initial Release

Core features only. No cross-trade management. No momentum filter. No group exits.

**What stops trading after an entry:**
- `InpMaxTrades` cap prevents more than N simultaneous positions.
- One entry per level per calendar day.
- No automatic day-end rule.

---

## v1.1 — Cross-Trade Management

All v1.00 rules apply, plus the following additions.

### Day Rules

**Rule 1 — First trade TP hit:**
If the first trade of the day closes in profit (TP hit), no new entries are opened for the rest of the day. Clean win = done.

**Rule 2 — Drawdown cycle resolved:**
If a second or later trade was opened today (meaning the first trade went into drawdown), once ALL open trades have closed (by any means — TP, group exit, or loss limit), no new entries are opened for the rest of the day.

Both rules reset at the next calendar day boundary.

### Break-Even Group Exits

When 2 or more trades are open in the same direction, the EA monitors three price levels and can close all positions automatically. Only same-direction trade groups are eligible (BOTH bias with mixed open positions is excluded).

#### Average Price Point (APP)

The lot-weighted average entry price of all open trades. When price reaches APP, total floating P&L across all trades is zero.

```
Formula: APP = Σ(entry_i × lots_i) / Σ(lots_i)

Example (equal lots, LONG):
  T1 @ 38,500 + T2 @ 38,450 + T3 @ 38,400
  APP = (38500 + 38450 + 38400) / 3 = 38,450

At price 38,450:
  T1: −50 pts   T2: 0   T3: +50 pts   Net = 0 ✓
```

**Enabled by:** `InpUseAPP = true`
**Effect:** Closes all trades for net zero (full capital recovery).

#### Secondary Average Price Point (SAPP)

The lot-weighted average entry price of all trades **except the first (oldest) trade**. When price reaches SAPP, trades T2+ are at zero; the first trade is still at a loss.

```
Formula: SAPP = Σ(entry_i × lots_i) / Σ(lots_i)  for i = 2, 3, 4...

Example (equal lots, LONG):
  T2 @ 38,450 + T3 @ 38,400
  SAPP = (38450 + 38400) / 2 = 38,425

At price 38,425:
  T1: −75 pts (full loss)   T2: −25 pts   T3: +25 pts
  T2 + T3 net = 0 ✓   Total loss = T1 only
```

**Enabled by:** `InpUseSAPP = true` (default off)
**Effect:** Closes all trades. T2+ exit at zero; T1 takes its full loss. Total day loss is limited to T1 only.
**Use case:** Price has recovered slightly but is showing weakness — exit early, limit exposure to T1 loss only.

#### T1 Break-Even (T1-BE)

When price reaches the first trade's actual open price, the first trade is at zero and all subsequent trades are in profit.

```
At price = T1 entry (38,500):
  T1: 0 pts   T2: +50 pts   T3: +100 pts   Net = +150 pts profit ✓
```

**Enabled by:** `InpUseT1BE = true`
**Effect:** Closes all trades for a net profit. Best group outcome.

#### Exit Priority and Price Levels (LONG example)

As price rises from the drawdown low:

```
Price level reached →  Exit triggered
─────────────────────────────────────
SAPP  (38,425)  →  T1 loss + T2+ at zero     [earliest / worst]
APP   (38,450)  →  All trades at zero         [middle]
T1-BE (38,500)  →  All trades net profit      [latest / best]
```

The EA checks T1-BE first, then APP, then SAPP. **If all three are enabled, SAPP fires first (lowest price for LONG).** Recommended defaults: `APP + T1-BE on`, `SAPP off`. Enable SAPP only on days when you want an early defensive exit.

### Momentum Check (Before Concurrent Trades)

Before opening any trade after the first, the EA measures recent directional momentum:

- Compares `close[1]` vs `close[1 + N]` over `InpMomentumBars` (default 3) completed bars.
- If the net move exceeds `InpMomentumFactor × ATR(14)` (default 1.5×) in the direction opposite to bias, the level is **skipped**.
- The scan loop continues to the next level touched in the same bar. If only one level was touched per bar (typical), the EA waits for the next bar and re-evaluates at the lower level.

**Effect for LONG:** If price is falling aggressively (bearish momentum > 1.5 × ATR), skip the 2nd entry at the next level and wait for one level further down. This reduces entries during fast, one-directional drops.

**Enabled by:** `InpUseMomentum = true`

### News Day Filter

A manual toggle (`InpNewsFilter`) that blocks new entries during a configurable UTC window. Default window: **13:30–15:00 UTC** (1 hour before NYSE AM open at 14:30 UTC, 30 minutes after).

Configure for any high-impact news event (NFP, CPI, FOMC):

| Input | Default | Meaning |
|-------|---------|---------|
| `InpNewsFilter` | false | Toggle on before a news day |
| `InpNewsBlockStartH / M` | 13:30 UTC | Block start |
| `InpNewsBlockEndH / M` | 15:00 UTC | Block end |

Existing open trades are **not** closed when the blackout starts — only new entries are blocked.

### Entry Arrows

A white `OBJ_ARROW_BUY` (↑) or `OBJ_ARROW_SELL` (↓) is drawn on the chart at each trade entry level. Arrows are cleaned up when the EA is removed from the chart.

### Dashboard (v1.1 additions)

The chart comment now shows:

```
  Open trades : 3 / 5  (today: 3)
  Float P&L   : -150.00

  T1 entry   : 38500  (T1-BE / net profit)
  APP        : 38450  (all trades net zero)
  SAPP       : 38425  (T1 loss, T2+ zero)

  Day status : ACTIVE
```

Day status values: `ACTIVE`, `DONE — no new entries`, `NEWS BLACKOUT`.

---

## v1.3 — Four Targeted Improvements (in GridReid_v1.2.mq5)

All v1.1 rules apply, plus the following changes.

### Fix 1 — T1 Detection Under BOTH Bias

`CheckFirstTradeStatus()` previously used a time-windowed `HistorySelect(openTime, now)` to find the T1 closing deal. Under BOTH bias, concurrent opposite-direction trades in the same window caused mismatches, allowing unlimited pyramid adding on loss-limit days.

**Fix:** `HistorySelectByPosition(g_firstTradePosID)` selects only deals belonging to the exact T1 position ID, independent of time windows or concurrent trades. `POSITION_IDENTIFIER` is now recorded at T1 entry.

### Fix 2 — Momentum Gate Applied to T1

The v1.1 momentum check had `g_tradesOpenedToday >= 1 &&` — meaning T1 was never filtered. Analysis of 9 loss-limit events found 7/9 were T1 entries with no momentum filter applied. The exemption has been removed; `IsMomentumOpposite()` now runs for all trades including T1.

### Fix 3 — BIAS_AUTO

A new `BIAS_AUTO = 4` enum value. When selected, the EA computes the operative bias each bar using `iBands(SMA=200, StdDev=InpStdDevMult)`:

| Price position | Effective bias |
|---|---|
| Above upper band (SMA + N×σ) | SHORT |
| Below lower band (SMA − N×σ) | LONG |
| Between bands | NONE |

New inputs: `InpSMAperiod` (default 200), `InpStdDevMult` (default 1.0 = ±1 standard deviation).

Dashboard shows `AUTO→LONG`, `AUTO→SHORT`, or `AUTO→NONE`.

### Fix 4 — Trade Session Expiry

Each trade is automatically closed at the end of the ICT session it was opened in, or after `InpMaxDurationHours` (default 4h) — whichever comes first.

| Session open time | Session end (UTC) |
|---|---|
| Asian  22:00–09:00 | 09:00 |
| London 07:00–16:00 | 16:00 |
| London+NY overlap 12:00–16:00 | 16:00 |
| NY-only 16:00–21:00 | 21:00 |
| Off-session 21:00–22:00 | Hard cap only |

Set `InpMaxDurationHours = 0` to disable the hard cap and use session end only.

---

## Verification Before Running Live

| Change | How to verify |
|--------|---------------|
| EA edit | MetaEditor F7 — 0 errors, 0 warnings |
| New parameters | Signal lab on ≥3M data: check win-rate delta by level type |
| Group exits | Backtest: confirm APP/SAPP/T1-BE closes at correct price levels |
| News filter | Enable InpNewsFilter, confirm no entries open during blackout window |
| Momentum skip | Backtest during strong trend days: verify entries skip one level |

---

## Key Non-Obvious Behaviours

- US30: 1 point ≠ 1 pip. Confirm `tick_size` and `tick_value` via `mt5.symbol_info("US30")`.
- APP/SAPP checks run every tick. Individual broker TPs also run independently — whichever fires first closes the trade.
- SAPP is reached before APP (for LONG). Enabling both means SAPP always fires first. Use one or the other.
- Momentum skip applies to ALL trades including T1 (v1.3+). Earlier versions exempted T1.
- Day rules reset at the calendar day boundary (UTC bar time), not at session open.
- `MANUAL_CONFIRM=true` in the Python bot must be set until the strategy is validated on demo. The EA has no equivalent flag — validate via backtesting before attaching to a live chart.
