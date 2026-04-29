//+------------------------------------------------------------------+
//|  GridReid — Psychological Level Grid Strategy EA                  |
//|  Instrument: US30 (Dow Jones Industrial Average)                 |
//|                                                                  |
//|  STRATEGY PLAYBOOK                                               |
//|   1. Grid levels at every InpGridStep points (default 50)       |
//|      Major levels : every 1000 points — strong reversal zones   |
//|      Mid levels   : every 250 points  — intermediate support/res |
//|      Minor levels : every 50 points   — active trading levels   |
//|                                                                  |
//|   2. Daily bias: LONG, SHORT, or BOTH                           |
//|      LONG  — buy when price comes DOWN to a level               |
//|      SHORT — sell when price goes UP to a level                 |
//|      BOTH  — buy at lower touches, sell at upper touches        |
//|      NONE  — monitor grid only, no entries                      |
//|                                                                  |
//|   3. TP = next grid level in bias direction (InpTPPoints)       |
//|      SL = optional hard stop in points (0 = use loss limit only)|
//|                                                                  |
//|   4. If price moves against bias, add trades at each new level  |
//|      (pyramid adding). Max trades capped by InpMaxTrades.       |
//|                                                                  |
//|   5. Emergency exit when:                                       |
//|      · Total floating loss >= InpLossLimitPct % of balance      |
//|      · Total floating loss >= InpLossLimitUSD (if > 0)         |
//|      · Price crosses InpExitLevel (point of no return)          |
//|                                                                  |
//|   6. Period filter: trade only in selected 30-min UTC slots     |
//|      Slot 0 = 00:00 UTC, Slot 28 = 14:00 UTC, Slot 47 = 23:30  |
//|      ICT sessions: Asian 22:00-09:00 / London 07:00-16:00 /    |
//|                    NY 12:00-21:00 (all UTC)                     |
//|                                                                  |
//|─────────────────── VERSION HISTORY ─────────────────────────────|
//|  v1.00  2026-04-26  — Initial release                           |
//|    · Grid level display: major/mid/minor horizontal lines       |
//|    · LONG / SHORT / BOTH bias with pyramid trade adding         |
//|    · Loss limit: % of balance, USD, physical exit level         |
//|    · Period filter: 48 × 30-min UTC slots (comma-separated)     |
//|    · ICT session filter: Asian / London / NY                   |
//|    · Risk-based lot sizing + fixed lot option                   |
//|    · Open-trade tracking — one entry per level per day          |
//|    · Chart dashboard via Comment()                              |
//|                                                                  |
//|  v1.1   2026-04-30  — Cross-trade management                    |
//|    · Day rule 1: stop entries after first-trade TP hit          |
//|    · Day rule 2: stop entries after full drawdown cycle         |
//|    · APP exit: close all at Average Price Point (net zero)      |
//|    · SAPP exit: close T2+ at zero, T1 at full loss             |
//|    · T1-BE exit: close all at T1 entry (T1 zero, rest profit)  |
//|    · Momentum check: skip level if strong opposite momentum     |
//|    · News filter: manual blackout window before NY AM open      |
//|    · Entry arrows: white buy/sell arrows at each trade entry    |
//+------------------------------------------------------------------+

#property copyright "Grid Reid Strategy"
#property version   "1.10"
#property description "GridReid — US30 Psychological Level Grid Strategy v1.1"
#property strict

#include <Trade\Trade.mqh>

//── Bias enum ─────────────────────────────────────────────────────

enum ENUM_GRID_BIAS
{
    BIAS_LONG  = 0,  // Long only  (buy dips to levels)
    BIAS_SHORT = 1,  // Short only (sell rallies to levels)
    BIAS_BOTH  = 2,  // Both directions (classic grid)
    BIAS_NONE  = 3,  // Monitor only — no entries
};

//── Trade info struct (for APP/SAPP sort by open time) ────────────

struct STradeInfo
{
    ulong    ticket;
    double   entry;
    double   lots;
    datetime openTime;
    bool     isLong;
};

//── Inputs ────────────────────────────────────────────────────────

input group "=== Grid Configuration ==="
input int    InpGridStep         = 50;         // Grid step in points
input int    InpMajorStep        = 1000;       // Major level spacing (solid lines)
input int    InpMidStep          = 250;        // Mid level spacing (dashed lines)
input int    InpLevelsAbove      = 12;         // Grid levels shown above price
input int    InpLevelsBelow      = 12;         // Grid levels shown below price
input double InpLevelTolerance   = 15.0;       // Touch tolerance in points

input group "=== Direction Bias ==="
input ENUM_GRID_BIAS InpBias     = BIAS_LONG;  // Daily trading bias
input int    InpExpectedMove     = 350;        // Expected daily range (points)
input int    InpMaxTrades        = 5;          // Max simultaneous grid trades

input group "=== Exit Settings ==="
input int    InpTPPoints         = 50;         // TP distance in points (one grid step)
input int    InpSLPoints         = 0;          // SL distance in points (0 = loss limit only)
input double InpMinRR            = 0.0;        // Minimum R:R ratio (0 = disabled)
input double InpLossLimitPct     = 5.0;        // Max floating loss as % of balance
input double InpLossLimitUSD     = 0.0;        // Max floating loss in $ (0 = disabled)
input double InpExitLevel        = 0.0;        // Physical exit price (0 = disabled)

