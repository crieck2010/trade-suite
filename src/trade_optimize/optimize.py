"""Markowitz optimizers, long-only with optional per-asset weight caps.

All optimizers solve problems of the form::

    min  0.5·w'Σw − γ·μ'w     s.t.  Σw = 1,  0 ≤ w ≤ cap

with a projected-gradient QP solver.  The projection onto the capped
simplex is exact (bisection on the Lagrange multiplier), and the step size
1/L (L = largest eigenvalue of Σ) guarantees convergence.

- γ = 0            → global minimum-variance portfolio
- γ swept upward  → the efficient frontier; the max-Sharpe point is read off it
"""

from __future__ import annotations

import math

from .linalg import dot, mat_vec, max_eigenvalue


def _project_capped_simplex(y: list[float], cap: float) -> list[float]:
    """Euclidean projection of y onto {x : Σx = 1, 0 ≤ x ≤ cap}."""
    n = len(y)
    if cap * n < 1.0 - 1e-12:
        raise ValueError(f"cap {cap} infeasible for {n} assets (cap*n < 1)")
    lo, hi = min(y) - cap - 1.0, max(y)
    for _ in range(200):
        mid = (lo + hi) / 2.0
        s = sum(min(max(v - mid, 0.0), cap) for v in y)
        if s > 1.0:
            lo = mid
        else:
            hi = mid
    lam = (lo + hi) / 2.0
    return [min(max(v - lam, 0.0), cap) for v in y]


def _qp(Q: list[list[float]], c: list[float], cap: float,
        tol: float = 1e-10, max_iter: int = 50_000) -> list[float]:
    """min 0.5·x'Qx + c'x  s.t. Σx = 1, 0 ≤ x ≤ cap (projected gradient)."""
    n = len(Q)
    L = max_eigenvalue(Q)
    step = 1.0 / L if L > 0 else 1.0
    x = _project_capped_simplex([1.0 / n] * n, cap)
    for _ in range(max_iter):
        grad = [g + ci for g, ci in zip(mat_vec(Q, x), c)]
        x_new = _project_capped_simplex([xi - step * gi for xi, gi in zip(x, grad)], cap)
        if math.sqrt(sum((a - b) ** 2 for a, b in zip(x, x_new))) < tol:
            return x_new
        x = x_new
    return x  # best effort after max_iter; deterministic regardless


def _check_inputs(sigma: list[list[float]], mu: list[float] | None,
                  max_weight: float) -> int:
    n = len(sigma)
    if n == 0 or any(len(r) != n for r in sigma):
        raise ValueError("sigma must be a non-empty square matrix")
    if mu is not None and len(mu) != n:
        raise ValueError("mu/sigma dimension mismatch")
    if not 0.0 < max_weight <= 1.0:
        raise ValueError("max_weight must be in (0, 1]")
    return n


def min_variance(sigma: list[list[float]], max_weight: float = 1.0) -> list[float]:
    """Global minimum-variance portfolio (long-only, capped)."""
    n = _check_inputs(sigma, None, max_weight)
    return _qp(sigma, [0.0] * n, max_weight)


def _gamma_max(sigma: list[list[float]], mu: list[float],
               max_weight: float) -> float:
    """Grow γ until the solution stops changing (frontier's top end)."""
    g, w_prev = 1.0, None
    for _ in range(60):
        w = _qp(sigma, [-g * m for m in mu], max_weight)
        if w_prev is not None and max(abs(a - b) for a, b in zip(w, w_prev)) < 1e-9:
            return g
        w_prev, g = w, g * 2.0
    return g


def efficient_frontier(sigma: list[list[float]], mu: list[float],
                       max_weight: float = 1.0, n_points: int = 25,
                       risk_free: float = 0.0) -> list[dict]:
    """Trace the long-only efficient frontier by sweeping risk aversion γ.

    Returns one dict per γ: gamma, weights, expected_return, volatility,
    sharpe (all in the input returns' per-period units).
    """
    n = _check_inputs(sigma, mu, max_weight)
    g_max = _gamma_max(sigma, mu, max_weight)
    lo = math.log10(g_max) - 4.0
    points = []
    for k in range(n_points):
        g = 10.0 ** (lo + (math.log10(g_max) - lo) * k / max(n_points - 1, 1))
        w = _qp(sigma, [-g * m for m in mu], max_weight)
        er = dot(w, mu)
        vol = math.sqrt(dot(w, mat_vec(sigma, w)))
        points.append({
            "gamma": g,
            "weights": w,
            "expected_return": er,
            "volatility": vol,
            "sharpe": (er - risk_free) / vol if vol > 0 else 0.0,
        })
    return points


def max_sharpe(sigma: list[list[float]], mu: list[float],
               risk_free: float = 0.0, max_weight: float = 1.0) -> list[float]:
    """Long-only tangency portfolio: the max-Sharpe point on the frontier."""
    n = _check_inputs(sigma, mu, max_weight)
    best = max(efficient_frontier(sigma, mu, max_weight, n_points=60,
                                  risk_free=risk_free),
               key=lambda p: p["sharpe"])
    return best["weights"]


def risk_parity(sigma: list[list[float]], max_weight: float = 1.0,
                tol: float = 1e-8, max_iter: int = 5_000) -> list[float]:
    """Equal risk contribution portfolio (damped fixed-point iteration).

    Iterates wᵢ ← wᵢ·σₚ²/(n·(Σw)ᵢ) toward wᵢ(Σw)ᵢ = σₚ²/n, renormalizing to
    the capped simplex each step.  Simpler than Spinu's CCD but converges
    reliably on well-conditioned covariances.
    """
    n = _check_inputs(sigma, None, max_weight)
    w = [1.0 / n] * n
    for _ in range(max_iter):
        sw = mat_vec(sigma, w)
        var = dot(w, sw)
        target = var / n
        w_new = [wi * (1 - 0.5) + 0.5 * target / s if s > 0 else wi
                 for wi, s in zip(w, sw)]
        w_new = _project_capped_simplex(w_new, max_weight)
        rc = [wi * s for wi, s in zip(w_new, mat_vec(sigma, w_new))]
        if max(rc) - min(rc) < tol * var:
            return w_new
        w = w_new
    return w


def equal_weight(n: int, max_weight: float = 1.0) -> list[float]:
    """1/N baseline (respects the cap)."""
    if n <= 0:
        raise ValueError("n must be positive")
    return _project_capped_simplex([1.0 / n] * n, max_weight)


_METHODS = {
    "min_variance": min_variance,
    "max_sharpe": max_sharpe,
    "risk_parity": risk_parity,
}


def optimize(sigma: list[list[float]], mu: list[float] | None = None,
             method: str = "max_sharpe", risk_free: float = 0.0,
             max_weight: float = 1.0) -> list[float]:
    """Dispatcher: pick an optimizer by name."""
    if method == "equal_weight":
        return equal_weight(len(sigma), max_weight)
    if method not in _METHODS:
        raise ValueError(f"unknown method {method!r}; "
                         f"choose from {sorted(_METHODS) + ['equal_weight']}")
    if method in ("max_sharpe",) and mu is None:
        raise ValueError("max_sharpe needs expected returns mu")
    fn = _METHODS[method]
    if method == "max_sharpe":
        assert mu is not None
        return fn(sigma, mu, risk_free=risk_free, max_weight=max_weight)
    return fn(sigma, max_weight=max_weight)
