"""
GridSetup dataclass — carries all information for one grid-level entry.
"""

from dataclasses import dataclass, field
from typing import List, Literal


@dataclass
class GridSetup:
    symbol:    str
    timeframe: str
    direction: Literal["LONG", "SHORT"]

    # Grid level that was touched
    level:       float           # exact grid level price
    level_type:  str             # "MAJOR" | "MID" | "MINOR"
    touch_from:  str             # "above" (price came down) | "below" (price came up)

    # Order levels
    entry:       float           # market price at execution
    stop_loss:   float           # 0.0 = no hard SL
    target:      float           # TP = next grid level
    risk_reward: float           # 0.0 = N/A (no SL)

    # Lot size
    lots:        float

    # Context
    session:     str             # e.g. "London", "NY", "Off-session"
    slot:        int             # 0-47 (30-min UTC slot index)
    notes:       List[str] = field(default_factory=list)