input group "=== Risk Management ==="
input double InpRiskPct          = 1.0;        // Risk % per trade
input double InpMaxLots          = 5.0;        // Max lot size cap
input double InpFixedLots        = 0.0;        // Fixed lots (0 = risk-based)
input int    InpMagicNumber      = 20260426;   // EA magic number
input int    InpSlippage         = 20;         // Max slippage in points

input group "=== Period Filter (30-min UTC slots) ==="
input bool   InpUsePeriodFilter  = false;      // Enable 30-min period filter
input string InpAllowedPeriods   = "";         // Comma-separated slot indices 0-47

input group "=== ICT Session Filter ==="
input bool   InpUseSessionFilter = false;      // Enable ICT session filter
input bool   InpTradeAsian       = false;      // Trade Asian session  (22:00-09:00 UTC)
input bool   InpTradeLondon      = true;       // Trade London session (07:00-16:00 UTC)
input bool   InpTradeNY          = true;       // Trade NY session     (12:00-21:00 UTC)

input group "=== News Day Filter ==="
input bool   InpNewsFilter       = false;      // News day: block entries in blackout window
input int    InpNewsBlockStartH  = 13;         // Blackout start hour UTC (default 13 = 1hr before NY AM)
input int    InpNewsBlockStartM  = 30;         // Blackout start minute UTC
input int    InpNewsBlockEndH    = 15;         // Blackout end hour UTC
input int    InpNewsBlockEndM    = 0;          // Blackout end minute UTC

input group "=== Break-Even Group Exits ==="
input bool   InpUseAPP           = true;       // APP exit: close all at Average Price Point (net zero)
input bool   InpUseSAPP          = false;      // SAPP exit: T1 full loss + T2+ at zero
input bool   InpUseT1BE          = true;       // T1-BE exit: close all when price = T1 entry (net profit)

input group "=== Momentum Filter ==="
input bool   InpUseMomentum      = true;       // Skip level if strong opposing momentum
input int    InpMomentumBars     = 3;          // Bars to measure directional momentum
input double InpMomentumFactor   = 1.5;        // ATR(14) multiple to qualify high momentum

input group "=== Chart Display ==="
input bool   InpShowGrid         = true;       // Draw grid lines on chart
input color  InpMajorColor       = clrGray;    // Major level colour
input color  InpMidColor         = clrDimGray; // Mid level colour
input color  InpMinorColor       = clrDarkSlateGray; // Minor level colour
input int    InpMajorWidth       = 2;          // Major line width
input int    InpMidWidth         = 1;          // Mid line width
input int    InpMinorWidth       = 1;          // Minor line width

//── Global state ──────────────────────────────────────────────────

CTrade   g_trade;
datetime g_lastBar     = 0;
int      g_atrHandle   = INVALID_HANDLE;

// Parsed period filter
int      g_periods[];
int      g_periodCnt   = 0;

// Entered-level tracking (one trade per level per day)
double   g_enteredLevels[];
int      g_enteredCnt  = 0;
int      g_lastDay     = -1;

// Day state machine
bool     g_dayTradingDone    = false;  // no new entries for rest of day
bool     g_dayHadDrawdown    = false;  // a 2nd+ trade was opened today
int      g_tradesOpenedToday = 0;      // count of trades opened today

// First-trade tracking
ulong    g_firstTradeTicket  = 0;      // position ticket of today's first trade
double   g_firstTradeEntry   = 0.0;    // open price of first trade
datetime g_firstTradeTime    = 0;      // open time (for history lookup)
bool     g_firstTradeOpen    = false;  // is first trade still open?

//+------------------------------------------------------------------+
//| Init                                                             |
//+------------------------------------------------------------------+
int OnInit()
{
    g_trade.SetExpertMagicNumber(InpMagicNumber);
    g_trade.SetDeviationInPoints(InpSlippage);
    g_trade.SetTypeFilling(ORDER_FILLING_IOC);

    g_periodCnt  = ParsePeriods(InpAllowedPeriods, g_periods);
    g_atrHandle  = iATR(_Symbol, PERIOD_CURRENT, 14);

    if(g_atrHandle == INVALID_HANDLE)
        Print("GridReid v1.1: ATR handle failed — momentum filter disabled.");

    if(InpShowGrid)
        DrawGrid(SymbolInfoDouble(_Symbol, SYMBOL_BID));

    ResetDayState();

    Print("GridReid v1.1 | Bias=", EnumToString(InpBias),
          " | Step=", InpGridStep, "pts | MaxTrades=", InpMaxTrades);
    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Deinit                                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    DeleteGridObjects();
    DeleteTradeArrows();
    if(g_atrHandle != INVALID_HANDLE)
        IndicatorRelease(g_atrHandle);
    Comment("");
}

