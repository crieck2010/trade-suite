"""Covariance estimation: sample covariance and Ledoit-Wolf shrinkage.

Sample covariance matrices are noisy when the number of assets is large
relative to the number of observations, and a noisy covariance fed to an
optimizer produces extreme, unstable weights.  Ledoit-Wolf (2004) shrinks
the sample covariance toward a structured target (scaled identity) with an
*optimal* intensity estimated from the data itself — no tuning parameter.
"""

from __future__ import annotations

import math


def sample_cov(
    returns: dict[str, list[float]],
    annualize: int = 252,
) -> dict:
    """Sample covariance as plain data.

    Returns ``{"symbols": [...], "matrix": [[...]], "annualized": bool}``;
    the matrix is scaled by ``annualize`` so volatilities read as annual.
    """
    syms = sorted(returns)
    if len(syms) < 2:
        raise ValueError("need at least two series")
    t = min(len(returns[s]) for s in syms)
    if t < 2:
        raise ValueError("need >= 2 observations")
    cols = [[returns[s][i] for i in range(t)] for s in syms]
    means = [sum(c) / t for c in cols]
    n = len(syms)
    mat = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            cov = sum((cols[i][k] - means[i]) * (cols[j][k] - means[j])
                      for k in range(t)) / (t - 1)
            mat[i][j] = mat[j][i] = cov * annualize
    return {"symbols": syms, "matrix": mat, "annualized": True,
            "n_obs": t, "scale": annualize}


def ledoit_wolf(
    returns: dict[str, list[float]],
    annualize: int = 252,
) -> dict:
    """Ledoit-Wolf (2004) optimal shrinkage toward ``mu * I``.

    Returns ``{"symbols", "matrix" (annualized), "shrinkage" (delta in
    [0, 1]), "target"}``.  ``delta = 0`` means the sample covariance is
    already well-conditioned; ``delta -> 1`` means the data are too noisy
    to trust and the estimator leans on the structured target.
    """
    syms = sorted(returns)
    if len(syms) < 2:
        raise ValueError("need at least two series")
    t = min(len(returns[s]) for s in syms)
    if t < 3:
        raise ValueError("need >= 3 observations for Ledoit-Wolf")
    n = len(syms)
    cols = [[returns[s][i] for i in range(t)] for s in syms]
    means = [sum(c) / t for c in cols]
    # Sample covariance (unscaled during estimation; scale at the end).
    S = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            S[i][j] = S[j][i] = sum(
                (cols[i][k] - means[i]) * (cols[j][k] - means[j])
                for k in range(t)) / t
    mu = sum(S[i][i] for i in range(n)) / n  # target: mu * I
    # pi_hat: sum of asymptotic variances of S entries.
    pi = 0.0
    for i in range(n):
        for j in range(n):
            pi += sum(((cols[i][k] - means[i]) * (cols[j][k] - means[j])
                       - S[i][j]) ** 2 for k in range(t)) / t
    # rho_hat: sum of asymptotic covariances with the target.
    rho = 0.0
    for i in range(n):
        for k in range(t):
            d = (cols[i][k] - means[i]) ** 2
            rho += ((d - S[i][i]) * (d - mu)) / t
    # gamma: squared misspecification of the target.
    gamma = sum((S[i][j] - (mu if i == j else 0.0)) ** 2
                for i in range(n) for j in range(n))
    kappa = max((pi - rho) / t, 0.0)
    delta = max(0.0, min(1.0, kappa / gamma)) if gamma > 0 else 0.0
    shrunk = [[delta * (mu if i == j else 0.0) + (1.0 - delta) * S[i][j]
               for j in range(n)] for i in range(n)]
    mat = [[v * annualize for v in row] for row in shrunk]
    return {"symbols": syms, "matrix": mat, "annualized": True,
            "shrinkage": delta,
            "target": "mu * I (scaled identity)",
            "target_mu": mu * annualize, "n_obs": t, "scale": annualize}


def portfolio_variance(weights: list[float], cov: dict) -> float:
    """Annualized portfolio variance ``w'Σw`` for a covariance dict."""
    mat = cov["matrix"]
    if len(weights) != len(mat):
        raise ValueError("weights length must match covariance dimension")
    return sum(w_i * sum(m_ij * w_j for m_ij, w_j in zip(row, weights))
               for w_i, row in zip(weights, mat))


def portfolio_volatility(weights: list[float], cov: dict) -> float:
    """Annualized portfolio volatility."""
    return math.sqrt(max(portfolio_variance(weights, cov), 0.0))
