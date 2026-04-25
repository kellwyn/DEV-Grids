"""
GridReid Signal Lab — Market Correlations

Computes rolling correlations between US30 and key macro assets:
  - DXY (US Dollar Index) — historically inverse to US30
  - VIX (Fear gauge)      — typically inverse: high VIX = sell-off
  - TNX (10Y Yield)       — mixed: rising yields can weigh on equities
  - SPX (S&P 500)         — strong positive correlation
  - Gold (GC=F)           — risk-off proxy, mixed vs US30
  - Crude Oil (CL=F)      — risk-on signal, generally positive

Data source: yfinance (free, no API key needed).
Falls back gracefully if yfinance is not installed or data unavailable.

Why this matters for the grid strategy:
  - Strong inverse DXY correlation: if DXY is ripping higher, US30 grid
    entries from the LONG side have lower win probability.
  - Elevated VIX: more volatility, levels more likely to be blown through.
  - Watch TNX: when yields spike sharply, US30 often drops faster/further.
"""

from __future__ import annotations

from typing import Optional
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False


# ── Data fetch ────────────────────────────────────────────────────────────────

def _fetch_yf(ticker: str, days: int) -> Optional[pd.Series]:
    """Fetch daily close prices for a yfinance ticker."""
    if not _YF_AVAILABLE:
        return None
    try:
        end   = datetime.now()
        start = end - timedelta(days=days)
        data  = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if data.empty:
            return None
        return data["Close"].squeeze()
    except Exception:
        return None


def fetch_corr_data(assets: list[str], days: int = 180) -> pd.DataFrame:
    """
    Fetch daily close prices for all assets.
    Returns DataFrame with one column per asset (indexed by date).
    Missing assets are silently skipped.
    """
    frames = {}
    for ticker in assets:
        s = _fetch_yf(ticker, days)
        if s is not None and not s.empty:
            frames[ticker] = s

    if not frames:
        return pd.DataFrame()

    df = pd.DataFrame(frames)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df.ffill().dropna()
    return df


# ── Correlation analysis ──────────────────────────────────────────────────────

def compute_rolling_corr(df: pd.DataFrame, base: str = "^DJI",
                          window: int = 20) -> pd.DataFrame:
    """
    Compute rolling pairwise correlations of all assets vs the base (US30).
    Returns DataFrame of rolling correlations with one column per asset.
    """
    if df.empty or base not in df.columns:
        return pd.DataFrame()

    returns = df.pct_change().dropna()
    base_ret = returns[base]

    result = {}
    for col in returns.columns:
        if col == base:
            continue
        result[col] = base_ret.rolling(window).corr(returns[col])

    return pd.DataFrame(result, index=returns.index)


def correlation_summary(df: pd.DataFrame, base: str = "^DJI",
                         window: int = 20) -> pd.DataFrame:
    """
    Return a summary table: asset, current_corr, 30d_corr, 90d_corr, interpretation.
    """
    if df.empty or base not in df.columns:
        return pd.DataFrame()

    returns = df.pct_change().dropna()
    base_ret = returns[base]

    rows = []
    for col in returns.columns:
        if col == base:
            continue

        series = returns[col]
        curr   = base_ret.iloc[-window:].corr(series.iloc[-window:])   if len(series) >= window else np.nan
        r30    = base_ret.iloc[-30:].corr(series.iloc[-30:])            if len(series) >= 30 else np.nan
        r90    = base_ret.iloc[-90:].corr(series.iloc[-90:])            if len(series) >= 90 else np.nan

        rows.append({
            "asset":         col,
            "current_corr":  round(curr, 3) if not np.isnan(curr) else "N/A",
            "30d_corr":      round(r30,  3) if not np.isnan(r30)  else "N/A",
            "90d_corr":      round(r90,  3) if not np.isnan(r90)  else "N/A",
            "interpretation": _interpret_corr(col, curr),
        })

    return pd.DataFrame(rows)


def _interpret_corr(asset: str, corr: float) -> str:
    """Plain-language interpretation of the current correlation vs US30."""
    if np.isnan(corr):
        return "N/A"

    asset_notes = {
        "DX-Y.NYB": "DXY inverse — strong negative corr = normal; rising DXY = US30 headwind",
        "^VIX":     "VIX inverse — high corr toward 0 or positive = elevated fear = bearish for US30",
        "^TNX":     "10Y yield — positive corr means rising yields hurt equities",
        "^GSPC":    "SPX — near +1.0 is normal; divergence may signal rotation",
        "GC=F":     "Gold — negative corr = risk-on; positive = risk-off / flight to safety",
        "CL=F":     "Crude — positive corr = risk-on environment supporting US30",
    }

    strength = ("strong" if abs(corr) > 0.6 else
                "moderate" if abs(corr) > 0.3 else "weak")
    direction = "positive" if corr > 0 else "negative"
    base = f"{strength} {direction} ({corr:+.3f})"

    note = asset_notes.get(asset, "")
    return f"{base} — {note}" if note else base


# ── Volatility regime ─────────────────────────────────────────────────────────

def vix_regime(df: pd.DataFrame) -> dict:
    """
    Return current VIX level and risk interpretation for grid trading.
    Higher VIX → wider swings → levels more likely to be blown through.
    """
    if "^VIX" not in df.columns or df.empty:
        return {"vix": None, "regime": "unknown", "grid_impact": "unknown"}

    vix_now = float(df["^VIX"].iloc[-1])
    vix_30d = float(df["^VIX"].iloc[-30:].mean()) if len(df) >= 30 else vix_now

    if vix_now < 15:
        regime     = "LOW VOLATILITY"
        grid_impact = "Favourable — levels likely to hold; reversals more reliable"
    elif vix_now < 25:
        regime     = "MODERATE VOLATILITY"
        grid_impact = "Normal — standard grid approach, monitor closely"
    elif vix_now < 35:
        regime     = "HIGH VOLATILITY"
        grid_impact = "Caution — levels may be blown through; widen tolerance or reduce size"
    else:
        regime     = "EXTREME VOLATILITY (>35)"
        grid_impact = "Avoid grid strategy — momentum trades dominating; loss limits critical"

    return {
        "vix":        vix_now,
        "vix_30d_avg": vix_30d,
        "regime":     regime,
        "grid_impact": grid_impact,
    }


def dxy_bias(df: pd.DataFrame) -> dict:
    """Return DXY trend direction and its implication for US30 LONG/SHORT bias."""
    if "DX-Y.NYB" not in df.columns or df.empty:
        return {"dxy": None, "trend": "unknown", "us30_implication": "unknown"}

    dxy     = df["DX-Y.NYB"]
    now     = float(dxy.iloc[-1])
    ma20    = float(dxy.rolling(20).mean().iloc[-1]) if len(dxy) >= 20 else now
    ma5     = float(dxy.rolling(5).mean().iloc[-1])  if len(dxy) >= 5  else now

    trend = "RISING" if ma5 > ma20 else "FALLING"

    implication = (
        "Rising DXY historically pressures US30 — favour SHORT bias or reduce LONG sizes"
        if trend == "RISING" else
        "Falling DXY historically supports US30 — LONG bias has tailwind"
    )

    return {"dxy": round(now, 2), "ma20": round(ma20, 2),
            "trend": trend, "us30_implication": implication}
