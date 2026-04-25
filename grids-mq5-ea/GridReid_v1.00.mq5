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
//+------------------------------------------------------------------+

#property copyright "Grid Reid Strategy"
#property version   "1.00"
#property description "GridReid — US30 Psychological Level Grid Strategy v1.00"
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

//── Inputs ────────────────────────────────────────────────────────

input group "=== Grid Configuration ==="
input int    InpGridStep         = 50;         // Grid step in points (50 = 50 US30 points)
input int    InpMajorStep        = 1000;       // Major level spacing (solid lines)
input int    InpMidStep          = 250;        // Mid level spacing (dashed lines)
input int    InpLevelsAbove      = 12;         // Grid levels shown above current price
input int    InpLevelsBelow      = 12;         // Grid levels shown below current price
input double InpLevelTolerance   = 15.0;       // Touch tolerance in points

input group "=== Direction Bias ==="
input ENUM_GRID_BIAS InpBias     = BIAS_LONG;  // Daily trading bias
input int    InpExpectedMove     = 350;        // Expected daily range (points) — display context
input int    InpMaxTrades        = 5;          // Max simultaneous grid trades

input group "=== Exit Settings ==="
input int    InpTPPoints         = 50;         // TP distance in points (one grid step)
input int    InpSLPoints         = 0;          // SL distance in points (0 = use loss limit only)
input double InpMinRR            = 0.0;        // Minimum R:R ratio (0 = disabled)
input double InpLossLimitPct     = 5.0;        // Max floating loss as % of balance (0 = disabled)
input double InpLossLimitUSD     = 0.0;        // Max floating loss in $ (0 = disabled)
input double InpExitLevel        = 0.0;        // Physical exit price — point of no return (0 = disabled)

input group "=== Risk Management ==="
input double InpRiskPct          = 1.0;        // Risk % per trade (active when InpFixedLots = 0)
input double InpMaxLots          = 5.0;        // Max lot size cap
input double InpFixedLots        = 0.0;        // Fixed lots (0 = risk-based sizing)
input int    InpMagicNumber      = 20260426;   // EA magic number
input int    InpSlippage         = 20;         // Max slippage in points

input group "=== Period Filter (30-min UTC slots) ==="
input bool   InpUsePeriodFilter  = false;      // Enable 30-min period filter
input string InpAllowedPeriods   = "";         // Comma-separated slot indices 0-47
                                               // Slot 0=00:00  14=07:00  17=08:30  28=14:00  34=17:00 UTC

input group "=== ICT Session Filter ==="
input bool   InpUseSessionFilter = false;      // Enable ICT session filter
input bool   InpTradeAsian       = false;      // Trade Asian session  (22:00-09:00 UTC)
input bool   InpTradeLondon      = true;       // Trade London session (07:00-16:00 UTC)
input bool   InpTradeNY          = true;       // Trade NY session     (12:00-21:00 UTC)

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
datetime g_lastBar    = 0;

// Parsed period filter
int      g_periods[]  ;
int      g_periodCnt  = 0;

// Levels entered today (one trade per level per day)
double   g_enteredLevels[];
int      g_enteredCnt = 0;
int      g_lastDay    = -1;

//+------------------------------------------------------------------+
//| Init                                                             |
//+------------------------------------------------------------------+
int OnInit()
{
    g_trade.SetExpertMagicNumber(InpMagicNumber);
    g_trade.SetDeviationInPoints(InpSlippage);
    g_trade.SetTypeFilling(ORDER_FILLING_IOC);

    g_periodCnt = ParsePeriods(InpAllowedPeriods, g_periods);

    if(InpShowGrid)
        DrawGrid(SymbolInfoDouble(_Symbol, SYMBOL_BID));

    ResetEnteredLevels();

    Print("GridReid v1.00 | Bias=", EnumToString(InpBias),
          " | Step=", InpGridStep, "pts | MaxTrades=", InpMaxTrades);
    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Deinit                                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    DeleteGridObjects();
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

    // Enforce loss limits every tick
    CheckLossLimits(bid);

    // Gate on new bar
    datetime barTime = iTime(_Symbol, PERIOD_CURRENT, 0);
    if(barTime == g_lastBar)
    {
        ShowDashboard();
        return;
    }
    g_lastBar = barTime;

    // Reset entered levels at day boundary
    MqlDateTime dt;
    TimeToStruct(barTime, dt);
    if(dt.day != g_lastDay)
    {
        ResetEnteredLevels();
        g_lastDay = dt.day;
    }

    // Check time filters before seeking entries
    if(!IsAllowedTime())
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

    // Use the most-recently COMPLETED bar (index 1)
    double barHigh  = iHigh(_Symbol,  PERIOD_CURRENT, 1);
    double barLow   = iLow(_Symbol,   PERIOD_CURRENT, 1);
    double barClose = iClose(_Symbol,  PERIOD_CURRENT, 1);
    double barOpen  = iOpen(_Symbol,   PERIOD_CURRENT, 1);
    double prevClose= iClose(_Symbol,  PERIOD_CURRENT, 2);

    double tol = InpLevelTolerance * _Point;

    // Collect all grid levels touched by this bar
    double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
    double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

    int    levelCount = 0;
    double touchedLevels[];
    bool   touchedFromAbove[];   // true = bar LOW touched level (price came down)
    bool   touchedFromBelow[];   // true = bar HIGH touched level (price came up)

    // Scan levels across bar's range
    double startLevel = MathFloor(barLow  / InpGridStep) * InpGridStep - InpGridStep;
    double endLevel   = MathCeil(barHigh  / InpGridStep) * InpGridStep + InpGridStep;

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

        if(HasEnteredLevel(lvl))  continue;
        if(LevelHasOpenTrade(lvl)) continue;

        bool canLong  = (InpBias == BIAS_LONG  || InpBias == BIAS_BOTH);
        bool canShort = (InpBias == BIAS_SHORT || InpBias == BIAS_BOTH);

        bool entered = false;

        // LONG: price came DOWN to this level — buy the dip
        if(canLong && touchedFromAbove[i])
        {
            if(OpenLong(lvl, ask))
                entered = true;
        }

        // SHORT: price came UP to this level — sell the rally
        if(!entered && canShort && touchedFromBelow[i])
        {
            if(OpenShort(lvl, bid))
                entered = true;
        }

        if(entered)
        {
            MarkLevelEntered(lvl);
            openCnt++;
            if(openCnt >= InpMaxTrades) break;
        }
    }
}

