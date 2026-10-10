"""No-arbitrage diagnostics for a volatility surface.

Calendar arbitrage: total variance w(T) must be non-decreasing in T —
otherwise a calendar spread is a money machine.  Butterfly arbitrage:
call prices must be decreasing and convex in K (equivalently the
Breeden-Litzenberger density is non-negative).
"""

from __future__ import annotations

import math

from .black_scholes import bs_price


def calendar_violations(surface, n_k: int = 9, k_width: float = 0.5,
                        tol: float = 1e-9) -> list[dict]:
    """Find (k, T1, T2) where total variance decreases with expiry."""
    out = []
    Ts = surface.expiries
    for i in range(n_k):
        k = -k_width + 2 * k_width * i / max(n_k - 1, 1)
        for j in range(1, len(Ts)):
            K1 = surface.s0 * math.exp(surface.r * Ts[j - 1] + k)
            K2 = surface.s0 * math.exp(surface.r * Ts[j] + k)
            w1 = surface.total_variance(K1, Ts[j - 1])
            w2 = surface.total_variance(K2, Ts[j])
            if w2 < w1 - tol:
                out.append({"k": k, "T1": Ts[j - 1], "T2": Ts[j],
                            "w1": w1, "w2": w2, "gap": w1 - w2})
    return out


def butterfly_violations(surface, T: float, n: int = 41,
                         k_width: float = 0.6, tol: float = 1e-6) -> list[dict]:
    """Rebuild call prices from the smile; check decreasing + convex in K."""
    F = surface.s0 * math.exp(surface.r * T)
    Ks = [F * math.exp(-k_width + 2 * k_width * i / (n - 1)) for i in range(n)]
    calls = [bs_price(surface.s0, K, T, surface.r, surface.iv(K, T), "call")
             for K in Ks]
    out = []
    for i, (K, C) in enumerate(zip(Ks, calls)):
        intrinsic = max(surface.s0 - K * math.exp(-surface.r * T), 0.0)
        if C < intrinsic - tol:
            out.append({"type": "below-intrinsic", "K": K, "C": C,
                        "intrinsic": intrinsic})
        if i > 0 and calls[i] > calls[i - 1] + tol:
            out.append({"type": "not-decreasing", "K": K,
                        "C_prev": calls[i - 1], "C": C})
    # convexity via increasing slopes (correct for the non-uniform K grid)
    for i in range(1, n - 1):
        h0, h1 = Ks[i] - Ks[i - 1], Ks[i + 1] - Ks[i]
        slope0 = (calls[i] - calls[i - 1]) / h0
        slope1 = (calls[i + 1] - calls[i]) / h1
        if slope1 < slope0 - tol:
            out.append({"type": "not-convex", "K": Ks[i],
                        "slope_change": slope1 - slope0})
    return out


def check_surface(surface) -> dict:
    """Full diagnostic: calendar + per-expiry butterfly checks."""
    cal = calendar_violations(surface)
    bfly = {T: butterfly_violations(surface, T) for T in surface.expiries}
    n_bfly = sum(len(v) for v in bfly.values())
    return {"calendar_violations": cal,
            "butterfly_violations": {T: v for T, v in bfly.items() if v},
            "n_calendar": len(cal), "n_butterfly": n_bfly,
            "arbitrage_free": len(cal) == 0 and n_bfly == 0}
