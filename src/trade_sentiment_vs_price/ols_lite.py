"""Minimal OLS for forward regressions: params, SEs, t-stats, p-values, R²."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .stats import mean, t_cdf


@dataclass
class OLSResult:
    params: list[float]
    bse: list[float]
    tvalues: list[float]
    pvalues: list[float]
    rsquared: float
    nobs: int
    var_names: list[str] = field(default_factory=list)

    def summary_dict(self) -> dict:
        return {"params": dict(zip(self.var_names, self.params)),
                "bse": dict(zip(self.var_names, self.bse)),
                "tvalues": dict(zip(self.var_names, self.tvalues)),
                "pvalues": dict(zip(self.var_names, self.pvalues)),
                "rsquared": self.rsquared, "nobs": self.nobs}


def _inverse(A: list[list[float]]) -> list[list[float]]:
    n = len(A)
    M = [row[:] + [1.0 if i == j else 0.0 for j in range(n)]
         for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-14:
            raise ValueError("singular matrix")
        M[col], M[piv] = M[piv], M[col]
        s = M[col][col]
        M[col] = [v / s for v in M[col]]
        for r in range(n):
            if r != col and M[r][col] != 0.0:
                f = M[r][col]
                M[r] = [rv - f * cv for rv, cv in zip(M[r], M[col])]
    return [row[n:] for row in M]


def ols(y: list[float], X: list[list[float]],
        var_names: list[str] | None = None) -> OLSResult:
    n = len(y)
    Xmat = [[1.0] + list(r) for r in X]
    k = len(Xmat[0])
    Xt = [list(c) for c in zip(*Xmat)]
    XtX = [[sum(a * b for a, b in zip(ra, rb)) for rb in Xt] for ra in Xt]
    XtX_inv = _inverse(XtX)
    Xty = [sum(rv * yv for rv, yv in zip(row, y)) for row in Xt]
    beta = [sum(rv * xv for rv, xv in zip(row, Xty)) for row in XtX_inv]
    resid = [yv - sum(b * xv for b, xv in zip(beta, row))
             for yv, row in zip(y, Xmat)]
    ssr = sum(e * e for e in resid)
    s2 = ssr / (n - k)
    se = [math.sqrt(max(s2 * XtX_inv[i][i], 0.0)) for i in range(k)]
    tv = [b / s if s > 0 else 0.0 for b, s in zip(beta, se)]
    pv = [2.0 * (1.0 - t_cdf(abs(t), n - k)) for t in tv]
    sst = sum((yv - mean(y)) ** 2 for yv in y)
    rsq = 1.0 - ssr / sst if sst > 0 else 0.0
    names = ["alpha"] + (var_names or [f"x{i}" for i in range(k - 1)])
    return OLSResult(beta, se, tv, pv, rsq, n, names)
