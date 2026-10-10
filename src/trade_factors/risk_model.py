"""Factor risk model: Σ = B·F·Bᵀ + D and return attribution.

Decomposes portfolio variance into factor vs idiosyncratic pieces and
attributes realized returns to factor exposures — the input
trade-optimize wants for a factor-aware covariance, and the lens
trade-risk wants for exposure monitoring.
"""

from __future__ import annotations

from .linalg import matmul, transpose
from .stats import mean


def factor_covariance(betas: list[list[float]],
                      factor_cov: list[list[float]],
                      idio_var: list[float]) -> list[list[float]]:
    """Asset covariance from N×K betas, K×K factor cov, N idiosyncratic vars."""
    N, K = len(betas), len(factor_cov)
    BFB = matmul(matmul(betas, factor_cov), transpose(betas))
    return [[BFB[i][j] + (idio_var[i] if i == j else 0.0) for j in range(N)]
            for i in range(N)]


def factor_cov_from_data(factor_rets: list[list[float]]) -> list[list[float]]:
    """Sample covariance of n×K factor returns."""
    n, K = len(factor_rets), len(factor_rets[0])
    mu = [mean(col) for col in zip(*factor_rets)]
    return [[sum((factor_rets[t][i] - mu[i]) * (factor_rets[t][j] - mu[j])
                 for t in range(n)) / (n - 1) for j in range(K)] for i in range(K)]


def variance_decomposition(weights: list[float], betas: list[list[float]],
                           factor_cov: list[list[float]],
                           idio_var: list[float]) -> dict:
    """Split portfolio variance into per-factor and idiosyncratic pieces."""
    K = len(factor_cov)
    port_beta = [sum(w * betas[i][k] for i, w in enumerate(weights))
                 for k in range(K)]
    factor_var = sum(port_beta[i] * port_beta[j] * factor_cov[i][j]
                     for i in range(K) for j in range(K))
    idio = sum(w * w * v for w, v in zip(weights, idio_var))
    total = factor_var + idio
    return {
        "total_var": total,
        "factor_var": factor_var,
        "idio_var": idio,
        "factor_share": factor_var / total if total > 0 else 0.0,
        "per_factor": [port_beta[i] * sum(factor_cov[i][j] * port_beta[j]
                                         for j in range(K)) for i in range(K)],
        "portfolio_beta": port_beta,
    }


def factor_attribution(port_excess: list[float], betas: list[float],
                       factor_rets: list[list[float]],
                       factor_names: list[str]) -> dict:
    """Attribute mean excess return to alpha + each factor exposure."""
    K = len(factor_names)
    fitted = [[sum(betas[k] * factor_rets[t][k] for k in range(K))]
              for t in range(len(port_excess))]
    alpha = mean([p - f[0] for p, f in zip(port_excess, fitted)])
    contrib = {nm: betas[k] * mean([row[k] for row in factor_rets])
               for k, nm in enumerate(factor_names)}
    return {"alpha": alpha, "factor_contrib": contrib,
            "total": alpha + sum(contrib.values()),
            "mean_excess": mean(port_excess)}
