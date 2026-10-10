"""Deflated Sharpe Ratio (Bailey & López de Prado, 2014).

``"The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest
Overfitting and Non-Normality"``, Journal of Portfolio Management.

The honesty rule (trade-strategies ``docs/validation/GATES.md``):
``n_trials`` is the number of *screened* ideas in the research phase —
every trial that was run, not just the ones reported. Passing a subset
of trials silently deflates the multiple-testing correction and is the
exact failure mode this engine exists to prevent.
"""

from __future__ import annotations

import math

import numpy as np

from ._stats import _EULER_MASCHERONI, norm_cdf, norm_ppf

__all__ = [
    "expected_sharpe_null",
    "dsr",
    "dsr_from_returns",
    "moments",
]


def expected_sharpe_null(trial_sharpes):
    """Expected Sharpe under the null given K selection trials.

    SR0 = sqrt(V) * ((1 - gamma) * Phi^-1(1 - 1/K)
                     + gamma * Phi^-1(1 - 1/(K*e)))

    where V is the sample variance of the K trial Sharpe ratios and
    gamma is the Euler-Mascheroni constant. For K = 1 there is no
    selection bias and SR0 = 0.
    """
    sharpes = np.asarray(trial_sharpes, dtype=float).ravel()
    sharpes = sharpes[np.isfinite(sharpes)]
    k = sharpes.shape[0]
    if k == 0:
        raise ValueError("trial_sharpes must contain at least one finite value")
    if k == 1:
        return 0.0
    var = float(np.var(sharpes, ddof=1))
    if var <= 0.0:
        return 0.0
    g = _EULER_MASCHERONI
    term = (1.0 - g) * norm_ppf(1.0 - 1.0 / k) + g * norm_ppf(1.0 - 1.0 / (k * math.e))
    return math.sqrt(var) * float(term)


def dsr(sr_hat, trial_sharpes, n_obs, skew=0.0, kurt=3.0, periods_per_year=252):
    """Deflated Sharpe Ratio: P(true Sharpe > 0 | selection over trials).

    Parameters
    ----------
    sr_hat : float
        Annualised Sharpe ratio of the *selected* strategy.
    trial_sharpes : array-like
        Annualised Sharpe ratios of **every** trial screened in the
        research phase (the honesty rule — ``n_trials = len(trial_sharpes)``).
    n_obs : int
        Number of return observations behind ``sr_hat``.
    skew, kurt : float
        Sample skewness / kurtosis of the selected strategy's returns
        (Lo, 2002 non-normal standard error).
    periods_per_year : int
        Annualisation factor matching ``sr_hat``'s units.

    Returns the DSR in [0, 1]. Raises ``ValueError`` on invalid input
    (fail closed — a multiplicity correction must never silently
    degrade into an unadjusted test).
    """
    sr_hat = float(sr_hat)
    n_obs = int(n_obs)
    skew = float(skew)
    kurt = float(kurt)
    ppy = int(periods_per_year)
    if not np.isfinite(sr_hat):
        raise ValueError("sr_hat must be finite")
    if n_obs < 2:
        raise ValueError("n_obs must be >= 2")
    if ppy < 1:
        raise ValueError("periods_per_year must be >= 1")
    if not np.isfinite(skew) or not np.isfinite(kurt):
        raise ValueError("skew and kurt must be finite")

    sr0 = expected_sharpe_null(trial_sharpes)
    # Lo (2002) standard error, computed per-period then annualised.
    sr_d = sr_hat / math.sqrt(ppy)
    var_d = (1.0 - skew * sr_d + (kurt - 1.0) / 4.0 * sr_d**2) / n_obs
    if var_d <= 0.0:
        raise ValueError("non-positive Sharpe standard error — check skew/kurt")
    se = math.sqrt(var_d) * math.sqrt(ppy)
    return float(np.clip(norm_cdf((sr_hat - sr0) / se), 0.0, 1.0))


def moments(returns):
    """Sample (mean, stdev, skew, kurtosis) of a return series.

    Moment estimators (dividing by n); kurtosis is the conventional
    (non-excess) fourth standardised moment, so Normal => 3.0.
    """
    r = np.asarray(returns, dtype=float).ravel()
    r = r[np.isfinite(r)]
    n = r.shape[0]
    if n < 2:
        raise ValueError("need at least 2 finite observations")
    mean = float(r.mean())
    sd = float(r.std())
    if sd <= 0.0:
        raise ValueError("return series has zero variance")
    z = (r - mean) / sd
    return {
        "n": n,
        "mean": mean,
        "stdev": sd,
        "skew": float((z**3).mean()),
        "kurt": float((z**4).mean()),
    }


def dsr_from_returns(returns, trial_sharpes, periods_per_year=252):
    """DSR straight from a return series (moments estimated internally)."""
    m = moments(returns)
    ppy = int(periods_per_year)
    sr_hat = (m["mean"] / m["stdev"]) * math.sqrt(ppy)
    return dsr(
        sr_hat,
        trial_sharpes,
        m["n"],
        skew=m["skew"],
        kurt=m["kurt"],
        periods_per_year=ppy,
    )