//+------------------------------------------------------------------+
//| Tick                                                             |
//+------------------------------------------------------------------+
void OnTick()
{
    double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

    // Redraw grid when price moves by a full grid step
    if(InpShowGrid)
    {
        static double s_lastDraw = 0;
        if(MathAbs(bid - s_lastDraw) >= InpGridStep)
        {
            DrawGrid(bid);
            s_lastDraw = bid;
        }
    }

    // Enforce hard loss limits every tick
    CheckLossLimits(bid);

    // Track first trade closure and update day state
    CheckFirstTradeStatus();
    CheckDayRules();

    // Group break-even exits (APP / SAPP / T1-BE)
    CheckBreakEvenExits(bid);

    // Gate on new bar
    datetime barTime = iTime(_Symbol, PERIOD_CURRENT, 0);
    if(barTime == g_lastBar)
    {
        ShowDashboard();
        return;
    }
    g_lastBar = barTime;

    // Reset day state at day boundary
    MqlDateTime dt;
    TimeToStruct(barTime, dt);
    if(dt.day != g_lastDay)
    {
        ResetDayState();
        g_lastDay = dt.day;
    }

    // Time and day-done filters
    if(g_dayTradingDone || !IsAllowedTime())
    {
        ShowDashboard();
        return;
    }

    RunStrategy();
    ShowDashboard();
}

//+------------------------------------------------------------------+
//| Main strategy — scan for level touches on completed bar          |
//+------------------------------------------------------------------+
void RunStrategy()
{
    if(InpBias == BIAS_NONE) return;

    int openCnt = CountOpenTrades();
    if(openCnt >= InpMaxTrades) return;

    double barHigh  = iHigh (_Symbol, PERIOD_CURRENT, 1);
    double barLow   = iLow  (_Symbol, PERIOD_CURRENT, 1);
    double prevClose= iClose(_Symbol, PERIOD_CURRENT, 2);

    double tol = InpLevelTolerance * _Point;
    double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
    double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

    int    levelCount = 0;
    double touchedLevels[];
    bool   touchedFromAbove[];
    bool   touchedFromBelow[];

    double startLevel = MathFloor(barLow  / InpGridStep) * InpGridStep - InpGridStep;
    double endLevel   = MathCeil (barHigh / InpGridStep) * InpGridStep + InpGridStep;

    for(double lvl = startLevel; lvl <= endLevel; lvl += InpGridStep)
    {
        bool hitFromAbove = (barLow  <= lvl + tol && barLow  >= lvl - tol && prevClose >= lvl);
        bool hitFromBelow = (barHigh >= lvl - tol && barHigh <= lvl + tol && prevClose <= lvl);

        if(!hitFromAbove && !hitFromBelow) continue;

        ArrayResize(touchedLevels,    levelCount + 1);
        ArrayResize(touchedFromAbove, levelCount + 1);
        ArrayResize(touchedFromBelow, levelCount + 1);
        touchedLevels[levelCount]    = lvl;
        touchedFromAbove[levelCount] = hitFromAbove;
        touchedFromBelow[levelCount] = hitFromBelow;
        levelCount++;
    }

    for(int i = 0; i < levelCount; i++)
    {
        double lvl = touchedLevels[i];

        if(HasEnteredLevel(lvl))   continue;
        if(LevelHasOpenTrade(lvl)) continue;

        bool canLong  = (InpBias == BIAS_LONG  || InpBias == BIAS_BOTH);
        bool canShort = (InpBias == BIAS_SHORT || InpBias == BIAS_BOTH);

        bool   entered   = false;
        ulong  newTicket = 0;

        // LONG: price came DOWN to this level
        if(canLong && touchedFromAbove[i])
        {
            // News blackout blocks all entries
            if(IsNewsBlackout()) continue;

            // For 2nd+ trade, skip level if bearish momentum is strong
            if(g_tradesOpenedToday >= 1 && IsMomentumOpposite(true))
                continue;  // skip — loop continues to next (lower) level

            if(OpenLong(lvl, ask, newTicket))
                entered = true;
        }

        // SHORT: price came UP to this level
        if(!entered && canShort && touchedFromBelow[i])
        {
            if(IsNewsBlackout()) continue;

            if(g_tradesOpenedToday >= 1 && IsMomentumOpposite(false))
                continue;

            if(OpenShort(lvl, bid, newTicket))
                entered = true;
        }

        if(entered)
        {
            if(g_tradesOpenedToday == 0)
            {
                // First trade of the day — record for tracking
                g_firstTradeTicket = newTicket;
                g_firstTradeTime   = TimeCurrent();
                g_firstTradeOpen   = true;

                // Get actual open price from position (may differ from lvl by spread/slip)
                if(PositionSelectByTicket(newTicket))
                    g_firstTradeEntry = PositionGetDouble(POSITION_PRICE_OPEN);
                else
                    g_firstTradeEntry = lvl;
            }
            else
            {
                // Second or later trade — we are in a drawdown phase
                g_dayHadDrawdown = true;
            }

            DrawEntryArrow(lvl, canLong && touchedFromAbove[i], newTicket);
            MarkLevelEntered(lvl);
            g_tradesOpenedToday++;
            openCnt++;
            if(openCnt >= InpMaxTrades) break;
        }
    }
}

