"""OLS with inference: standard errors, t-stats, p-values, R².

cov_type="nonrobust" is the textbook estimator; "HC1" is White's
heteroskedasticity-consistent variant (MacKinnon-White small-sample
adjustment).  Solves the normal equations — fine for a handful of
factors; not the tool for thousand-column designs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .linalg import inverse, matmul, matvec, transpose
from .stats import mean, t_pvalue


@dataclass
class OLSResult:
    params: list[float]
    bse: list[float]
    tvalues: list[float]
    pvalues: list[float]
    rsquared: float
    adj_rsquared: float
    resid: list[float]
    nobs: int
    df_resid: int
    sigma2: float
    var_names: list[str] = field(default_factory=list)

    def summary_dict(self) -> dict:
        return {
            "params": dict(zip(self.var_names, self.params)),
            "bse": dict(zip(self.var_names, self.bse)),
            "tvalues": dict(zip(self.var_names, self.tvalues)),
            "pvalues": dict(zip(self.var_names, self.pvalues)),
            "rsquared": self.rsquared,
            "adj_rsquared": self.adj_rsquared,
            "nobs": self.nobs,
        }


def ols(y: list[float], X: list[list[float]],
        var_names: list[str] | None = None,
        add_intercept: bool = True,
        cov_type: str = "nonrobust") -> OLSResult:
    n = len(y)
    Xmat = _as_rows(y, X, add_intercept)
    k = len(Xmat[0])
    if n <= k:
        raise ValueError("need more observations than regressors")
    Xt = transpose(Xmat)
    XtX_inv = inverse(matmul(Xt, Xmat))
    beta = matvec(XtX_inv, matvec(Xt, y))
    resid = [yi - sum(b * xi for b, xi in zip(beta, row))
             for yi, row in zip(y, Xmat)]
    ssr = sum(e * e for e in resid)
    sigma2 = ssr / (n - k)
    if cov_type == "nonrobust":
        cov = [[sigma2 * v for v in row] for row in XtX_inv]
    elif cov_type == "HC1":
        meat = [[0.0] * k for _ in range(k)]
        for e, row in zip(resid, Xmat):
            for i in range(k):
                for j in range(k):
                    meat[i][j] += e * e * row[i] * row[j]
        tmp = matmul(XtX_inv, meat)
        cov = [[n / (n - k) * v for v in row]
               for row in matmul(tmp, XtX_inv)]
    else:
        raise ValueError("cov_type must be 'nonrobust' or 'HC1'")
    bse = [math.sqrt(max(cov[i][i], 0.0)) for i in range(k)]
    tvalues = [b / se if se > 0 else 0.0 for b, se in zip(beta, bse)]
    pvalues = [t_pvalue(t, n - k) for t in tvalues]
    sst = sum((yi - mean(y)) ** 2 for yi in y)
    rsq = 1.0 - ssr / sst if sst > 0 else 0.0
    adj = 1.0 - (1.0 - rsq) * (n - 1) / (n - k) if n > k else rsq
    names = var_names or [f"x{i}" for i in range(k - (1 if add_intercept else 0))]
    if add_intercept:
        names = ["alpha"] + names
    return OLSResult(beta, bse, tvalues, pvalues, rsq, adj, resid, n, n - k,
                     sigma2, names)


def _as_rows(y: list[float], X: list[list[float]],
             add_intercept: bool) -> list[list[float]]:
    """Accept X as n×k rows; prepend an intercept column if asked."""
    n = len(y)
    if len(X) != n or any(len(r) != len(X[0]) for r in X):
        raise ValueError("X must be n×k rows matching y")
    if add_intercept:
        return [[1.0] + list(r) for r in X]
    return [list(r) for r in X]


def rolling_ols(y: list[float], X: list[list[float]], window: int,
                var_names: list[str] | None = None) -> list[OLSResult]:
    """OLS on each trailing window — beta dynamics over time."""
    if window < 2 or window > len(y):
        raise ValueError("window must satisfy 2 <= window <= n")
    return [ols(y[i - window:i], [r[:] for r in X[i - window:i]],
                  var_names=var_names) for i in range(window, len(y) + 1)]
