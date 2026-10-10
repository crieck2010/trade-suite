"""Smile analytics: delta-space quotes, risk-neutral density, local vol.

- 25-delta risk reversal / butterfly: the FX-style skew descriptors.
- Breeden-Litzenberger density: q(K) = e^{rT} · ∂²C/∂K².
- Dupire local volatility from fitted SVI slices (Gatheral's formula).
"""

from __future__ import annotations

import math

from .black_scholes import bs_greeks, bs_price


def strike_for_delta(surface, T: float, delta: float, kind: str = "call",
                     tol: float = 1e-9) -> float:
    """Find K with the given spot delta via bisection (delta uses surface IV)."""
    F = surface.s0 * math.exp(surface.r * T)
    lo, hi = F * math.exp(-3.0), F * math.exp(3.0)

    def d(K):
        return bs_greeks(surface.s0, K, T, surface.r, surface.iv(K, T), kind)["delta"]

    target = delta
    if kind == "call":
        flo, fhi = d(lo) - target, d(hi) - target
    else:
        flo, fhi = d(lo) - target, d(hi) - target
    if flo * fhi > 0:
        raise ValueError("delta target outside reachable range")
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        fm = d(mid) - target
        if abs(fm) < 1e-12:
            break
        if (flo < 0) == (fm < 0):
            lo, flo = mid, fm
        else:
            hi = mid
        if hi - lo < tol * F:
            break
    return 0.5 * (lo + hi)


def skew_quotes(surface, T: float) -> dict:
    """25-delta risk reversal and butterfly + ATM for one expiry."""
    atm = surface.atm_iv(T)
    kc = strike_for_delta(surface, T, 0.25, "call")
    kp = strike_for_delta(surface, T, -0.25, "put")
    iv_c = surface.iv(kc, T)
    iv_p = surface.iv(kp, T)
    return {"T": T, "atm_iv": atm,
            "rr_25d": iv_c - iv_p,          # risk reversal: skew direction
            "bfly_25d": 0.5 * (iv_c + iv_p) - atm,  # butterfly: smile curvature
            "K_call_25d": kc, "K_put_25d": kp}


def implied_density(surface, T: float, n: int = 201,
                    k_width: float = 1.0) -> list[dict]:
    """Risk-neutral density via Breeden-Litzenberger (central differences)."""
    F = surface.s0 * math.exp(surface.r * T)
    ks = [-k_width + 2 * k_width * i / (n - 1) for i in range(n)]
    Ks = [F * math.exp(k) for k in ks]
    calls = [bs_price(surface.s0, K, T, surface.r, surface.iv(K, T), "call")
             for K in Ks]
    disc = math.exp(surface.r * T)
    out = []
    for i in range(1, n - 1):
        d2c = (calls[i - 1] - 2 * calls[i] + calls[i + 1])
        dK = Ks[i + 1] - Ks[i - 1]
        q = disc * d2c / (dK * dK / 4.0)
        out.append({"K": Ks[i], "density": max(q, 0.0)})
    # normalize with the trapezoid rule over the returned grid
    total = sum(0.5 * (out[i]["density"] + out[i + 1]["density"])
                * (out[i + 1]["K"] - out[i]["K"]) for i in range(len(out) - 1))
    if total > 0:
        for p in out:
            p["density"] /= total
    return out


def _svi_w_at(fits: dict, T: float, k: float) -> float:
    Ts = sorted(fits)
    if T <= Ts[0]:
        return fits[Ts[0]].total_variance(k)
    if T >= Ts[-1]:
        return fits[Ts[-1]].total_variance(k)
    for i in range(1, len(Ts)):
        if T <= Ts[i]:
            t = (T - Ts[i - 1]) / (Ts[i] - Ts[i - 1])
            w1 = fits[Ts[i - 1]].total_variance(k)
            w2 = fits[Ts[i]].total_variance(k)
            return w1 + t * (w2 - w1)
    return fits[Ts[-1]].total_variance(k)


def local_vol(fits: dict, K: float, T: float, s0: float, r: float) -> float:
    """Dupire local volatility from SVI slices (Gatheral's w-formula).

    σ²_loc = (∂w/∂T) / g,  g = 1 − (k/w)w_k + ¼(−¼ − 1/w + k²/w²)w_k² + ½w_kk
    """
    F = s0 * math.exp(r * T)
    k = math.log(K / F)
    h = 1e-4
    w = _svi_w_at(fits, T, k)
    if w <= 1e-12:
        return 0.0
    wk = (_svi_w_at(fits, T, k + h) - _svi_w_at(fits, T, k - h)) / (2 * h)
    wkk = (_svi_w_at(fits, T, k + h) - 2 * w + _svi_w_at(fits, T, k - h)) / (h * h)
    Ts = sorted(fits)
    if T <= Ts[0] or T >= Ts[-1]:
        # one-sided in T at the edges
        t0, t1 = (Ts[0], Ts[1]) if T <= Ts[0] else (Ts[-2], Ts[-1])
        wt = (_svi_w_at(fits, t1, k) - _svi_w_at(fits, t0, k)) / (t1 - t0)
    else:
        for i in range(1, len(Ts)):
            if T <= Ts[i]:
                t0, t1 = Ts[i - 1], Ts[i]
                wt = (_svi_w_at(fits, t1, k) - _svi_w_at(fits, t0, k)) / (t1 - t0)
                break
    g = (1 - (k / w) * wk
         + 0.25 * (-0.25 - 1 / w + k * k / (w * w)) * wk * wk
         + 0.5 * wkk)
    if g <= 1e-12 or wt < 0:
        return 0.0
    return math.sqrt(wt / g)
