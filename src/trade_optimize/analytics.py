"""Portfolio analytics: what a weight vector implies.

All functions take plain weight lists and return plain data — no optimizer
state leaks into reporting, so these double as the suite's shared
portfolio-math helpers.
"""

from __future__ import annotations

import math

from .linalg import dot, mat_vec


def portfolio_stats(weights: list[float], mu: list[float],
                    sigma: list[list[float]], risk_free: float = 0.0,
                    periods_per_year: int = 252) -> dict:
    """Expected return / volatility / Sharpe, per-period and annualized."""
    er = dot(weights, mu)
    var = dot(weights, mat_vec(sigma, weights))
    vol = math.sqrt(max(var, 0.0))
    sharpe = (er - risk_free) / vol if vol > 0 else 0.0
    ann = math.sqrt(periods_per_year)
    return {
        "expected_return": er,
        "volatility": vol,
        "sharpe": sharpe,
        "expected_return_ann": er * periods_per_year,
        "volatility_ann": vol * ann,
        "sharpe_ann": sharpe * ann,
        "max_weight": max(weights),
        "n_assets": len(weights),
        "n_held": sum(1 for w in weights if w > 1e-9),
    }


def risk_contributions(weights: list[float],
                       sigma: list[list[float]]) -> list[dict]:
    """Per-asset risk contributions: RCᵢ = wᵢ(Σw)ᵢ, plus share of total vol.

    RCᵢ sums to portfolio variance; the shares sum to 1.  The workhorse
    behind concentration limits and risk-parity checks.
    """
    sw = mat_vec(sigma, weights)
    var = dot(weights, sw)
    vols = math.sqrt(max(var, 0.0))
    out = []
    for i, (w, s) in enumerate(zip(weights, sw)):
        rc = w * s
        out.append({
            "index": i,
            "weight": w,
            "risk_contribution": rc,
            "risk_share": rc / var if var > 0 else 0.0,
            "marginal_vol": s / vols if vols > 0 else 0.0,
        })
    return out


def diversification_ratio(weights: list[float],
                          sigma: list[list[float]]) -> float:
    """Weighted-average asset vol / portfolio vol.  ≥ 1; higher = more diversified."""
    vols = [math.sqrt(max(sigma[i][i], 0.0)) for i in range(len(weights))]
    port_vol = math.sqrt(max(dot(weights, mat_vec(sigma, weights)), 0.0))
    if port_vol == 0:
        return 1.0
    return dot(weights, vols) / port_vol


def herfindahl(weights: list[float]) -> float:
    """Sum of squared weights: 1/N (fully spread) … 1 (single asset)."""
    return sum(w * w for w in weights)