//+------------------------------------------------------------------+
//| Open a LONG trade                                                |
//+------------------------------------------------------------------+
bool OpenLong(double level, double askPrice, ulong &outTicket)
{
    double tp = level + InpTPPoints * _Point;
    double sl = (InpSLPoints > 0) ? level - InpSLPoints * _Point : 0.0;

    if(InpMinRR > 0.0 && sl > 0.0)
    {
        double risk   = askPrice - sl;
        double reward = tp - askPrice;
        if(risk <= 0 || reward / risk < InpMinRR) return false;
    }

    double lots = CalcLots(askPrice, sl);
    if(lots <= 0) return false;

    string comment = StringFormat("GridReid_L_%.0f", level);
    bool ok = g_trade.Buy(lots, _Symbol, askPrice, sl, tp, comment);
    if(ok)
        outTicket = g_trade.ResultOrder();
    else
        Print("OPEN LONG failed level=", level, " err=", g_trade.ResultRetcode(),
              " ", g_trade.ResultRetcodeDescription());
    return ok;
}

//+------------------------------------------------------------------+
//| Open a SHORT trade                                               |
//+------------------------------------------------------------------+
bool OpenShort(double level, double bidPrice, ulong &outTicket)
{
    double tp = level - InpTPPoints * _Point;
    double sl = (InpSLPoints > 0) ? level + InpSLPoints * _Point : 0.0;

    if(InpMinRR > 0.0 && sl > 0.0)
    {
        double risk   = sl - bidPrice;
        double reward = bidPrice - tp;
        if(risk <= 0 || reward / risk < InpMinRR) return false;
    }

    double lots = CalcLots(bidPrice, sl);
    if(lots <= 0) return false;

    string comment = StringFormat("GridReid_S_%.0f", level);
    bool ok = g_trade.Sell(lots, _Symbol, bidPrice, sl, tp, comment);
    if(ok)
        outTicket = g_trade.ResultOrder();
    else
        Print("OPEN SHORT failed level=", level, " err=", g_trade.ResultRetcode(),
              " ", g_trade.ResultRetcodeDescription());
    return ok;
}

//+------------------------------------------------------------------+
//| Risk-based lot sizing                                            |
//+------------------------------------------------------------------+
double CalcLots(double entry, double sl)
{
    if(InpFixedLots > 0.0) return NormaliseLots(InpFixedLots);

    if(sl <= 0.0)
    {
        sl = (InpBias == BIAS_SHORT)
             ? entry + InpGridStep * _Point
             : entry - InpGridStep * _Point;
    }

    double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
    double riskAmt  = balance * InpRiskPct / 100.0;
    double slDist   = MathAbs(entry - sl);
    if(slDist <= 0) return SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);

    double tickVal  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
    double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
    if(tickVal <= 0 || tickSize <= 0) return SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);

    return NormaliseLots(riskAmt / (slDist * (tickVal / tickSize)));
}

//+------------------------------------------------------------------+
//| Clamp lots to broker limits                                      |
//+------------------------------------------------------------------+
double NormaliseLots(double lots)
{
    double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
    double maxLot  = MathMin(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX), InpMaxLots);
    double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

    lots = MathMax(minLot, MathMin(maxLot, lots));
    if(lotStep > 0)
        lots = MathRound(lots / lotStep) * lotStep;

    return NormalizeDouble(lots, 2);
}

//+------------------------------------------------------------------+
//| Emergency loss limit — close all if any threshold breached       |
//+------------------------------------------------------------------+
void CheckLossLimits(double bid)
{
    double floatPL = TotalFloatingPL();
    bool   close   = false;

    if(InpLossLimitPct > 0.0)
    {
        double balance = AccountInfoDouble(ACCOUNT_BALANCE);
        if(balance > 0 && floatPL < -(balance * InpLossLimitPct / 100.0))
        {
            Print("LOSS LIMIT PCT hit: floatPL=", floatPL);
            close = true;
        }
    }

    if(!close && InpLossLimitUSD > 0.0 && floatPL < -InpLossLimitUSD)
    {
        Print("LOSS LIMIT USD hit: floatPL=", floatPL);
        close = true;
    }

    if(!close && InpExitLevel > 0.0)
    {
        if(InpBias == BIAS_LONG  && bid < InpExitLevel) { Print("EXIT LEVEL breached (LONG)");  close = true; }
        if(InpBias == BIAS_SHORT && bid > InpExitLevel) { Print("EXIT LEVEL breached (SHORT)"); close = true; }
    }

    if(close)
    {
        CloseAllTrades();
        g_dayTradingDone = true;
    }
}

