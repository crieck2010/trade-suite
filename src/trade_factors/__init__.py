"""Fama-French factor analysis for the trade-suite.

Pure-Python OLS with inference, Ken French data-library parser, FF3/FF5/
Carhart time-series regressions, GRS joint-alpha test, Fama-MacBeth
two-pass tests, characteristic-sorted (2x3) factor portfolios, and a
factor risk model (Σ = B·F·Bᵀ + D).  Stdlib-only, deterministic.
"""

from __future__ import annotations

__version__ = "0.1.0"

from . import famamacbeth, factors, linalg, models, ols, portfolios, risk_model, stats
from .adapters import (
    cov_for_optimize,
    exposures_for_risk,
    factor_mimicking_weights,
    returns_from_prices,
    to_agent_factor_report,
)
from .factors import FACTOR_SETS, FactorData, demo_factors, load_french_csv
from .famamacbeth import fama_macbeth
from .models import grs_test, panel_regressions, timeseries_regression
from .ols import OLSResult, ols as ols_, rolling_ols
from .portfolios import double_sort_returns, long_short_weights
from .risk_model import (
    factor_attribution,
    factor_covariance,
    variance_decomposition,
)

__all__ = [
    "FACTOR_SETS",
    "FactorData",
    "OLSResult",
    "cov_for_optimize",
    "demo_factors",
    "double_sort_returns",
    "exposures_for_risk",
    "fama_macbeth",
    "famamacbeth",
    "factor_attribution",
    "factor_covariance",
    "factor_mimicking_weights",
    "factors",
    "grs_test",
    "linalg",
    "load_french_csv",
    "long_short_weights",
    "models",
    "ols",
    "ols_",
    "panel_regressions",
    "portfolios",
    "returns_from_prices",
    "risk_model",
    "rolling_ols",
    "stats",
    "timeseries_regression",
    "to_agent_factor_report",
    "variance_decomposition",
    "__version__",
]
