"""Return and covariance estimators.

Conventions: ``returns`` is a list of rows (time) × list of columns
(assets), i.e. ``returns[t][i]`` is asset i's return in period t.
All estimators are plain functions — no hidden state, easy to test and
to swap for a sibling module's estimator later.
"""

from __future__ import annotations

from .linalg import transpose


def _check(returns: list[list[float]]) -> tuple[int, int]:
    if not returns or not returns[0]:
        raise ValueError("returns must be a non-empty T×N matrix")
    n = len(returns[0])
    if any(len(r) != n for r in returns):
        raise ValueError("ragged returns matrix")
    return len(returns), n


def mean_returns(returns: list[list[float]]) -> list[float]:
    """Historical mean return per asset (per-period units)."""
    t, _ = _check(returns)
    cols = transpose(returns)
    return [sum(c) / t for c in cols]


def shrink_mean(returns: list[list[float]], delta: float = 0.3) -> list[float]:
    """Shrink per-asset means toward the grand mean.

    A light James-Stein-flavoured guard against the noisiest estimates
    dominating the optimizer.  ``delta=0`` is the raw sample mean.
    """
    if not 0.0 <= delta <= 1.0:
        raise ValueError("delta must be in [0, 1]")
    mu = mean_returns(returns)
    grand = sum(mu) / len(mu)
    return [(1 - delta) * m + delta * grand for m in mu]


def sample_covariance(returns: list[list[float]]) -> list[list[float]]:
    """Unbiased sample covariance (ddof=1)."""
    t, n = _check(returns)
    if t < 2:
        raise ValueError("need at least 2 observations")
    mu = mean_returns(returns)
    cov = [[0.0] * n for _ in range(n)]
    for row in returns:
        d = [row[i] - mu[i] for i in range(n)]
        for i in range(n):
            for j in range(i, n):
                cov[i][j] += d[i] * d[j]
    for i in range(n):
        for j in range(i, n):
            cov[i][j] /= (t - 1)
            cov[j][i] = cov[i][j]
    return cov


def shrink_covariance(returns: list[list[float]], delta: float = 0.2) -> list[list[float]]:
    """Shrink the sample covariance toward its diagonal (variances only).

    Kills the noisiest off-diagonal correlations while keeping each asset's
    own variance.  ``delta=0`` is the raw sample covariance; ``delta=1``
    assumes assets are uncorrelated.  A simple, honest stand-in for full
    Ledoit-Wolf shrinkage.
    """
    if not 0.0 <= delta <= 1.0:
        raise ValueError("delta must be in [0, 1]")
    s = sample_covariance(returns)
    n = len(s)
    return [[(1 - delta) * s[i][j] if i != j else s[i][j]
             for j in range(n)] for i in range(n)]


def ewma_covariance(returns: list[list[float]], lam: float = 0.94) -> list[list[float]]:
    """Exponentially-weighted covariance (RiskMetrics style).

    Recent observations dominate; ``lam=0.94`` is the classic daily choice.
    Mean is taken as zero (standard for short-horizon risk).
    """
    t, n = _check(returns)
    if not 0.0 < lam < 1.0:
        raise ValueError("lam must be in (0, 1)")
    cov = [[0.0] * n for _ in range(n)]
    wsum = 0.0
    w = 1.0
    for row in reversed(returns):  # most recent first
        wsum += w
        for i in range(n):
            for j in range(i, n):
                cov[i][j] += w * row[i] * row[j]
        w *= lam
    for i in range(n):
        for j in range(i, n):
            cov[i][j] /= wsum
            cov[j][i] = cov[i][j]
    return cov