//+------------------------------------------------------------------+
//| Detect when first trade closes; apply day rule 1 (TP → done)    |
//+------------------------------------------------------------------+
void CheckFirstTradeStatus()
{
    if(g_firstTradeTicket == 0 || !g_firstTradeOpen || g_dayTradingDone) return;

    if(PositionSelectByTicket(g_firstTradeTicket)) return;  // still open

    g_firstTradeOpen = false;

    // Search deal history for the closing deal of this position
    HistorySelect(g_firstTradeTime, TimeCurrent() + 1);
    for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
    {
        ulong deal = HistoryDealGetTicket(i);
        if((ulong)HistoryDealGetInteger(deal, DEAL_POSITION_ID) != g_firstTradeTicket) continue;
        if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;

        double profit = HistoryDealGetDouble(deal, DEAL_PROFIT);
        if(profit > 0.0)
        {
            // Day rule 1: first trade hit TP — stop new entries
            g_dayTradingDone = true;
            Print("GridReid v1.1: T1 TP hit (profit=", profit, ") — no more entries today.");
        }
        else
        {
            // First trade closed at loss — flag drawdown for day rule 2
            g_dayHadDrawdown = true;
        }
        break;
    }
}

//+------------------------------------------------------------------+
//| Day rule 2: after drawdown cycle fully resolves, stop entries    |
//+------------------------------------------------------------------+
void CheckDayRules()
{
    if(g_dayTradingDone) return;

    // Rule 2: multiple trades were opened today AND all are now closed
    if(g_tradesOpenedToday >= 2 && CountOpenTrades() == 0)
    {
        g_dayTradingDone = true;
        Print("GridReid v1.1: Drawdown cycle resolved — no more entries today.");
    }
}

//+------------------------------------------------------------------+
//| Collect open EA positions sorted oldest-first                    |
//| Returns false if fewer than 2 trades or mixed directions         |
//+------------------------------------------------------------------+
bool CollectTrades(STradeInfo &trades[], int &cnt, bool &allLong)
{
    cnt = 0;
    ArrayResize(trades, 0);

    for(int i = PositionsTotal() - 1; i >= 0; i--)
    {
        ulong t = PositionGetTicket(i);
        if(!PositionSelectByTicket(t)) continue;
        if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
        if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;

        ArrayResize(trades, cnt + 1);
        trades[cnt].ticket   = t;
        trades[cnt].entry    = PositionGetDouble(POSITION_PRICE_OPEN);
        trades[cnt].lots     = PositionGetDouble(POSITION_VOLUME);
        trades[cnt].openTime = (datetime)PositionGetInteger(POSITION_TIME);
        trades[cnt].isLong   = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
        cnt++;
    }

    if(cnt < 2) return false;

    // Bubble sort oldest-first
    for(int a = 0; a < cnt - 1; a++)
        for(int b = 0; b < cnt - 1 - a; b++)
            if(trades[b].openTime > trades[b+1].openTime)
            {
                STradeInfo tmp = trades[b];
                trades[b]      = trades[b+1];
                trades[b+1]    = tmp;
            }

    // All must be same direction for group exits to be meaningful
    bool hasLong = false, hasShort = false;
    for(int i = 0; i < cnt; i++)
    {
        if(trades[i].isLong) hasLong = true; else hasShort = true;
    }
    if(hasLong && hasShort) return false;  // mixed — skip group exits

    allLong = hasLong;
    return true;
}

//+------------------------------------------------------------------+
//| Calculate APP and SAPP from open trades                          |
//|   APP  = weighted avg of ALL trades  → net zero at this price   |
//|   SAPP = weighted avg of T2+ trades  → T1 loss, T2+ zero       |
//+------------------------------------------------------------------+
void CalcBreakEvenLevels(const STradeInfo &trades[], int cnt,
                          double &app, double &sapp, double &t1Entry)
{
    t1Entry = trades[0].entry;

    double sumLots = 0, sumW = 0;
    for(int i = 0; i < cnt; i++) { sumLots += trades[i].lots; sumW += trades[i].entry * trades[i].lots; }
    app = sumW / sumLots;

    sumLots = 0; sumW = 0;
    for(int i = 1; i < cnt; i++) { sumLots += trades[i].lots; sumW += trades[i].entry * trades[i].lots; }
    sapp = (sumLots > 0) ? sumW / sumLots : app;
}

//+------------------------------------------------------------------+
//| Monitor APP / SAPP / T1-BE exits on every tick                  |
//+------------------------------------------------------------------+
void CheckBreakEvenExits(double bid)
{
    STradeInfo trades[];
    int  cnt     = 0;
    bool allLong = true;

    if(!CollectTrades(trades, cnt, allLong)) return;

    double app, sapp, t1Entry;
    CalcBreakEvenLevels(trades, cnt, app, sapp, t1Entry);

    // Check order: best outcome first (T1-BE), then APP, then SAPP
    // For LONG: price rising → hits SAPP < APP < t1Entry in sequence

    // T1-BE: close all when price = T1 entry → T1 flat, T2+ in profit
    if(InpUseT1BE)
    {
        bool hit = allLong ? (bid >= t1Entry) : (bid <= t1Entry);
        if(hit)
        {
            Print("GridReid v1.1: T1-BE exit — price=", bid,
                  " T1entry=", t1Entry, " closing all for net profit.");
            CloseAllTrades();
            g_dayTradingDone = true;
            return;
        }
    }

    // APP: close all at average price → net zero across all trades
    if(InpUseAPP)
    {
        bool hit = allLong ? (bid >= app) : (bid <= app);
        if(hit)
        {
            Print("GridReid v1.1: APP exit — price=", bid,
                  " APP=", app, " closing all at net zero.");
            CloseAllTrades();
            g_dayTradingDone = true;
            return;
        }
    }

    // SAPP: close all — T1 takes full loss, T2+ exit at zero
    if(InpUseSAPP)
    {
        bool hit = allLong ? (bid >= sapp) : (bid <= sapp);
        if(hit)
        {
            Print("GridReid v1.1: SAPP exit — price=", bid,
                  " SAPP=", sapp, " T1 takes loss, T2+ at zero.");
            CloseAllTrades();
            g_dayTradingDone = true;
            return;
        }
    }
}

