"""trade-breadth: US equity market-breadth engine.

Broadening vs narrowing participation, breadth thrusts, and a fragility
gauge — regime context for the trade-suite's agentic layer.

Pure-Python, stdlib-only engine. Plain data in/out (dicts, lists of floats).
Research/backtesting/paper-trading only — never live trading.
"""

from __future__ import annotations

from .adapters import (
    bars_from_trade_data_equities,
    hedge_tilt_input,
    market_context_provider,
    risk_regime_input,
)
from .breadth import breadth_panel, mcclellan
from .demo import run_demo
from .regime import (
    BROADENING,
    NARROWING,
    NEUTRAL,
    PRESETS,
    classify_regime,
    concentration,
    fragility,
    top_n_share,
)
from .snapshot import SCHEMA_VERSION, snapshot, snapshot_history
from .thrusts import detect_narrowing_warnings, detect_thrusts
from .universe import demo_universe, validate_universe

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "SCHEMA_VERSION",
    "BROADENING",
    "NARROWING",
    "NEUTRAL",
    "PRESETS",
    "bars_from_trade_data_equities",
    "breadth_panel",
    "classify_regime",
    "concentration",
    "demo_universe",
    "detect_narrowing_warnings",
    "detect_thrusts",
    "fragility",
    "hedge_tilt_input",
    "market_context_provider",
    "mcclellan",
    "risk_regime_input",
    "run_demo",
    "snapshot",
    "snapshot_history",
    "top_n_share",
    "validate_universe",
]