//+------------------------------------------------------------------+
//| Open a LONG (buy) trade at a grid level                         |
//+------------------------------------------------------------------+
bool OpenLong(double level, double askPrice)
{
    double tp = level + InpTPPoints * _Point;
    double sl = (InpSLPoints > 0) ? level - InpSLPoints * _Point : 0.0;

    // R:R check (only if SL is set)
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
    if(!ok)
        Print("OPEN LONG failed level=", level, " err=", g_trade.ResultRetcode(),
              " ", g_trade.ResultRetcodeDescription());
    return ok;
}

//+------------------------------------------------------------------+
//| Open a SHORT (sell) trade at a grid level                       |
//+------------------------------------------------------------------+
bool OpenShort(double level, double bidPrice)
{
    double tp = level - InpTPPoints * _Point;
    double sl = (InpSLPoints > 0) ? level + InpSLPoints * _Point : 0.0;

    // R:R check
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
    if(!ok)
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
        // No SL: size based on 1 grid step risk
        sl = (InpBias == BIAS_SHORT)
             ? entry + InpGridStep * _Point
             : entry - InpGridStep * _Point;
    }

    double balance    = AccountInfoDouble(ACCOUNT_BALANCE);
    double riskAmt    = balance * InpRiskPct / 100.0;
    double slDist     = MathAbs(entry - sl);
    if(slDist <= 0) return SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);

    double tickVal  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
    double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
    if(tickVal <= 0 || tickSize <= 0) return SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);

    double valPerPt = tickVal / tickSize;
    double lots     = riskAmt / (slDist * valPerPt);

    return NormaliseLots(lots);
}

//+------------------------------------------------------------------+
//| Clamp lots to broker limits and InpMaxLots                      |
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
//| Check loss limits — close all trades if breached                 |
//+------------------------------------------------------------------+
void CheckLossLimits(double bid)
{
    double floatPL = TotalFloatingPL();
    bool   close   = false;

    // % of balance
    if(InpLossLimitPct > 0.0)
    {
        double balance = AccountInfoDouble(ACCOUNT_BALANCE);
        if(balance > 0 && floatPL < -(balance * InpLossLimitPct / 100.0))
        {
            Print("LOSS LIMIT PCT hit: floatPL=", floatPL,
                  " limit=", -(balance * InpLossLimitPct / 100.0));
            close = true;
        }
    }

    // $ amount
    if(!close && InpLossLimitUSD > 0.0 && floatPL < -InpLossLimitUSD)
    {
        Print("LOSS LIMIT USD hit: floatPL=", floatPL, " limit=-", InpLossLimitUSD);
        close = true;
    }

    // Physical exit level
    if(!close && InpExitLevel > 0.0)
    {
        if(InpBias == BIAS_LONG && bid < InpExitLevel)
        {
            Print("EXIT LEVEL breached (LONG): price=", bid, " exitLevel=", InpExitLevel);
            close = true;
        }
        if(InpBias == BIAS_SHORT && bid > InpExitLevel)
        {
            Print("EXIT LEVEL breached (SHORT): price=", bid, " exitLevel=", InpExitLevel);
            close = true;
        }
    }

    if(close) CloseAllTrades();
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
            {
                g_trade.PositionClose(ticket);
            }
        }
    }
    ResetEnteredLevels();
}

