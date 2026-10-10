"""Holm step-down procedure (Holm, 1979).

``"A Simple Sequentially Rejective Multiple Test Procedure"``,
Scandinavian Journal of Statistics 6(2).

The conservative baseline of the package: given one p-value per trial
(e.g. one-sided t-tests of each trial's mean excess return), Holm
controls the family-wise error rate at ``alpha`` with strictly more
power than Bonferroni, and no dependence assumptions at all. Use it as
the "at minimum, this" comparison next to the DSR / Reality Check / SPA
results.
"""

from __future__ import annotations

import numpy as np

from ._stats import one_sided_t_pvalue

__all__ = ["holm", "t_test_pvalues"]


def holm(p_values, alpha=0.05):
    """Holm step-down multiple testing correction.

    Sorts the p-values ascending and rejects H_(i) while
    ``p_(i) <= alpha / (m - i + 1)``, stopping at the first failure.
    Returns a plain-data dict with per-trial ``reject`` flags (in the
    *input* order), Holm-adjusted p-values, ``n_rejected`` and the
    per-trial ``verdict`` (``"validated"`` for rejected nulls,
    ``"invalidated"`` otherwise).
    """
    p = np.asarray(p_values, dtype=float).ravel()
    m = p.shape[0]
    if m == 0:
        raise ValueError("p_values must be non-empty")
    if not np.all(np.isfinite(p)) or np.any((p < 0.0) | (p > 1.0)):
        raise ValueError("p_values must be finite probabilities in [0, 1]")
    alpha = float(alpha)
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")

    order = np.argsort(p, kind="stable")
    ps = p[order]
    reject_sorted = np.zeros(m, dtype=bool)
    for i in range(m):
        if ps[i] <= alpha / (m - i):
            reject_sorted[i] = True
        else:
            break
    # Holm-adjusted p-values: max over j<=i of min(1, (m-j+1) * p_(j)).
    adj_sorted = np.minimum.accumulate(
        np.minimum(1.0, (m - np.arange(m)) * ps)[::-1]
    )[::-1]
    adj_sorted = np.maximum.accumulate(adj_sorted)

    reject = np.zeros(m, dtype=bool)
    adjusted = np.zeros(m)
    reject[order] = reject_sorted
    adjusted[order] = adj_sorted
    return {
        "test": "holm",
        "reject": [bool(x) for x in reject],
        "p_adjusted": [float(x) for x in adjusted],
        "n_rejected": int(reject.sum()),
        "n_trials": m,
        "alpha": alpha,
        "verdicts": [
            "validated" if x else "invalidated" for x in reject
        ],
    }


def t_test_pvalues(returns, benchmark=None):
    """One-sided p-values (H1: mean excess return > 0) per trial.

    Normal approximation to the t-statistic; fine asymptotically and for
    the n >= ~30 backtests this package targets. Feed the result into
    :func:`holm`. For exact small-sample inference prefer the bootstrap
    tests (Reality Check / SPA).
    """
    r = np.asarray(returns, dtype=float)
    if r.ndim == 1:
        r = r[:, None]
    if r.ndim != 2 or not np.all(np.isfinite(r)):
        raise ValueError("returns must be a finite 1-D or 2-D array")
    n, k = r.shape
    if n < 2:
        raise ValueError("need at least 2 observations")
    if benchmark is None:
        b = np.zeros(n)
    else:
        b = np.asarray(benchmark, dtype=float).ravel()
        if b.shape[0] != n or not np.all(np.isfinite(b)):
            raise ValueError("benchmark must be finite with length n_obs")
    f = r - b[:, None]
    out = []
    for j in range(k):
        col = f[:, j]
        se = float(col.std(ddof=1) / np.sqrt(n))
        out.append(one_sided_t_pvalue(float(col.mean()), se, n))
    return out
