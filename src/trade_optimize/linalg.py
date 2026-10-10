"""Pure-Python linear algebra for the optimizer.

Matrices are lists of lists (row-major); vectors are lists of floats.
No third-party dependencies.  These routines are intentionally small and
auditable — the optimizer's correctness rests on them.
"""

from __future__ import annotations

import math


def _check_square(A: list[list[float]]) -> int:
    n = len(A)
    if n == 0 or any(len(row) != n for row in A):
        raise ValueError("expected a non-empty square matrix")
    return n


def transpose(A: list[list[float]]) -> list[list[float]]:
    return [list(col) for col in zip(*A)]


def mat_vec(A: list[list[float]], x: list[float]) -> list[float]:
    if any(len(row) != len(x) for row in A):
        raise ValueError("matrix/vector dimension mismatch")
    return [sum(a * xi for a, xi in zip(row, x)) for row in A]


def mat_mat(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    if not A or not B or len(A[0]) != len(B):
        raise ValueError("matrix dimension mismatch")
    Bt = transpose(B)
    return [[sum(a * b for a, b in zip(row, col)) for col in Bt] for row in A]


def dot(x: list[float], y: list[float]) -> float:
    return sum(a * b for a, b in zip(x, y))


def cholesky(A: list[list[float]]) -> list[list[float]]:
    """Lower-triangular L with A = L·Lᵀ.  Raises if A is not positive-definite."""
    n = _check_square(A)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                v = A[i][i] - s
                if v <= 0:
                    raise ValueError("matrix is not positive-definite")
                L[i][j] = math.sqrt(v)
            else:
                L[i][j] = (A[i][j] - s) / L[j][j]
    return L


def _forward(L: list[list[float]], b: list[float]) -> list[float]:
    n = len(L)
    y = [0.0] * n
    for i in range(n):
        y[i] = (b[i] - sum(L[i][k] * y[k] for k in range(i))) / L[i][i]
    return y


def _back(U: list[list[float]], y: list[float]) -> list[float]:
    n = len(U)
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (y[i] - sum(U[i][k] * x[k] for k in range(i + 1, n))) / U[i][i]
    return x


def solve(A: list[list[float]], b: list[float]) -> list[float]:
    """Solve A·x = b for positive-definite A (via Cholesky)."""
    L = cholesky(A)
    return _back(transpose(L), _forward(L, b))


def invert(A: list[list[float]]) -> list[list[float]]:
    """Matrix inverse via Gauss-Jordan with partial pivoting."""
    n = _check_square(A)
    M = [row[:] + [1.0 if i == j else 0.0 for j in range(n)]
         for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-15:
            raise ValueError("matrix is singular")
        M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        M[col] = [v / pv for v in M[col]]
        for r in range(n):
            if r != col:
                f = M[r][col]
                M[r] = [rv - f * cv for rv, cv in zip(M[r], M[col])]
    return [row[n:] for row in M]


def max_eigenvalue(A: list[list[float]], iters: int = 200) -> float:
    """Largest eigenvalue by power iteration (for QP step-size choice)."""
    n = _check_square(A)
    x = [1.0 / math.sqrt(n)] * n
    for _ in range(iters):
        y = mat_vec(A, x)
        nrm = math.sqrt(dot(y, y))
        if nrm == 0:
            return 0.0
        x = [v / nrm for v in y]
    return dot(x, mat_vec(A, x))
