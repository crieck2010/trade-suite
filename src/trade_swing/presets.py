"""Conservative / balanced / aggressive presets.

Starting points, not optimized values. The strategy's edge (if any) must
survive the gates under the preset you actually intend to trade —
tuning the preset to the demo until it passes is overfitting, and the
docs say so.
"""

from __future__ import annotations

from .costs import CostModel
from .strategy import SwingConfig


PRESETS: dict[str, dict] = {
    "conservative": {
        "description": "Slow signals, wide stops, tiny risk: fewer trades, "
                       "shallower drawdowns, more whipsaw lag.",
        "config": SwingConfig(fast=30, slow=80, atr_period=14,
                              stop_multiple=4.0, risk_per_trade=0.005,
                              max_position_pct=0.15,
                              regime_min_conviction=50.0),
        "costs": CostModel(),
    },
    "balanced": {
        "description": "The reference configuration used across the docs.",
        "config": SwingConfig(),
        "costs": CostModel(),
    },
    "aggressive": {
        "description": "Fast signals, tight stops, more risk: more trades, "
                       "deeper drawdowns, higher cost drag.",
        "config": SwingConfig(fast=10, slow=30, atr_period=10,
                              stop_multiple=2.0, risk_per_trade=0.02,
                              max_position_pct=0.40,
                              regime_min_conviction=15.0),
        "costs": CostModel(slippage_bps=8.0),
    },
}


def get_preset(name: str) -> dict:
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; expected one of "
                         f"{sorted(PRESETS)}")
    return PRESETS[name]
