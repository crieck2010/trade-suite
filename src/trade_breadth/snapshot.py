"""The ``snapshot()`` interop contract.

This is the single stable object the rest of the suite consumes:

- **trade-agents** merges it into ``market_context`` on every idea/debate
- **trade-risk** reads ``regime``/``fragility`` for regime-conditional limits
- **trade-hedge** reads ``fragility`` as a defensive-tilt input

Schema is versioned (``schema_version``); v1 is documented in
``docs/ARCHITECTURE.md``.  The dict is JSON-serializable by construction
(missing values are ``None``, never NaN).
"""

from __future__ import annotations

import json

from .breadth import breadth_panel
from .regime import PRESETS, classify_regime
from .thrusts import detect_narrowing_warnings, detect_thrusts
from .universe import validate_universe

SCHEMA_VERSION = 1

INDICATOR_KEYS = (
    "advancers", "decliners", "unchanged", "ad_ratio", "ad_line",
    "pct_above_50dma", "pct_above_200dma",
    "new_highs", "new_lows", "highs_minus_lows", "up_down_volume_ratio",
    "mcclellan_oscillator", "mcclellan_summation",
    "ew_index", "cw_index", "ew_cw_ratio", "ew_cw_ratio_vs_63dma",
)


def snapshot(
    universe: dict,
    weights: dict[str, float] | None = None,
    date: str | None = None,
    preset: str = "standard",
    thrust_window: int = 10,
) -> dict:
    """Build the dated, JSON-serializable regime snapshot.

    ``date`` selects a historical snapshot (default: the last panel date).
    Raises ValueError for an unknown date.
    """
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; choose from {sorted(PRESETS)}")
    clean = validate_universe(universe)
    panel = breadth_panel(clean, weights=weights)
    regimes = classify_regime(panel, weights=weights, preset=preset)
    thrusts = detect_thrusts(panel, window=thrust_window)
    warnings = detect_narrowing_warnings(panel)

    if date is None:
        idx = len(panel) - 1
    else:
        dates = [r["date"] for r in panel]
        if date not in dates:
            raise ValueError(f"date {date!r} not in panel "
                             f"({dates[0]}..{dates[-1]})")
        idx = dates.index(date)

    row = panel[idx]
    reg = regimes[idx]
    recent_thrusts = [t for t in thrusts if t["date"] <= row["date"]][-5:]
    active_warnings = [w for w in warnings if w["date"] == row["date"]]

    snap = {
        "schema_version": SCHEMA_VERSION,
        "date": row["date"],
        "universe": {
            "n_symbols": row["n_symbols"],
            "n_priced": row["n_priced"],
            "weights_supplied": weights is not None,
        },
        "regime": reg["regime"],
        "regime_score": reg["regime_score"],
        "fragility": reg["fragility"],
        "indicators": {k: row.get(k) for k in INDICATOR_KEYS},
        "regime_components": reg["components"],
        "thrusts_recent": recent_thrusts,
        "warnings": active_warnings,
        "config": {
            "preset": preset,
            "thrust_window": thrust_window,
            "thresholds": PRESETS[preset],
        },
    }
    # contract enforcement: must survive a JSON round-trip
    json.dumps(snap)
    return snap


def snapshot_history(
    universe: dict,
    weights: dict[str, float] | None = None,
    preset: str = "standard",
) -> list[dict]:
    """Regime/fragility history: one compact dict per panel date."""
    clean = validate_universe(universe)
    panel = breadth_panel(clean, weights=weights)
    regimes = classify_regime(panel, weights=weights, preset=preset)
    return [
        {
            "date": r["date"],
            "regime": r["regime"],
            "regime_score": r["regime_score"],
            "fragility": r["fragility"],
        }
        for r in regimes
    ]
