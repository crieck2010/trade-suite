"""White's Reality Check (White, 2000).

``"A Reality Check for Data Snooping"``, Econometrica 68(5).

Tests the composite null that *no* strategy in a screened set beats the
benchmark, correcting for the data-snooping bias that comes from
selecting the best-looking trial after the fact. The p-value comes from
the stationary bootstrap (Politis & Romano, 1994).
"""

from __future__ import annotations

import numpy as np

from ._stats import stationary_bootstrap_indices

__all__ = ["reality_check"]


def _as_2d(returns):
    r = np.asarray(returns, dtype=float)
    if r.ndim == 1:
        r = r[:, None]
    if r.ndim != 2:
        raise ValueError("returns must be 1-D or 2-D")
    if not np.all(np.isfinite(r)):
        raise ValueError("returns must be finite")
    return r


def reality_check(returns, benchmark=None, n_boot=1000, block_len=None,
                  seed=0, alpha=0.05):
    """White's Reality Check across a set of strategy trials.

    Parameters
    ----------
    returns : (n_obs, n_trials) array-like
        Per-period returns of every screened trial (all of them — the
        honesty rule applies here exactly as in the DSR).
    benchmark : (n_obs,) array-like, optional
        Benchmark returns; the tested quantity is the mean *excess*
        return of each trial over the benchmark. Defaults to zeros.
    n_boot : int
        Stationary-bootstrap replications.
    block_len : float, optional
        Mean bootstrap block length; defaults to ``round(n_obs ** (1/3))``.
    seed : int
        Bootstrap RNG seed (results are reproducible).
    alpha : float
        Significance level for the round-level verdict.

    Returns a plain-data dict with ``p_value``, ``statistic``,
    ``best_trial`` (index of the max excess-mean trial), ``n_boot``,
    ``block_len``, ``alpha`` and ``verdict`` — ``"validated"`` when the
    null is rejected (at least one trial genuinely beats the benchmark),
    ``"invalidated"`` otherwise — an invalidated round is evidence, not an execution.
    """
    r = _as_2d(returns)
    n, k = r.shape
    if n < 2 or k < 1:
        raise ValueError("need n_obs >= 2 and at least one trial")
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

    f = r - b[:, None]                      # excess returns
    fbar = f.mean(axis=0)
    stat = float(np.sqrt(n) * np.max(fbar))
    best_trial = int(np.argmax(fbar))

    if block_len is None:
        block_len = max(1, round(n ** (1.0 / 3.0)))
    idx = stationary_bootstrap_indices(n, block_len, n_boot, seed)
    fboot = f[idx]                          # (n_boot, n, k)
    fbar_star = fboot.mean(axis=1)
    # Recentered under the null: E*[fbar*] = fbar.
    stat_star = np.sqrt(n) * np.max(fbar_star - fbar[None, :], axis=1)
    p_value = float((1.0 + np.sum(stat_star >= stat)) / (n_boot + 1.0))

    return {
        "test": "white_reality_check",
        "p_value": p_value,
        "statistic": stat,
        "best_trial": best_trial,
        "best_trial_mean_excess": float(fbar[best_trial]),
        "n_trials": k,
        "n_obs": n,
        "n_boot": n_boot,
        "block_len": float(block_len),
        "alpha": alpha,
        "verdict": "validated" if p_value < alpha else "invalidated",
    }
