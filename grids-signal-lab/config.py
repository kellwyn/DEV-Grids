"""
Signal Lab — instrument and strategy configuration for GridReid.
US30 (Dow Jones Industrial Average) defaults.
"""

from dataclasses import dataclass, field
from typing import List

DURATIONS: dict[str, int] = {
    "1W":  7,
    "1M":  30,
    "3M":  90,
    "6M":  180,
    "1Y":  365,
    "2Y":  730,
}

DURATION_LABELS = list(DURATIONS.keys())


@dataclass
class LabConfig:
    # ── Instrument ────────────────────────────────────────────────────────────
    symbol:       str = "US30"
    analysis_tf:  str = "M30"   # 48 × 30-min slots per 24h

    # ── Grid geometry ─────────────────────────────────────────────────────────
    grid_step:    int   = 50     # points between trading levels
    major_step:   int   = 1000   # major level spacing
    mid_step:     int   = 250    # mid level spacing
    tolerance:    float = 15.0   # touch tolerance in points

    # ── Strategy parameters ───────────────────────────────────────────────────
    bias:          str  = "LONG"  # default bias for historical analysis
    expected_move: int  = 350     # typical daily range in points

    # ── ICT session hours (UTC) ───────────────────────────────────────────────
    # US30 relevant sessions
    asian_start_h:  int = 22   # 22:00 UTC = Tokyo pre-session
    asian_end_h:    int = 9    # 09:00 UTC = Tokyo close
    london_start_h: int = 7    # 07:00 UTC = London open
    london_end_h:   int = 16   # 16:00 UTC = London close
    ny_start_h:     int = 12   # 12:00 UTC ≈ 1hr before NYSE open
    ny_end_h:       int = 21   # 21:00 UTC = NYSE close

    # ── US30 RTH window ───────────────────────────────────────────────────────
    # NYSE Regular Trading Hours: 09:30–16:00 ET = 14:30–21:00 UTC
    use_rth:     bool = False
    rth_start_h: int  = 14
    rth_start_m: int  = 30
    rth_end_h:   int  = 21
    rth_end_m:   int  = 0

    # ── Candle classification ─────────────────────────────────────────────────
    big_move_pct:    float = 0.3   # bar body >= this % of price = big-move candle (US30 ~0.3%)
    tight_range_pct: float = 0.05  # bar H-L / price < this % = tight/doji candle

    # ── Indicator periods ─────────────────────────────────────────────────────
    rsi_period:    int = 14
    atr_period:    int = 14
    vol_ma_period: int = 20

    # ── Market correlation assets ─────────────────────────────────────────────
    # Symbols used in yfinance for correlation analysis
    corr_assets: List[str] = field(default_factory=lambda: [
        "^DJI",      # Dow Jones itself (benchmark)
        "DX-Y.NYB",  # US Dollar Index (inverse correlation)
        "^VIX",      # Volatility Index (inverse)
        "^TNX",      # 10-Year Treasury Yield
        "^GSPC",     # S&P 500 (positive correlation)
        "GC=F",      # Gold futures (safe-haven flow)
        "CL=F",      # Crude Oil (risk-on signal)
    ])

    # ── TP/outcome analysis ───────────────────────────────────────────────────
    tp_lookahead_bars: int = 50   # max bars to look forward for TP/SL hit
