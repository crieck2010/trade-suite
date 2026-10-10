"""Raw SVI smile parameterization (Gatheral 2004) with a pure-Python fitter.

w(k) = a + b·(ρ·(k−m) + sqrt((k−m)² + s²)),  k = log-forward moneyness.

SVI gives smooth smiles, sane extrapolation, and closed-form local vol
via Dupire.  Fitted per expiry with Nelder-Mead in an unconstrained
transformed space: (a, log b, atanh ρ, m, log s).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def raw_svi_w(k: float, a: float, b: float, rho: float, m: float, s: float) -> float:
    return a + b * (rho * (k - m) + math.sqrt((k - m) ** 2 + s ** 2))


@dataclass
class SVIFit:
    T: float
    a: float
    b: float
    rho: float
    m: float
    s: float
    rmse_iv: float

    def total_variance(self, k: float) -> float:
        return raw_svi_w(k, self.a, self.b, self.rho, self.m, self.s)

    def iv(self, k: float) -> float:
        return math.sqrt(max(self.total_variance(k), 0.0) / self.T)

    def to_dict(self) -> dict:
        return {"T": self.T, "a": self.a, "b": self.b, "rho": self.rho,
                "m": self.m, "s": self.s, "rmse_iv": self.rmse_iv}


def _nelder_mead(f, x0: list[float], step: float = 0.1,
                 max_iter: int = 5000, tol: float = 1e-9) -> list[float]:
    n = len(x0)
    simplex = [list(x0)]
    for i in range(n):
        x = list(x0)
        x[i] += step
        simplex.append(x)
    vals = [f(x) for x in simplex]
    for _ in range(max_iter):
        order = sorted(range(n + 1), key=lambda i: vals[i])
        simplex = [simplex[i] for i in order]
        vals = [vals[i] for i in order]
        if max(abs(vals[0] - v) for v in vals[1:]) < tol:
            break
        centroid = [sum(simplex[i][j] for i in range(n)) / n for j in range(n)]
        xr = [centroid[j] + (centroid[j] - simplex[n][j]) for j in range(n)]
        fr = f(xr)
        if vals[0] <= fr < vals[n - 1]:
            simplex[n], vals[n] = xr, fr
            continue
        if fr < vals[0]:  # expand
            xe = [centroid[j] + 2.0 * (xr[j] - centroid[j]) for j in range(n)]
            fe = f(xe)
            simplex[n], vals[n] = (xe, fe) if fe < fr else (xr, fr)
            continue
        # contract
        xc = [centroid[j] + 0.5 * (simplex[n][j] - centroid[j]) for j in range(n)]
        fc = f(xc)
        if fc < vals[n]:
            simplex[n], vals[n] = xc, fc
            continue
        # shrink
        simplex = [simplex[0]] + [
            [simplex[0][j] + 0.5 * (simplex[i][j] - simplex[0][j])
             for j in range(n)] for i in range(1, n + 1)]
        vals = [f(x) for x in simplex]
    return simplex[0]


def fit_svi_slice(ks: list[float], ivs: list[float], T: float) -> SVIFit:
    """Fit raw SVI to one expiry's (k, iv) smile."""
    if len(ks) != len(ivs) or len(ks) < 5:
        raise ValueError("need >= 5 smile points")
    if T <= 0:
        raise ValueError("need T > 0")
    w_mkt = [iv * iv * T for iv in ivs]
    w_atm = w_mkt[min(range(len(ks)), key=lambda i: abs(ks[i]))]

    def unpack(x):
        a, lb, ar, m, ls = x
        return a, math.exp(lb), math.tanh(ar), m, math.exp(ls)

    def objective(x):
        a, b, rho, m, s = unpack(x)
        err = 0.0
        for k, wm in zip(ks, w_mkt):
            w = raw_svi_w(k, a, b, rho, m, s)
            iv_fit = math.sqrt(max(w, 0.0) / T)
            iv_m = math.sqrt(max(wm, 0.0) / T)
            err += (iv_fit - iv_m) ** 2
        # Gatheral-Jim Gatheral no-butterfly-ish guard: ATM total variance >= 0
        guard = a + b * s * math.sqrt(max(1 - rho * rho, 0.0))
        if guard < 0:
            err += 1e6 * guard * guard
        return err

    x0 = [max(w_atm - 0.04, 0.001), math.log(0.15),
          math.atanh(-0.3), 0.0, math.log(0.3)]
    x = _nelder_mead(objective, x0)
    a, b, rho, m, s = unpack(x)
    iv_fit = [math.sqrt(max(raw_svi_w(k, a, b, rho, m, s), 0.0) / T) for k in ks]
    rmse = math.sqrt(sum((f - m_) ** 2 for f, m_ in zip(iv_fit, ivs)) / len(ks))
    return SVIFit(T=T, a=a, b=b, rho=rho, m=m, s=s, rmse_iv=rmse)


def fit_svi_surface(surface) -> dict[float, SVIFit]:
    """Fit one SVI smile per quoted expiry of a VolSurface."""
    fits = {}
    for T in surface.expiries:
        ks, ws = surface._grid[T]
        ivs = [math.sqrt(max(w, 0.0) / T) for w in ws]
        fits[T] = fit_svi_slice(ks, ivs, T)
    return fits
