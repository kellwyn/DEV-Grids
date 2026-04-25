"""
GridReid Signal Lab — Economic Calendar & Fundamental Context

Tracks high-impact USD/US30 events and their expected market behaviour.
Grid trading is riskiest around high-impact news releases because:
  - Price can break straight through levels without reversing
  - Spreads widen significantly at brokers
  - Momentum can override the psychological level magnetism

Recommended behaviour:
  - Pause new grid entries 30 min BEFORE and 15 min AFTER high-impact news
  - Check this module before each session to see upcoming events
  - After NFP / FOMC: wait for first 30-min candle to close before resuming

Data sources (in priority order):
  1. Live: investing.com economic calendar (via scraping) — if requests available
  2. Reference: static schedule of recurring monthly/weekly events
  3. Manual: user can log events in memory/episodic_grids.md

US30 sensitivity by event (impact on grid win rate):
  HIGH IMPACT  — avoid new entries ±30 min:
    NFP         (First Friday of month, 13:30 UTC)
    FOMC        (8× per year, statement 19:00-20:00 UTC)
    CPI         (Monthly, 13:30 UTC)
    GDP         (Quarterly advance, 13:30 UTC)
    PCE         (Monthly, 13:30 UTC)

  MODERATE IMPACT — reduce size, widen tolerance:
    ADP Payrolls  (Wednesday before NFP, 13:15 UTC)
    ISM Mfg PMI   (First business day of month, 15:00 UTC)
    ISM Services  (Third business day, 15:00 UTC)
    Retail Sales  (Monthly, 13:30 UTC)
    PPI           (Monthly, 13:30 UTC)
    Fed Speeches  (Hawkish = USD up, bearish for US30)

  LOW IMPACT — monitor, no size change:
    Jobless Claims   (Thursday, 13:30 UTC)
    Consumer Conf.   (Last Tuesday, 15:00 UTC)
    Housing Data     (varies, 15:00 UTC)
    JOLTS            (Monthly, 15:00 UTC)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import calendar

try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False


# ── Event data model ──────────────────────────────────────────────────────────

@dataclass
class EconomicEvent:
    name:        str
    impact:      str              # "HIGH" | "MODERATE" | "LOW"
    time_utc:    str              # "13:30" or "varies"
    frequency:   str              # "Monthly" | "8×/year" | "Weekly" etc.
    schedule:    str              # human-readable schedule description
    us30_effect: str              # expected US30 reaction
    grid_action: str              # what to do with the grid
    avoid_window_min: int = 30    # minutes before/after to pause new entries


# ── Static event reference table ──────────────────────────────────────────────

HIGH_IMPACT_EVENTS: list[EconomicEvent] = [
    EconomicEvent(
        name="Non-Farm Payrolls (NFP)",
        impact="HIGH",
        time_utc="13:30",
        frequency="Monthly",
        schedule="First Friday of each month",
        us30_effect=(
            "Strong NFP = USD up, rate-hike fears = US30 sells off initially then recovers.\n"
            "Weak NFP = USD down, rate-cut hopes = US30 rallies."
        ),
        grid_action="PAUSE all entries 30 min before and 15 min after. Wait for first 30-min bar close.",
        avoid_window_min=30,
    ),
    EconomicEvent(
        name="FOMC Meeting Statement",
        impact="HIGH",
        time_utc="19:00",
        frequency="8× per year",
        schedule="Jan, Mar, May, Jun, Jul, Sep, Nov, Dec (approx)",
        us30_effect=(
            "Hawkish surprise (rate hike / hawkish tone) = US30 sharp drop.\n"
            "Dovish surprise (rate cut / pause) = US30 sharp rally.\n"
            "Volatility extreme — multi-hundred-point swings within 30 min."
        ),
        grid_action="PAUSE all entries 60 min before. Resume only after 30-min candle closes post-announcement.",
        avoid_window_min=60,
    ),
    EconomicEvent(
        name="Consumer Price Index (CPI)",
        impact="HIGH",
        time_utc="13:30",
        frequency="Monthly",
        schedule="~12th of each month (varies ±3 days)",
        us30_effect=(
            "Hot CPI = rate-hike fears = US30 drop.\n"
            "Cool CPI = disinflation narrative = US30 rally."
        ),
        grid_action="PAUSE entries 30 min before. Resume after 13:45 UTC bar close.",
        avoid_window_min=30,
    ),
    EconomicEvent(
        name="GDP (Advance / Preliminary)",
        impact="HIGH",
        time_utc="13:30",
        frequency="Quarterly",
        schedule="Late January, April, July, October",
        us30_effect="Miss = risk-off = US30 drops. Beat = US30 rallies.",
        grid_action="PAUSE entries 30 min before.",
        avoid_window_min=30,
    ),
    EconomicEvent(
        name="Core PCE Price Index",
        impact="HIGH",
        time_utc="13:30",
        frequency="Monthly",
        schedule="Last Friday of each month",
        us30_effect="Fed's preferred inflation gauge. Same direction as CPI impact.",
        grid_action="PAUSE entries 30 min before.",
        avoid_window_min=30,
    ),
]

MODERATE_IMPACT_EVENTS: list[EconomicEvent] = [
    EconomicEvent(
        name="ADP National Employment",
        impact="MODERATE",
        time_utc="13:15",
        frequency="Monthly",
        schedule="Wednesday before NFP Friday",
        us30_effect="Pre-cursor to NFP. Strong ADP = NFP optimism = modest US30 move.",
        grid_action="Reduce new entries to 50% size 15 min before and after.",
        avoid_window_min=15,
    ),
    EconomicEvent(
        name="ISM Manufacturing PMI",
        impact="MODERATE",
        time_utc="15:00",
        frequency="Monthly",
        schedule="First business day of each month",
        us30_effect="<50 = contraction = US30 negative. >50 = expansion = positive.",
        grid_action="Monitor. Reduce size if significantly off consensus.",
        avoid_window_min=15,
    ),
    EconomicEvent(
        name="ISM Services PMI",
        impact="MODERATE",
        time_utc="15:00",
        frequency="Monthly",
        schedule="Third business day of each month",
        us30_effect="Services dominate the US economy. Miss = US30 negative.",
        grid_action="Monitor. Reduce size if significantly off consensus.",
        avoid_window_min=15,
    ),
    EconomicEvent(
        name="Retail Sales",
        impact="MODERATE",
        time_utc="13:30",
        frequency="Monthly",
        schedule="~15th of each month",
        us30_effect="Consumer spending proxy. Strong = US30 positive.",
        grid_action="Monitor only. No size change required.",
        avoid_window_min=0,
    ),
    EconomicEvent(
        name="Fed Chair / FOMC Member Speech",
        impact="MODERATE",
        time_utc="varies",
        frequency="Frequent",
        schedule="Check Fed calendar at federalreserve.gov",
        us30_effect="Hawkish tone = USD up, US30 down. Dovish = opposite.",
        grid_action="If scheduled during active trading, monitor tone in real-time.",
        avoid_window_min=0,
    ),
    EconomicEvent(
        name="Producer Price Index (PPI)",
        impact="MODERATE",
        time_utc="13:30",
        frequency="Monthly",
        schedule="~10th of each month",
        us30_effect="Leading indicator for CPI. Hot = rate fears = US30 negative.",
        grid_action="Monitor only.",
        avoid_window_min=0,
    ),
]

LOW_IMPACT_EVENTS: list[EconomicEvent] = [
    EconomicEvent(
        name="Initial Jobless Claims",
        impact="LOW",
        time_utc="13:30",
        frequency="Weekly",
        schedule="Every Thursday",
        us30_effect="Spike in claims = labour market weakening = mixed US30 reaction.",
        grid_action="No action required. Note if >300K (significant miss).",
        avoid_window_min=0,
    ),
    EconomicEvent(
        name="CB Consumer Confidence",
        impact="LOW",
        time_utc="15:00",
        frequency="Monthly",
        schedule="Last Tuesday of each month",
        us30_effect="Sentiment leading indicator. Large miss = US30 sells.",
        grid_action="No action required.",
        avoid_window_min=0,
    ),
    EconomicEvent(
        name="JOLTS Job Openings",
        impact="LOW",
        time_utc="15:00",
        frequency="Monthly",
        schedule="~First week of month, 5-6 weeks after reference month",
        us30_effect="Labour demand proxy. Declining openings = softening = bearish.",
        grid_action="No action required.",
        avoid_window_min=0,
    ),
]

ALL_EVENTS = HIGH_IMPACT_EVENTS + MODERATE_IMPACT_EVENTS + LOW_IMPACT_EVENTS


# ── Calendar display ──────────────────────────────────────────────────────────

def print_calendar():
    """Print the US30 economic event reference table to the console."""
    sep = "─" * 72
    now = datetime.now(timezone.utc)

    print(f"\n{sep}")
    print(f"  US30 ECONOMIC CALENDAR REFERENCE  |  {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(sep)
    print(f"  {'Event':<35}  {'Impact':<10}  {'Time UTC':<10}  {'Schedule'}")
    print(sep)

    for ev in HIGH_IMPACT_EVENTS:
        print(f"  {ev.name:<35}  \033[91m{ev.impact:<10}\033[0m  {ev.time_utc:<10}  {ev.schedule}")

    print()
    for ev in MODERATE_IMPACT_EVENTS:
        print(f"  {ev.name:<35}  \033[93m{ev.impact:<10}\033[0m  {ev.time_utc:<10}  {ev.schedule}")

    print()
    for ev in LOW_IMPACT_EVENTS:
        print(f"  {ev.name:<35}  {ev.impact:<10}  {ev.time_utc:<10}  {ev.schedule}")

    print(f"\n{sep}")
    print("  GRID TRADING RULES DURING HIGH-IMPACT EVENTS:")
    print(f"  · Pause NEW entries for ±30 min around HIGH impact releases")
    print(f"  · FOMC: pause ±60 min. Wait for first 30-min bar after release.")
    print(f"  · Existing open trades: let them ride (TP/loss-limit handles them)")
    print(f"  · After spike: resume only when level-touch pattern re-establishes")
    print(sep)


def get_high_impact_today() -> list[EconomicEvent]:
    """
    Return list of high-impact events that typically fall on today's day of week.
    - Thursday: Jobless Claims
    - Friday: NFP (first Friday), PCE (last Friday)
    """
    now  = datetime.now(timezone.utc)
    dow  = now.weekday()       # 0=Mon, 4=Fri, 3=Thu
    day  = now.day
    month_last_day = calendar.monthrange(now.year, now.month)[1]

    today_events = []

    # Thursday: Jobless Claims
    if dow == 3:
        today_events.append(next(e for e in LOW_IMPACT_EVENTS if "Claims" in e.name))

    # Check if first Friday (NFP)
    if dow == 4:
        # First Friday = day <= 7
        if day <= 7:
            today_events.append(next(e for e in HIGH_IMPACT_EVENTS if "NFP" in e.name))
        # Last Friday (PCE)
        if day > month_last_day - 7:
            today_events.append(next(e for e in HIGH_IMPACT_EVENTS if "PCE" in e.name))

    return today_events


def is_blackout_window(events: Optional[list[EconomicEvent]] = None) -> bool:
    """
    Check if the current UTC time is within any active blackout window.
    Returns True if new grid entries should be paused.
    """
    if events is None:
        events = get_high_impact_today()

    now_utc = datetime.now(timezone.utc)
    now_min  = now_utc.hour * 60 + now_utc.minute

    for ev in events:
        if ev.avoid_window_min <= 0 or ev.time_utc == "varies":
            continue
        try:
            h, m = map(int, ev.time_utc.split(":"))
        except ValueError:
            continue

        event_min = h * 60 + m
        if abs(now_min - event_min) <= ev.avoid_window_min:
            return True

    return False
