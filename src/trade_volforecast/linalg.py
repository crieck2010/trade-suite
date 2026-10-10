"""Tiny linear-algebra helpers (stdlib-only).

Just enough for OLS normal equations and small symmetric solves:
matrix multiply, transpose, and Gaussian elimination with partial
pivoting.  Nothing here is meant for large systems — HAR regressions
are 4x4.
"""

from __future__ import annotations


def transpose(A: list[list[float]]) -> list[list[float]]:
    return [list(row) for row in zip(*A)]


def matvec(A: list[list[float]], x: list[float]) -> list[float]:
    return [sum(a * xi for a, xi in zip(row, x)) for row in A]


def matmul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    Bt = transpose(B)
    return [[sum(a * b for a, b in zip(row, col)) for col in Bt] for row in A]


def solve(A: list[list[float]], b: list[float]) -> list[float]:
    """Solve A x = b by Gaussian elimination with partial pivoting."""
    n = len(A)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-14:
            raise ValueError("singular matrix in solve()")
        M[col], M[piv] = M[piv], M[col]
        for row in range(col + 1, n):
            factor = M[row][col] / M[col][col]
            for k in range(col, n + 1):
                M[row][k] -= factor * M[col][k]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))) / M[i][i]
    return x


def ols_fit(X: list[list[float]], y: list[float]) -> dict:
    """Ordinary least squares via the normal equations.

    Returns coefficients, residuals, R², and the residual variance.
    """
    Xt = transpose(X)
    XtX = matmul(Xt, X)
    Xty = matvec(Xt, y)
    beta = solve(XtX, Xty)
    resid = [yi - sum(b * xi for b, xi in zip(beta, row)) for yi, row in zip(y, X)]
    n, k = len(y), len(beta)
    ss_res = sum(r * r for r in resid)
    mean_y = sum(y) / n
    ss_tot = sum((yi - mean_y) ** 2 for yi in y)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {
        "beta": beta,
        "residuals": resid,
        "r_squared": r2,
        "sigma2": ss_res / max(n - k, 1),
        "n": n,
        "k": k,
    }
