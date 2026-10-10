"""Tiny matrix toolkit: multiply, transpose, Gauss-Jordan inverse, solve.

Sized for factor work (a handful of regressors, dozens of assets) —
not for thousand-asset covariance matrices.  See METHODOLOGY for the
numerical caveats (normal equations, no pivoting beyond partial).
"""

from __future__ import annotations


def transpose(A: list[list[float]]) -> list[list[float]]:
    return [list(row) for row in zip(*A)]


def matmul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    n, m, p = len(A), len(B), len(B[0])
    return [[sum(A[i][k] * B[k][j] for k in range(m)) for j in range(p)]
            for i in range(n)]


def matvec(A: list[list[float]], x: list[float]) -> list[float]:
    return [sum(a * xi for a, xi in zip(row, x)) for row in A]


def identity(n: int) -> list[list[float]]:
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def inverse(A: list[list[float]]) -> list[list[float]]:
    """Gauss-Jordan with partial pivoting."""
    n = len(A)
    M = [row[:] + identity(n)[i] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-14:
            raise ValueError("singular matrix")
        M[col], M[piv] = M[piv], M[col]
        scale = M[col][col]
        M[col] = [v / scale for v in M[col]]
        for r in range(n):
            if r != col and M[r][col] != 0.0:
                factor = M[r][col]
                M[r] = [rv - factor * cv for rv, cv in zip(M[r], M[col])]
    return [row[n:] for row in M]


def solve(A: list[list[float]], b: list[float]) -> list[float]:
    return matvec(inverse(A), b)
