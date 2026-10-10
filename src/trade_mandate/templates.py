"""Mandate presets: starting constitutions with documented philosophies.

A preset is a starting point, not a recommendation — read the philosophy,
adjust the numbers, and ratify your own.  ``blank`` keeps only the schema
so every choice is deliberate.
"""

from __future__ import annotations

PHILOSOPHY = {
    "conservative": (
        "Capital preservation first.  Tight drawdown leash (10%), modest "
        "volatility target, single-name cap at 5%, no derivatives beyond "
        "defined-risk spreads, and a high conviction bar (40/100) before "
        "new risk.  For money you cannot afford to impair."
    ),
    "balanced": (
        "The default working mandate.  15% max drawdown, 12% vol target, "
        "1.5x portfolio leverage cap, 10% single-name cap.  Defined-risk "
        "options allowed; naked short options forbidden.  Regime conviction "
        "25/100 to open new risk."
    ),
    "aggressive": (
        "Maximum tolerated risk for experienced operators.  25% max "
        "drawdown, 20% vol target, 2x leverage, 15% single-name cap, lower "
        "conviction bar (15/100).  Still forbids naked short options and "
        "martingale averaging — aggression is about size, not recklessness."
    ),
    "blank": (
        "Schema only, defaults elsewhere.  Every number is a deliberate "
        "choice by the author.  Recommended: start here once you know what "
        "you want, not before."
    ),
}

PRESETS: dict[str, dict] = {
    "conservative": {
        "max_drawdown": 0.10,
        "vol_target": 0.08,
        "leverage_caps": {"portfolio": 1.0, "per_position": 0.10},
        "concentration": {"max_single_name_weight": 0.05,
                          "max_sector_weight": 0.25},
        "allowed_instruments": {
            "derivatives": {
                "allowed_types": ["long_call", "long_put", "covered_call",
                                  "credit_spread", "iron_butterfly"],
                "forbidden": ["naked_short_call", "naked_short_put"],
            },
        },
        "order_constraints": {"max_order_pct_adv": 0.02,
                              "allowed_order_types": ["limit"]},
        "regime_rules": {"min_conviction_to_trade": 40,
                         "stand_down_flat": True},
    },
    "balanced": {},  # the DEFAULTS in mandate.py, documented here for clarity
    "aggressive": {
        "max_drawdown": 0.25,
        "vol_target": 0.20,
        "leverage_caps": {"portfolio": 2.0, "per_position": 0.20},
        "concentration": {"max_single_name_weight": 0.15,
                          "max_sector_weight": 0.45},
        "allowed_instruments": {
            "derivatives": {
                "allowed_types": ["long_call", "long_put", "covered_call",
                                  "cash_secured_put", "credit_spread",
                                  "debit_spread", "iron_condor",
                                  "iron_butterfly", "collar"],
                "forbidden": ["naked_short_call", "naked_short_put"],
            },
        },
        "order_constraints": {"max_order_pct_adv": 0.10,
                              "allowed_order_types": ["market", "limit",
                                                      "stop", "stop_limit"]},
        "regime_rules": {"min_conviction_to_trade": 15,
                         "stand_down_flat": False},
    },
    "blank": {
        "max_drawdown": 0.50,
        "vol_target": 0.30,
        "leverage_caps": {"portfolio": 3.0, "per_position": 0.50},
        "concentration": {"max_single_name_weight": 0.50,
                          "max_sector_weight": 1.00},
        "allowed_instruments": {
            "asset_classes": ["equity", "etf", "option", "future", "crypto"],
            "derivatives": {"allowed_types": [], "forbidden": []},
        },
        "forbidden_behaviors": [],
        "order_constraints": {"max_order_pct_adv": 1.0,
                              "allowed_order_types": ["market", "limit",
                                                      "stop", "stop_limit"]},
        "regime_rules": {"min_conviction_to_trade": 0,
                         "stand_down_flat": False},
    },
}


def get_preset(name: str) -> dict:
    """Return the override dict for a preset (empty dict for balanced)."""
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; choose from "
                         f"{sorted(PRESETS)}")
    return dict(PRESETS[name])


def preset_names() -> list[str]:
    return sorted(PRESETS)