//+------------------------------------------------------------------+
//| Count open EA trades on this symbol                              |
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
//| True if an open EA trade is already at this level (within tol)  |
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
                double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
                if(MathAbs(openPrice - level) <= tol) return true;
            }
        }
    }
    return false;
}

//+------------------------------------------------------------------+
//| Entered-level tracking (one entry per level per day)            |
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
    g_enteredLevels[g_enteredCnt] = level;
    g_enteredCnt++;
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
//| Parse comma-separated period string into array                   |
//| e.g. "14,15,16,28" → [14, 15, 16, 28]                          |
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
//| Draw horizontal grid lines on the chart                          |
//+------------------------------------------------------------------+
void DrawGrid(double centerPrice)
{
    DeleteGridObjects();

    double base  = MathRound(centerPrice / InpGridStep) * InpGridStep;
    int    start = -InpLevelsBelow;
    int    end   =  InpLevelsAbove;

    for(int i = start; i <= end; i++)
    {
        double lvl = base + i * InpGridStep;
        string name = StringFormat("GR_level_%d", (int)lvl);

        bool   isMajor = ((int)MathRound(lvl) % InpMajorStep == 0);
        bool   isMid   = (!isMajor && (int)MathRound(lvl) % InpMidStep == 0);

        color  clr   = isMajor ? InpMajorColor : (isMid ? InpMidColor : InpMinorColor);
        int    width = isMajor ? InpMajorWidth : (isMid ? InpMidWidth  : InpMinorWidth);
        int    style = isMajor ? STYLE_SOLID   : (isMid ? STYLE_DASH   : STYLE_DOT);

        ObjectCreate(0, name, OBJ_HLINE, 0, 0, lvl);
        ObjectSetInteger(0, name, OBJPROP_COLOR,  clr);
        ObjectSetInteger(0, name, OBJPROP_WIDTH,  width);
        ObjectSetInteger(0, name, OBJPROP_STYLE,  style);
        ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
        ObjectSetInteger(0, name, OBJPROP_HIDDEN,     true);

        // Label the level type
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
//| Dashboard — displayed in chart comment                            |
//+------------------------------------------------------------------+
void ShowDashboard()
{
    double bid      = SymbolInfoDouble(_Symbol, SYMBOL_BID);
    double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
    double equity   = AccountInfoDouble(ACCOUNT_EQUITY);
    double floatPL  = TotalFloatingPL();
    int    openCnt  = CountOpenTrades();

    datetime utcNow = TimeGMT();
    MqlDateTime t;
    TimeToStruct(utcNow, t);
    int slot = t.hour * 2 + (t.min / 30);

    string session = GetSessionName(t.hour);
    string biasStr = (InpBias == BIAS_LONG) ? "LONG" :
                     (InpBias == BIAS_SHORT) ? "SHORT" :
                     (InpBias == BIAS_BOTH)  ? "BOTH" : "NONE";

    // Nearest levels
    double nearestAbove = MathCeil(bid  / InpGridStep) * InpGridStep;
    double nearestBelow = MathFloor(bid / InpGridStep) * InpGridStep;
    double distAbove    = nearestAbove - bid;
    double distBelow    = bid - nearestBelow;

    string lossInfo = "";
    if(InpLossLimitPct > 0)
        lossInfo += StringFormat("Loss limit: %.1f%% (%.2f $)\n",
                                 InpLossLimitPct, balance * InpLossLimitPct / 100.0);
    if(InpLossLimitUSD > 0)
        lossInfo += StringFormat("Loss limit: $%.2f\n", InpLossLimitUSD);
    if(InpExitLevel > 0)
        lossInfo += StringFormat("Exit level: %.0f\n", InpExitLevel);

    string periodInfo = InpUsePeriodFilter
        ? StringFormat("Period filter: ON  (slot %d / 47)", slot)
        : StringFormat("Period filter: OFF (slot %d / 47 — %s)", slot, session);

    Comment(
        "═══════════════════════════════════\n",
        "  GRID REID  v1.00   |  ", _Symbol, "\n",
        "═══════════════════════════════════\n",
        StringFormat("  Price    : %.0f\n", bid),
        StringFormat("  Bias     : %s  |  Expected move: %d pts\n", biasStr, InpExpectedMove),
        StringFormat("  Grid step: %d pts\n", InpGridStep),
        "───────────────────────────────────\n",
        StringFormat("  Level above : %.0f  (+%.0f pts)\n", nearestAbove, distAbove),
        StringFormat("  Level below : %.0f  (-%.0f pts)\n", nearestBelow, distBelow),
        "───────────────────────────────────\n",
        StringFormat("  Open trades : %d / %d\n", openCnt, InpMaxTrades),
        StringFormat("  Float P&L   : %.2f\n", floatPL),
        StringFormat("  Balance     : %.2f    Equity: %.2f\n", balance, equity),
        "───────────────────────────────────\n",
        lossInfo,
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
