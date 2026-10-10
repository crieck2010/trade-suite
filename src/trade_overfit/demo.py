"""Seeded synthetic data: a true edge vs N noise strategies.

The money demo: with N=1000 noise strategies and one year of data, the best
in-sample Sharpe looks spectacular (~3) — and the DSR kills it, because under
the null of no skill the expected best-of-1000 is also ~3.
"""

from __future__ import annotations

import random

from .dsr import deflated_sharpe_ratio, expected_sharpe_under_null
from ._stats import excess_kurtosis, skewness
from .metrics import sharpe_ratio


def demo_true_edge(n: int = 1260, seed: int = 7, mu: float = 0.001,
                   sigma: float = 0.008) -> list[float]:
    """A genuinely skilled strategy: daily N(mu, sigma).

    Defaults give annualized Sharpe ~2.0 over 5 years with max drawdown
    inside the desk's 15% gate — the "honest winner" the desk should PASS.
    (Default mu was raised from 0.0008 in v0.2.0: the 7-gate set is strictly
    harder than the 5-gate set the old default was calibrated against, and
    the demo's documented contract is that a genuine edge survives the desk.)
    """
    rng = random.Random(seed)
    return [rng.gauss(mu, sigma) for _ in range(n)]


def demo_noise_strategies(n_strategies: int = 1000, n: int = 252,
                          seed: int = 7, sigma: float = 0.01) -> list[list[float]]:
    """N zero-mean noise strategies — pure luck, no edge whatsoever."""
    rng = random.Random(seed)
    return [[rng.gauss(0.0, sigma) for _ in range(n)] for _ in range(n_strategies)]


def demo_selection_bias(n_strategies: int = 1000, n: int = 252,
                        seed: int = 7, sigma: float = 0.01) -> dict:
    """Run the selection-bias demo end to end.

    Returns the trial Sharpes, the in-sample winner, its (inflated) Sharpe,
    the expected best-of-N under the null, and the winner's DSR.
    """
    strategies = demo_noise_strategies(n_strategies, n, seed, sigma)
    trial_sharpes = [sharpe_ratio(s) or 0.0 for s in strategies]
    best_idx = max(range(n_strategies), key=lambda i: trial_sharpes[i])
    best_sr = trial_sharpes[best_idx]
    sr0 = expected_sharpe_under_null(trial_sharpes)
    # Use the winner's own skew/kurtosis, exactly as validate() does, so the
    # demo DSR and the desk-gate DSR agree.
    winner = strategies[best_idx]
    sk = skewness(winner) or 0.0
    ke = excess_kurtosis(winner) or 0.0
    dsr = deflated_sharpe_ratio(best_sr, n, trial_sharpes, sk, ke)
    return {
        "n_strategies": n_strategies,
        "n_obs": n,
        "seed": seed,
        "trial_sharpes": trial_sharpes,
        "best_idx": best_idx,
        "best_in_sample_sharpe": best_sr,
        "best_skewness": sk,
        "best_excess_kurtosis": ke,
        "expected_sharpe_under_null": sr0,
        "best_dsr": dsr,
        # "Killed" = fails the desk's standard DSR gate (0.95). The winner's
        # DSR sits well below it: a 3+ Sharpe the desk cannot confidently
        # distinguish from the luckiest of 1000 coin flips does not ship.
        "killed": dsr is not None and dsr < 0.95,
    }
