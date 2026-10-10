"""Forecast evaluation: how to tell a good vol forecast from a lucky one.

Loss functions (Patton, 2011 — robust to noise in the vol proxy):

- ``mse`` — mean squared error; punishes big misses symmetrically.
- ``qlike`` — E[ σ̂²/σ² − ln(σ̂²/σ²) − 1 ]; the workhorse.  Robust:
  ranking models by QLIKE on a noisy realized-vol proxy gives the same
  ranking as on true latent volatility.  Asymmetric — under-predicting
  vol hurts more than over-predicting, which matches how risk feels.
- ``mae`` — mean absolute error, for the median-minded.

``mincer_zarnowitz`` regresses realized on forecast: a perfect
forecast has intercept 0 and slope 1; the R² says how much of
tomorrow's vol the forecast actually explains.
"""

from __future__ import annotations

import math

from .linalg import ols_fit


def mse(realized: list[float], forecast: list[float]) -> float:
    _check(realized, forecast)
    return sum((f - r) ** 2 for f, r in zip(forecast, realized)) / len(realized)


def mae(realized: list[float], forecast: list[float]) -> float:
    _check(realized, forecast)
    return sum(abs(f - r) for f, r in zip(forecast, realized)) / len(realized)


def qlike(realized_var: list[float], forecast_var: list[float]) -> float:
    """Patton (2011) QLIKE.  Inputs are *variances*, both > 0."""
    _check(realized_var, forecast_var)
    total = 0.0
    for r, f in zip(realized_var, forecast_var):
        if r <= 0 or f <= 0:
            raise ValueError("QLIKE needs positive variances")
        total += r / f - math.log(r / f) - 1.0
    return total / len(realized_var)


def _check(a: list[float], b: list[float]) -> None:
    if len(a) != len(b) or not a:
        raise ValueError("realized and forecast must be non-empty and aligned")


def mincer_zarnowitz(realized: list[float], forecast: list[float]) -> dict:
    """Regress realized vol on the forecast: RV = a + b·F + e."""
    _check(realized, forecast)
    fit = ols_fit([[1.0, f] for f in forecast], realized)
    a, b = fit["beta"]
    return {
        "intercept": a,          # want ≈ 0 (no bias)
        "slope": b,              # want ≈ 1 (right scale)
        "r_squared": fit["r_squared"],  # explanatory power
        "n": fit["n"],
    }


def compare(realized: list[float], forecasts: dict[str, list[float]]) -> dict:
    """Head-to-head table: MSE, MAE, and MZ R² per named forecast."""
    return {
        name: {
            "mse": mse(realized, f),
            "mae": mae(realized, f),
            "mz_r2": mincer_zarnowitz(realized, f)["r_squared"],
        }
        for name, f in forecasts.items()
    }
