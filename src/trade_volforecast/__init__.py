"""Volatility forecasting for the trade-suite.

Realized-volatility estimators (close-to-close, Parkinson, Garman-Klass,
Rogers-Satchell, Yang-Zhang), RiskMetrics EWMA, GARCH(1,1) and
GJR-GARCH(1,1) by maximum likelihood, HAR-RV regressions, and forecast
evaluation (MSE, QLIKE, Mincer-Zarnowitz).  Stdlib-only, deterministic.
"""

from __future__ import annotations

__version__ = "0.1.0"

from . import demo, evaluate, ewma, garch, har, linalg, optimize, realized, rng
from .adapters import (
    realized_from_bars,
    to_agent_vol_report,
    vol_for_optimize,
    vol_for_risk,
)
from .demo import demo_bars
from .evaluate import compare, mae, mincer_zarnowitz, mse, qlike
from .ewma import ewma_forecast, ewma_variance
from .garch import (
    fit_garch,
    fit_gjr,
    garch_forecast,
    simulate_garch,
    simulate_gjr,
)
from .har import har_fit, har_predict
from .realized import ESTIMATORS, realized_vol, realized_var_series

__all__ = [
    "ESTIMATORS",
    "compare",
    "demo_bars",
    "evaluate",
    "ewma",
    "ewma_forecast",
    "ewma_variance",
    "fit_garch",
    "fit_gjr",
    "garch",
    "garch_forecast",
    "har",
    "har_fit",
    "har_predict",
    "linalg",
    "mae",
    "mincer_zarnowitz",
    "mse",
    "optimize",
    "qlike",
    "realized",
    "realized_from_bars",
    "realized_vol",
    "realized_var_series",
    "rng",
    "simulate_garch",
    "simulate_gjr",
    "to_agent_vol_report",
    "vol_for_optimize",
    "vol_for_risk",
]
