"""Nelder-Mead downhill simplex (stdlib-only).

Used for GARCH / GJR-GARCH maximum-likelihood estimation, where the
likelihood surface is smooth but constrained.  Constraints are handled
by the caller via parameter transforms (see garch.py), so the
optimizer itself works on an unconstrained space.
"""

from __future__ import annotations


def nelder_mead(
    fn,
    x0: list[float],
    step: float = 0.1,
    max_iter: int = 2000,
    tol: float = 1e-8,
) -> dict:
    """Minimize ``fn`` starting from ``x0``.

    Returns the best point, function value, iteration count, and a
    convergence flag.
    """
    n = len(x0)
    alpha, gamma, rho, sigma = 1.0, 2.0, 0.5, 0.5  # reflection/expansion/contraction/shrink
    simplex = [list(x0)]
    for i in range(n):
        p = list(x0)
        p[i] += step * (1.0 + abs(x0[i]))
        simplex.append(p)
    fvals = [fn(p) for p in simplex]

    it = 0
    converged = False
    for it in range(1, max_iter + 1):
        order = sorted(range(n + 1), key=lambda i: fvals[i])
        simplex = [simplex[i] for i in order]
        fvals = [fvals[i] for i in order]
        # convergence: spread of function values at the simplex
        if max(fvals) - min(fvals) < tol:
            converged = True
            break
        centroid = [sum(simplex[i][j] for i in range(n)) / n for j in range(n)]
        worst = simplex[n]

        def _point(c):
            return [centroid[j] + c * (centroid[j] - worst[j]) for j in range(n)]

        xr, fr = _point(alpha), None
        fr = fn(xr)
        if fvals[0] <= fr < fvals[n - 1]:
            simplex[n], fvals[n] = xr, fr
            continue
        if fr < fvals[0]:
            xe, fe = _point(gamma), None
            fe = fn(xe)
            if fe < fr:
                simplex[n], fvals[n] = xe, fe
            else:
                simplex[n], fvals[n] = xr, fr
            continue
        # contraction
        xc = _point(rho if fr < fvals[n] else -rho)
        fc = fn(xc)
        if fc < min(fr, fvals[n]):
            simplex[n], fvals[n] = xc, fc
            continue
        # shrink
        best = simplex[0]
        for i in range(1, n + 1):
            simplex[i] = [best[j] + sigma * (simplex[i][j] - best[j]) for j in range(n)]
            fvals[i] = fn(simplex[i])

    order = sorted(range(n + 1), key=lambda i: fvals[i])
    return {
        "x": simplex[order[0]],
        "fun": fvals[order[0]],
        "n_iter": it,
        "converged": converged,
    }
