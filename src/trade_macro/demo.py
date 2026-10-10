"""Seeded synthetic copper/gold series for demos and tests.

The arc is planted deliberately: a long EXPANSION (copper drifts up while
gold idles), a sharp CONTRACTION (copper falls hard — the growth scare),
then a RECOVERY.  Deterministic for a given seed; not market data, not
backtest evidence.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from .indicators import get_indicator

# (start_day, end_day, copper_drift, copper_vol) — gold: drift 0, vol 0.004
_ARC = [
    (0, 250, 0.0012, 0.008),    # expansion: copper grinds higher
    (250, 330, -0.0060, 0.015),  # contraction: sharp copper selloff
    (330, 600, 0.0015, 0.009),   # recovery
]


def demo_series(
    seed: int = 42,
    days: int = 600,
    start: str = "2024-01-02",
) -> dict:
    """Return ``{"copper": [...], "gold": [...]}`` price series."""
    rng = random.Random(seed)
    day0 = date.fromisoformat(start)
    copper_px, gold_px = 4.0, 2000.0
    copper, gold = [], []
    for d in range(days):
        drift, vol = next(p[2:] for p in _ARC if p[0] <= d < p[1])
        copper_px *= 1.0 + drift + vol * rng.gauss(0.0, 1.0)
        gold_px *= 1.0 + 0.004 * rng.gauss(0.0, 1.0)
        day = (day0 + timedelta(days=d)).isoformat()
        copper.append({"date": day, "price": copper_px})
        gold.append({"date": day, "price": gold_px})
    return {"copper": copper, "gold": gold}


def run_demo(seed: int = 42, preset: str = "standard") -> dict:
    """Full demo pipeline: series -> panel -> alerts -> latest snapshot."""
    series = demo_series(seed=seed)
    spec = get_indicator("copper_gold")
    data = spec["compute"](series, preset=preset)
    panel = data["panel"]
    seen = []
    for r in panel:
        if not seen or seen[-1] != r["regime"]:
            seen.append(r["regime"])
    return {
        "copper": series["copper"],
        "gold": series["gold"],
        "panel": panel,
        "alerts": data["alerts"],
        "latest": data["latest"],
        "regime_arc": seen,
        "source": "synthetic",
    }
