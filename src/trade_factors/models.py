"""Factor model regressions: time-series tests and the GRS statistic.

The time-series regression R_it − R_ft = α_i + β_i'F_t + ε_it is the
workhorse: betas are exposures, alpha is mispricing.  The GRS test
(Gibbons-Ross-Shanken 1989) asks whether N alphas are *jointly* zero —
the flagship "does this model price these assets" test.
"""

from __future__ import annotations

from .factors import FACTOR_SETS, FactorData
from .linalg import inverse, matvec
from .ols import OLSResult, ols
from .stats import f_pvalue, mean


def factor_matrix(factors: FactorData, model: str) -> tuple[list[str], list[list[float]]]:
    names = factors.names(model)
    return names, factors.matrix(names)


def timeseries_regression(asset_excess: list[float], factors: FactorData,
                          model: str = "ff5",
                          cov_type: str = "nonrobust") -> OLSResult:
    """Regress one asset's excess returns on the factor set."""
    names, X = factor_matrix(factors, model)
    return ols(asset_excess, X, var_names=names, cov_type=cov_type)


def panel_regressions(assets: dict[str, list[float]], factors: FactorData,
                      model: str = "ff5") -> dict[str, OLSResult]:
    """Time-series regression for every asset in the panel."""
    names, X = factor_matrix(factors, model)
    return {a: ols(r, [row[:] for row in X], var_names=names) for a, r in assets.items()}


def grs_test(results: dict[str, OLSResult], factors: FactorData,
             model: str = "ff5") -> dict:
    """GRS test that all alphas are jointly zero.

    F = ((T−N−K)/N) · (α'Σ⁻¹α) / (1 + μ_f'Ω⁻¹μ_f)  ~  F(N, T−N−K)
    """
    names = list(results)
    N, K = len(names), len(FACTOR_SETS[model])
    T = results[names[0]].nobs
    alphas = [results[n].params[0] for n in names]
    # residual covariance Σ (N×N)
    resid = [results[n].resid for n in names]
    Sigma = [[sum(ri * rj for ri, rj in zip(resid[i], resid[j])) / T
              for j in range(N)] for i in range(N)]
    # factor moments
    Fmat = factors.matrix(factors.names(model))
    mu = [mean(col) for col in zip(*Fmat)]
    dev = [[row[j] - mu[j] for j in range(K)] for row in Fmat]
    Omega = [[sum(dev[t][i] * dev[t][j] for t in range(T)) / T
              for j in range(K)] for i in range(K)]
    aSa = sum(a * b for a, b in zip(alphas, matvec(inverse(Sigma), alphas)))
    mOm = sum(m * b for m, b in zip(mu, matvec(inverse(Omega), mu)))
    F = ((T - N - K) / N) * aSa / (1.0 + mOm)
    df1, df2 = N, T - N - K
    return {"F": F, "df1": df1, "df2": df2,
            "pvalue": f_pvalue(F, df1, df2),
            "n_assets": N, "n_factors": K, "nobs": T}