//+------------------------------------------------------------------+
//| True if recent momentum strongly opposes the given direction     |
//+------------------------------------------------------------------+
bool IsMomentumOpposite(bool checkingLong)
{
    if(!InpUseMomentum || g_atrHandle == INVALID_HANDLE) return false;

    double atrBuf[];
    ArraySetAsSeries(atrBuf, true);
    if(CopyBuffer(g_atrHandle, 0, 1, 1, atrBuf) < 1) return false;
    double atr = atrBuf[0];
    if(atr <= 0) return false;

    // Net directional move of last N completed bars
    int    n         = InpMomentumBars;
    double recentMove = iClose(_Symbol, PERIOD_CURRENT, 1)
                      - iClose(_Symbol, PERIOD_CURRENT, 1 + n);

    // bearish momentum → oppose LONG; bullish momentum → oppose SHORT
    if(checkingLong  && recentMove < -(InpMomentumFactor * atr)) return true;
    if(!checkingLong && recentMove >  (InpMomentumFactor * atr)) return true;

    return false;
}

//+------------------------------------------------------------------+
//| True if current UTC time is inside the news blackout window      |
//+------------------------------------------------------------------+
bool IsNewsBlackout()
{
    if(!InpNewsFilter) return false;

    datetime utcNow = TimeGMT();
    MqlDateTime t;
    TimeToStruct(utcNow, t);

    int nowMin   = t.hour * 60 + t.min;
    int startMin = InpNewsBlockStartH * 60 + InpNewsBlockStartM;
    int endMin   = InpNewsBlockEndH   * 60 + InpNewsBlockEndM;

    return (nowMin >= startMin && nowMin < endMin);
}

