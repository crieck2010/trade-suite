"""RiskMetrics EWMA volatility (J.P. Morgan, 1996).

The exponentially weighted moving average gives yesterday a weight of
λ and everything before it geometrically declining weights — the
industry's quick-and-dirty vol forecast, and still the benchmark every
fancier model has to beat.

    σ²_t = λ·σ²_{t-1} + (1 − λ)·r²_{t-1},   λ = 0.94 (daily)
"""

from __future__ import annotations

import math


def ewma_variance(
    returns: list[float],
    lam: float = 0.94,
    init: float | None = None,
) -> list[float]:
    """Filtered variance series; ``var[t]`` uses returns up to ``t-1``."""
    if not 0.0 < lam < 1.0:
        raise ValueError("lam must be in (0, 1)")
    if len(returns) < 2:
        raise ValueError("need at least 2 returns")
    var = init if init is not None else sum(r * r for r in returns) / len(returns)
    if var <= 0:
        raise ValueError("initial variance must be positive")
    out = []
    for r in returns:
        var = lam * var + (1.0 - lam) * r * r
        out.append(var)
    return out


def ewma_forecast(
    returns: list[float],
    horizon: int = 1,
    lam: float = 0.94,
    annualize: int = 252,
) -> dict:
    """EWMA vol forecast.  Flat term structure: every horizon gets the
    current filtered variance (EWMA has no mean reversion)."""
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    var_t = ewma_variance(returns, lam=lam)[-1]
    vol = math.sqrt(var_t * annualize)
    return {
        "model": "ewma",
        "lambda": lam,
        "horizon_days": horizon,
        "variance": var_t,
        "vol_annualized": vol,
        # per-horizon (all identical — EWMA's term structure is flat)
        "term_structure": [vol] * horizon,
    }
