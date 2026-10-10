"""Hansen's SPA test (Hansen, 2005).

``"A Test for Superior Predictive Ability"``, Journal of Business &
Economic Statistics 23(4).

A consistent improvement over White's Reality Check: the test statistic
is *studentised* (each trial scaled by its own long-run standard
error), floored at zero, and poor trials are discarded from the
bootstrap distribution via Hansen's recentering. The result is a test
with better power that remains consistent when some — but not all —
trials are worthless.
"""

from __future__ import annotations

import math

import numpy as np

from ._stats import newey_west_long_run_variance, stationary_bootstrap_indices

__all__ = ["spa_test"]


def spa_test(returns, benchmark=None, n_boot=1000, block_len=None,
             seed=0, alpha=0.05, nw_lags=None):
    """Hansen's Superior Predictive Ability test.

    Same inputs and return contract as
    :func:`trade_multitest.reality_check.reality_check`, plus:

    nw_lags : int, optional
        Newey-West lag for the long-run variance of each trial's excess
        returns. Defaults to ``floor(4 * (n/100)^(2/9))``.

    The returned dict carries ``test="hansen_spa"``,
    ``studentised_statistic``, the ``recentering_threshold``
    ``sqrt(2 log log n)``, per-trial ``t_stats``, and the round-level
    ``verdict`` (``"validated"`` / ``"invalidated"`` at ``alpha``).
    """
    r = np.asarray(returns, dtype=float)
    if r.ndim == 1:
        r = r[:, None]
    if r.ndim != 2:
        raise ValueError("returns must be 1-D or 2-D")
    if not np.all(np.isfinite(r)):
        raise ValueError("returns must be finite")
    n, k = r.shape
    if n < 8 or k < 1:
        raise ValueError("SPA needs n_obs >= 8 and at least one trial")
    n_boot = int(n_boot)
    if n_boot < 100:
        raise ValueError("n_boot must be >= 100 for a usable p-value")
    alpha = float(alpha)
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")

    if benchmark is None:
        b = np.zeros(n)
    else:
        b = np.asarray(benchmark, dtype=float).ravel()
        if b.shape[0] != n or not np.all(np.isfinite(b)):
            raise ValueError("benchmark must be finite with length n_obs")

    f = r - b[:, None]
    dbar = f.mean(axis=0)
    omega = np.array([
        math.sqrt(newey_west_long_run_variance(f[:, j], nw_lags) / n)
        for j in range(k)
    ])
    if np.any(omega <= 0.0):
        raise ValueError("degenerate trial: zero long-run variance")
    t_stats = np.sqrt(n) * dbar / omega
    stat = float(max(0.0, np.max(t_stats)))
    best_trial = int(np.argmax(t_stats))

    # Hansen's recentering: keep trials with t_k >= -sqrt(2 log log n).
    c = math.sqrt(2.0 * math.log(math.log(n)))
    mu_c = dbar * (t_stats >= -c)

    if block_len is None:
        block_len = max(1, round(n ** (1.0 / 3.0)))
    idx = stationary_bootstrap_indices(n, block_len, n_boot, seed)
    fboot = f[idx]
    dbar_star = fboot.mean(axis=1)
    stat_star = np.maximum(
        0.0, np.max(np.sqrt(n) * (dbar_star - mu_c[None, :]) / omega[None, :], axis=1)
    )
    p_value = float((1.0 + np.sum(stat_star > stat)) / (n_boot + 1.0))

    return {
        "test": "hansen_spa",
        "p_value": p_value,
        "studentised_statistic": stat,
        "best_trial": best_trial,
        "t_stats": [float(t) for t in t_stats],
        "recentering_threshold": c,
        "n_trials": k,
        "n_obs": n,
        "n_boot": n_boot,
        "block_len": float(block_len),
        "alpha": alpha,
        "verdict": "validated" if p_value < alpha else "invalidated",
    }
