"""Deflated Sharpe Ratio (Bailey & de Prado, 2014) — the centerpiece.

The DSR answers: "given that I tried N strategies and picked the best,
what is the probability its true Sharpe exceeds zero?" It deflates the
in-sample Sharpe by the expected best-of-N under the null of no skill.
"""

from __future__ import annotations

import math

from ._stats import excess_kurtosis, normal_cdf, norm_ppf, sample_variance, skewness
from .metrics import sharpe_ratio

EULER_MASCHERONI = 0.5772156649


def psr(sharpe_hat: float, sharpe_star: float, n_obs: int,
        skew: float = 0.0, kurt_excess: float = 0.0) -> float | None:
    """Probabilistic Sharpe Ratio: P(true SR > sharpe_star | observed sharpe_hat).

    PSR(SR*) = Phi( (SR_hat - SR*) * sqrt(T-1)
                    / sqrt(1 - skew*SR_hat + (kurt_excess/4) * SR_hat^2) )

    Returns None when n_obs < 2 (undefined).
    """
    if n_obs < 2:
        return None
    num = (sharpe_hat - sharpe_star) * math.sqrt(n_obs - 1)
    den_sq = 1.0 - skew * sharpe_hat + (kurt_excess / 4.0) * sharpe_hat ** 2
    den = math.sqrt(max(den_sq, 1e-12))
    return normal_cdf(num / den)


def expected_sharpe_under_null(trial_sharpes: list[float]) -> float:
    """Expected best-of-N Sharpe under the null of no skill (SR_0).

    SR_0 = sqrt(V_hat) * ((1 - gamma) * PhiInv(1 - 1/N)
                          + gamma * PhiInv(1 - 1/(N*e)))

    with gamma = Euler-Mascheroni, V_hat = variance of the N trial Sharpes.
    N = 1  ->  0.0 (a single trial has no selection bias to deflate).
    """
    n = len(trial_sharpes)
    if n <= 1:
        return 0.0
    var = sample_variance(trial_sharpes)
    if var is None or var <= 0.0:
        return 0.0
    g = EULER_MASCHERONI
    term = (1.0 - g) * norm_ppf(1.0 - 1.0 / n) + g * norm_ppf(1.0 - 1.0 / (n * math.e))
    return math.sqrt(var) * term


def deflated_sharpe_ratio(sharpe_hat: float, n_obs: int,
                          trial_sharpes: list[float],
                          skew: float = 0.0,
                          kurt_excess: float = 0.0) -> float | None:
    """DSR = PSR(SR_0): probability the strategy's true Sharpe exceeds the
    expected best-of-N-trials Sharpe under the null.

    ``trial_sharpes`` is the list of in-sample Sharpes of every strategy tried
    (including the winner). With a single trial this collapses to PSR(0).
    Returns None when n_obs < 2.
    """
    sr0 = expected_sharpe_under_null(trial_sharpes)
    return psr(sharpe_hat, sr0, n_obs, skew, kurt_excess)


def dsr_from_returns(returns: list[float], trial_sharpes: list[float] | None = None,
                     rf_annual: float = 0.0, periods: int = 252) -> dict:
    """Convenience wrapper: compute everything from a returns series.

    When ``trial_sharpes`` is omitted it defaults to ``[sharpe]`` (N = 1),
    i.e. no selection-bias correction.
    """
    sr = sharpe_ratio(returns, rf_annual, periods)
    sk = skewness(returns) or 0.0
    ke = excess_kurtosis(returns) or 0.0
    trials = list(trial_sharpes) if trial_sharpes else ([sr] if sr is not None else [])
    dsr = deflated_sharpe_ratio(sr, len(returns), trials, sk, ke) if sr is not None else None
    return {
        "sharpe_hat": sr,
        "n_obs": len(returns),
        "n_trials": len(trials),
        "skewness": sk,
        "excess_kurtosis": ke,
        "expected_sharpe_under_null": expected_sharpe_under_null(trials),
        "dsr": dsr,
    }
