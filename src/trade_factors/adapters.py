"""Interop adapters: plain-data bridges to sibling suite modules.

Sibling imports are lazy (inside functions) so trade-factors stays
importable and testable on its own.
"""

from __future__ import annotations

from .models import grs_test, panel_regressions
from .ols import OLSResult
from .risk_model import factor_cov_from_data, factor_covariance


# ------------------------------------------------------- trade-data-equities

def returns_from_prices(prices: list[float]) -> list[float]:
    """Simple returns from a price series (duck-typed bars work too)."""
    return [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices))]


# -------------------------------------------------------------- trade-agents

def to_agent_factor_report(results: dict[str, OLSResult],
                           grs: dict | None = None) -> dict:
    """Agent-ready factor report: alphas, betas, fit, and the GRS verdict."""
    return {
        "source": "trade-factors",
        "assets": {a: {"alpha": r.params[0],
                       "alpha_t": r.tvalues[0],
                       "alpha_p": r.pvalues[0],
                       "betas": dict(zip(r.var_names[1:], r.params[1:])),
                       "rsquared": r.rsquared,
                       "nobs": r.nobs}
                   for a, r in results.items()},
        "grs": grs,
    }


# ------------------------------------------------------------- trade-optimize

def cov_for_optimize(betas: list[list[float]], factor_rets: list[list[float]],
                     idio_var: list[float]) -> list[list[float]]:
    """Factor-implied asset covariance for trade-optimize's covariance slot.

    Structured, always positive-definite (given positive idio_var), and
    far better conditioned than a raw sample covariance on short history.
    """
    return factor_covariance(betas, factor_cov_from_data(factor_rets), idio_var)


# ---------------------------------------------------------------- trade-risk

def exposures_for_risk(asset_names: list[str],
                       results: dict[str, OLSResult]) -> dict:
    """Factor exposure table for trade-risk monitoring."""
    return {
        "source": "trade-factors",
        "exposures": {a: dict(zip(results[a].var_names[1:], results[a].params[1:]))
                      for a in asset_names if a in results},
    }


# ------------------------------------------------------------ trade-backtest

def factor_mimicking_weights(scores: list[float], n_long: int,
                             n_short: int) -> list[float]:
    """Dollar-neutral long-short weights from characteristic scores."""
    from .portfolios import long_short_weights
    return long_short_weights(scores, n_long, n_short)