//+------------------------------------------------------------------+
//| Draw a white entry arrow at the traded level                     |
//+------------------------------------------------------------------+
void DrawEntryArrow(double level, bool isLong, ulong ticket)
{
    string name = StringFormat("GR_arrow_%llu", ticket);
    ENUM_OBJECT objType = isLong ? OBJ_ARROW_BUY : OBJ_ARROW_SELL;

    ObjectCreate(0, name, objType, 0, TimeCurrent(), level);
    ObjectSetInteger(0, name, OBJPROP_COLOR,      clrWhite);
    ObjectSetInteger(0, name, OBJPROP_WIDTH,      2);
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
    ObjectSetString (0, name, OBJPROP_TOOLTIP,
                     StringFormat("%s @ %.0f", isLong ? "LONG" : "SHORT", level));
    ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| Delete all entry arrows                                          |
//+------------------------------------------------------------------+
void DeleteTradeArrows()
{
    int total = ObjectsTotal(0);
    for(int i = total - 1; i >= 0; i--)
    {
        string name = ObjectName(0, i);
        if(StringFind(name, "GR_arrow_") == 0)
            ObjectDelete(0, name);
    }
}

//+------------------------------------------------------------------+
//| Sum floating P&L of all EA positions                             |
//+------------------------------------------------------------------+
double TotalFloatingPL()
{
    double total = 0.0;
    for(int i = PositionsTotal() - 1; i >= 0; i--)
    {
        if(PositionSelectByTicket(PositionGetTicket(i)))
        {
            if(PositionGetInteger(POSITION_MAGIC) == InpMagicNumber &&
               PositionGetString(POSITION_SYMBOL) == _Symbol)
                total += PositionGetDouble(POSITION_PROFIT);
        }
    }
    return total;
}

//+------------------------------------------------------------------+
//| Close all EA trades on this symbol                               |
//+------------------------------------------------------------------+
void CloseAllTrades()
{
    for(int i = PositionsTotal() - 1; i >= 0; i--)
    {
        ulong ticket = PositionGetTicket(i);
        if(PositionSelectByTicket(ticket))
        {
            if(PositionGetInteger(POSITION_MAGIC) == InpMagicNumber &&
               PositionGetString(POSITION_SYMBOL) == _Symbol)
                g_trade.PositionClose(ticket);
        }
    }
    ResetEnteredLevels();
}

//+------------------------------------------------------------------+
//| Count open EA trades                                             |
//+------------------------------------------------------------------+
int CountOpenTrades()
{
    int cnt = 0;
    for(int i = PositionsTotal() - 1; i >= 0; i--)
    {
        if(PositionSelectByTicket(PositionGetTicket(i)))
        {
            if(PositionGetInteger(POSITION_MAGIC) == InpMagicNumber &&
               PositionGetString(POSITION_SYMBOL) == _Symbol)
                cnt++;
        }
    }
    return cnt;
}

//+------------------------------------------------------------------+
//| True if an open trade already sits at this level                 |
//+------------------------------------------------------------------+
bool LevelHasOpenTrade(double level)
{
    double tol = InpLevelTolerance * _Point;
    for(int i = PositionsTotal() - 1; i >= 0; i--)
    {
        if(PositionSelectByTicket(PositionGetTicket(i)))
        {
            if(PositionGetInteger(POSITION_MAGIC) == InpMagicNumber &&
               PositionGetString(POSITION_SYMBOL) == _Symbol)
            {
                if(MathAbs(PositionGetDouble(POSITION_PRICE_OPEN) - level) <= tol)
                    return true;
            }
        }
    }
    return false;
}

//+------------------------------------------------------------------+
//| Level-entered tracking                                           |
//+------------------------------------------------------------------+
void ResetEnteredLevels()
{
    ArrayResize(g_enteredLevels, 0);
    g_enteredCnt = 0;
}

bool HasEnteredLevel(double level)
{
    double tol = InpLevelTolerance * _Point;
    for(int i = 0; i < g_enteredCnt; i++)
        if(MathAbs(g_enteredLevels[i] - level) <= tol) return true;
    return false;
}

void MarkLevelEntered(double level)
{
    ArrayResize(g_enteredLevels, g_enteredCnt + 1);
    g_enteredLevels[g_enteredCnt++] = level;
}

//+------------------------------------------------------------------+
//| Reset all day-state variables                                    |
//+------------------------------------------------------------------+
void ResetDayState()
{
    ResetEnteredLevels();
    g_dayTradingDone    = false;
    g_dayHadDrawdown    = false;
    g_tradesOpenedToday = 0;
    g_firstTradeTicket  = 0;
    g_firstTradeEntry   = 0.0;
    g_firstTradeTime    = 0;
    g_firstTradeOpen    = false;
}

//+------------------------------------------------------------------+
//| Time filter: period slots + ICT sessions                         |
//+------------------------------------------------------------------+
bool IsAllowedTime()
{
    if(!InpUsePeriodFilter && !InpUseSessionFilter) return true;

    datetime utcNow = TimeGMT();
    MqlDateTime t;
    TimeToStruct(utcNow, t);
    int slot = t.hour * 2 + (t.min / 30);

    if(InpUsePeriodFilter && g_periodCnt > 0)
    {
        bool found = false;
        for(int i = 0; i < g_periodCnt; i++)
            if(g_periods[i] == slot) { found = true; break; }
        if(!found) return false;
    }

    if(InpUseSessionFilter)
    {
        bool inAsian  = InpTradeAsian  && IsInWindow(t.hour, 22, 9);
        bool inLondon = InpTradeLondon && IsInWindow(t.hour, 7,  16);
        bool inNY     = InpTradeNY     && IsInWindow(t.hour, 12, 21);
        if(!inAsian && !inLondon && !inNY) return false;
    }

    return true;
}

bool IsInWindow(int hour, int start, int end)
{
    if(start > end) return (hour >= start || hour < end);
    return (hour >= start && hour < end);
}

//+------------------------------------------------------------------+
//| Parse comma-separated period string                              |
//+------------------------------------------------------------------+
int ParsePeriods(const string src, int &out[])
{
    if(StringLen(src) == 0) return 0;

    string parts[];
    int cnt = StringSplit(src, ',', parts);
    ArrayResize(out, cnt);
    int valid = 0;
    for(int i = 0; i < cnt; i++)
    {
        StringTrimLeft(parts[i]);
        StringTrimRight(parts[i]);
        int slot = (int)StringToInteger(parts[i]);
        if(slot >= 0 && slot <= 47)
            out[valid++] = slot;
    }
    ArrayResize(out, valid);
    return valid;
}

//+------------------------------------------------------------------+
//| Draw horizontal grid lines                                       |
//+------------------------------------------------------------------+
void DrawGrid(double centerPrice)
{
    DeleteGridObjects();

    double base  = MathRound(centerPrice / InpGridStep) * InpGridStep;
    int    start = -InpLevelsBelow;
    int    end   =  InpLevelsAbove;

    for(int i = start; i <= end; i++)
    {
        double lvl  = base + i * InpGridStep;
        string name = StringFormat("GR_level_%d", (int)lvl);

        bool isMajor = ((int)MathRound(lvl) % InpMajorStep == 0);
        bool isMid   = (!isMajor && (int)MathRound(lvl) % InpMidStep == 0);

        color clr   = isMajor ? InpMajorColor : (isMid ? InpMidColor   : InpMinorColor);
        int   width = isMajor ? InpMajorWidth : (isMid ? InpMidWidth   : InpMinorWidth);
        int   style = isMajor ? STYLE_SOLID   : (isMid ? STYLE_DASH    : STYLE_DOT);

        ObjectCreate(0, name, OBJ_HLINE, 0, 0, lvl);
        ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
        ObjectSetInteger(0, name, OBJPROP_WIDTH,      width);
        ObjectSetInteger(0, name, OBJPROP_STYLE,      style);
        ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
        ObjectSetInteger(0, name, OBJPROP_HIDDEN,     true);

        string label = isMajor ? " MAJOR" : (isMid ? " MID" : "");
        if(StringLen(label) > 0)
            ObjectSetString(0, name, OBJPROP_TOOLTIP,
                            StringFormat("%.0f%s", lvl, label));
    }
    ChartRedraw(0);
}

void DeleteGridObjects()
{
    int total = ObjectsTotal(0);
    for(int i = total - 1; i >= 0; i--)
    {
        string name = ObjectName(0, i);
        if(StringFind(name, "GR_level_") == 0)
            ObjectDelete(0, name);
    }
}

//+------------------------------------------------------------------+
//| Dashboard                                                        |
//+------------------------------------------------------------------+
void ShowDashboard()
{
    double bid     = SymbolInfoDouble(_Symbol, SYMBOL_BID);
    double balance = AccountInfoDouble(ACCOUNT_BALANCE);
    double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
    double floatPL = TotalFloatingPL();
    int    openCnt = CountOpenTrades();

    datetime utcNow = TimeGMT();
    MqlDateTime t;
    TimeToStruct(utcNow, t);
    int slot = t.hour * 2 + (t.min / 30);

    string session = GetSessionName(t.hour);
    string biasStr = (InpBias == BIAS_LONG) ? "LONG" :
                     (InpBias == BIAS_SHORT) ? "SHORT" :
                     (InpBias == BIAS_BOTH)  ? "BOTH" : "NONE";

    double nearestAbove = MathCeil (bid / InpGridStep) * InpGridStep;
    double nearestBelow = MathFloor(bid / InpGridStep) * InpGridStep;

    // Day state
    string dayStatus = g_dayTradingDone ? "DONE — no new entries" : "ACTIVE";
    if(IsNewsBlackout()) dayStatus = "NEWS BLACKOUT";

    // Loss limit line
    string lossInfo = "";
    if(InpLossLimitPct > 0)
        lossInfo += StringFormat("Loss limit : %.1f%% ($%.2f)\n",
                                 InpLossLimitPct, balance * InpLossLimitPct / 100.0);
    if(InpLossLimitUSD > 0)
        lossInfo += StringFormat("Loss limit : $%.2f\n", InpLossLimitUSD);
    if(InpExitLevel > 0)
        lossInfo += StringFormat("Exit level : %.0f\n", InpExitLevel);

    // APP / SAPP / T1-BE lines (only when ≥2 trades open)
    string beInfo = "";
    STradeInfo trades[];
    int  cnt = 0; bool allLong = true;
    if(CollectTrades(trades, cnt, allLong))
    {
        double app, sapp, t1Entry;
        CalcBreakEvenLevels(trades, cnt, app, sapp, t1Entry);
        beInfo = StringFormat(
            "T1 entry   : %.0f  (T1-BE / net profit)\n"
            "APP        : %.0f  (all trades net zero)\n"
            "SAPP       : %.0f  (T1 loss, T2+ zero)\n",
            t1Entry, app, sapp);
    }

    string periodInfo = InpUsePeriodFilter
        ? StringFormat("Period filter: ON  (slot %d / 47)", slot)
        : StringFormat("Period filter: OFF (slot %d / 47 — %s)", slot, session);

    Comment(
        "═══════════════════════════════════\n",
        "  GRID REID  v1.1    |  ", _Symbol, "\n",
        "═══════════════════════════════════\n",
        StringFormat("  Price    : %.0f\n", bid),
        StringFormat("  Bias     : %s  |  Move: %d pts\n", biasStr, InpExpectedMove),
        StringFormat("  Grid step: %d pts\n", InpGridStep),
        "───────────────────────────────────\n",
        StringFormat("  Level above : %.0f  (+%.0f pts)\n", nearestAbove, nearestAbove - bid),
        StringFormat("  Level below : %.0f  (-%.0f pts)\n", nearestBelow, bid - nearestBelow),
        "───────────────────────────────────\n",
        StringFormat("  Open trades : %d / %d  (today: %d)\n", openCnt, InpMaxTrades, g_tradesOpenedToday),
        StringFormat("  Float P&L   : %.2f\n", floatPL),
        StringFormat("  Balance     : %.2f    Equity: %.2f\n", balance, equity),
        "───────────────────────────────────\n",
        beInfo,
        lossInfo,
        StringFormat("  Day status : %s\n", dayStatus),
        periodInfo, "\n",
        StringFormat("  Session  : %s\n", session),
        "═══════════════════════════════════"
    );
}

//+------------------------------------------------------------------+
//| Return active ICT session name for a UTC hour                    |
//+------------------------------------------------------------------+
string GetSessionName(int hour)
{
    string parts = "";
    if(IsInWindow(hour, 22, 9))  parts += "Asian/";
    if(IsInWindow(hour, 7, 16))  parts += "London/";
    if(IsInWindow(hour, 12, 21)) parts += "NY/";
    if(StringLen(parts) == 0) return "Off-session";
    return StringSubstr(parts, 0, StringLen(parts) - 1);
}
