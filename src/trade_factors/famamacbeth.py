"""Fama-MacBeth two-pass cross-sectional test (1973).

Pass 1: time-series regression per asset → betas.
Pass 2: each period, regress returns on betas → risk-premium estimates λ_t.
Report mean premia with t-stats.  Answers "are these factors priced?"
rather than "do they span returns?".
"""

from __future__ import annotations

from .factors import FactorData
from .models import factor_matrix
from .ols import ols
from .stats import mean, std


def fama_macbeth(assets: dict[str, list[float]], factors: FactorData,
                 model: str = "ff5") -> dict:
    names = list(assets)
    fnames, X = factor_matrix(factors, model)
    T = len(X)
    # Pass 1: betas (drop the intercept — pass 2 estimates its own)
    betas = {}
    for a in names:
        res = ols(assets[a], [row[:] for row in X], var_names=fnames)
        betas[a] = res.params[1:]
    # Pass 2: cross-sectional regression each period
    lambdas: list[list[float]] = []
    for t in range(T):
        y = [assets[a][t] for a in names]
        B = [betas[a] for a in names]
        res = ols(y, B, var_names=fnames, add_intercept=True)
        lambdas.append(res.params)
    all_names = ["lambda_0"] + [f"lambda_{f}" for f in fnames]
    out = {}
    for j, nm in enumerate(all_names):
        series = [lam[j] for lam in lambdas]
        m, s = mean(series), std(series)
        out[nm] = {"mean": m, "std": s,
                   "tstat": m / (s / (T ** 0.5)) if s > 0 else 0.0,
                   "nobs": T}
    return {"premia": out, "model": model, "n_assets": len(names)}
