"""trade-hedge: the auto-hedging loop for the trade-suite.

The adjustment engine that keeps a portfolio inside its risk limits as prices
move. Pure-Python, stdlib-only engine. Plain data in/out (dicts, lists of
floats). The loop NEVER places orders — it emits hedge PROPOSALS into
trade-paper's approval queue, where the user is the final gate.

Research/backtesting/paper-trading only — never live trading, never
personalized investment advice.
"""

from __future__ import annotations

from .adapters import (
    betas_from_factors,
    positions_from_paper,
    prices_from_data,
    proposals_to_paper_payloads,
    vol_from_volforecast,
)
from .demo import demo_drift_breach, demo_stale_data, demo_vol_regime_shift
from .exposures import compute_exposures
from .hedges import (
    delta_trim_rule,
    exposure_cap_rule,
    propose_hedges,
    vol_regime_rule,
)
from .presets import PRESETS, describe_presets
from .safety import safety_check
from .scheduler import LoopState, run_cycle

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "LoopState",
    "PRESETS",
    "betas_from_factors",
    "compute_exposures",
    "delta_trim_rule",
    "demo_drift_breach",
    "demo_stale_data",
    "demo_vol_regime_shift",
    "describe_presets",
    "exposure_cap_rule",
    "positions_from_paper",
    "prices_from_data",
    "proposals_to_paper_payloads",
    "propose_hedges",
    "run_cycle",
    "safety_check",
    "vol_from_volforecast",
    "vol_regime_rule",
]
