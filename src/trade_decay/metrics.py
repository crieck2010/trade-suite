"""Decay metrics for live strategies.

Pure functions over equity series.  The maths (annualization, the
log-linear half-life fit, drawdown) is derived in docs/METHODOLOGY.md;
this module is the implementation.

Conventions
-----------
* Inputs are equity series: ``[(datetime, equity)]`` in ascending time
  order, as produced by :class:`trade_decay.ledger.LedgerReader`.
* Series are resampled to **daily** (last snapshot of each day) before
  any return-based metric, so irregular intraday snapshot cadences do
  not distort annualization.
* Returns are simple (not log) returns.
* ``float("nan")`` means "not computable" (too few points, zero
  variance); callers treat NaN as missing, never as zero.

Stdlib + numpy only.  No I/O, no network, no broker code.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

#: Trading days per year used to annualize Sharpe ratios.
TRADING_DAYS_PER_YEAR = 252


# ---------------------------------------------------------------------------
# series helpers
# ---------------------------------------------------------------------------

def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resample_daily(series: list[tuple]) -> list[tuple]:
    """Resample ``[(datetime, equity)]`` to one point per UTC day.

    Keeps the **last** snapshot of each day (the most informed mark).
    Days with non-positive or non-finite equity are dropped -- a ledger
    row with equity <= 0 is corrupt data, not a return of -100%.
    """
    by_day: dict = {}
    for ts, equity in series:
        try:
            value = float(equity)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value <= 0:
            continue
        day = _as_datetime(ts).date().isoformat()
        by_day[day] = (_as_datetime(ts), value)  # last write wins
    return [by_day[day] for day in sorted(by_day)]


def daily_returns(daily: list[tuple]) -> np.ndarray:
    """Simple returns ``eq[i]/eq[i-1] - 1`` for a daily equity series."""
    eq = np.array([e for _, e in daily], dtype=float)
    if len(eq) < 2:
        return np.array([], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        rets = eq[1:] / eq[:-1] - 1.0
    return rets[np.isfinite(rets)]


# ---------------------------------------------------------------------------
# Sharpe
# ---------------------------------------------------------------------------

def sharpe_ratio(returns: np.ndarray,
                 periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """Annualized Sharpe ratio (risk-free rate assumed 0).

    Returns NaN when there are fewer than 2 finite returns or zero
    variance -- a flat line has no measurable Sharpe, not a Sharpe
    of zero.
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return float("nan")
    sd = float(r.std(ddof=1))
    if sd == 0:
        return float("nan")
    return float(r.mean() / sd * math.sqrt(periods_per_year))


def trailing_sharpe(daily: list[tuple], window_days: int = 60) -> float:
    """Sharpe over the last ``window_days`` of daily data."""
    window = daily[-window_days:] if window_days > 0 else daily
    return sharpe_ratio(daily_returns(window))


def rolling_sharpe(daily: list[tuple],
                   window_days: int = 30) -> list[tuple]:
    """``[(date_iso, sharpe)]``: Sharpe of each trailing window.

    One point per day once ``window_days`` of history exist.  Windows
    whose Sharpe is NaN are skipped -- gaps are honest, interpolation
    would invent precision.
    """
    out = []
    for i in range(window_days, len(daily) + 1):
        window = daily[i - window_days:i]
        s = sharpe_ratio(daily_returns(window))
        if math.isfinite(s):
            out.append((daily[i - 1][0].date().isoformat(), s))
    return out


def divergence_zscore(trailing: float, expected: float,
                      expected_std: float | None) -> float | None:
    """How far trailing performance sits from the validation expectation.

    ``(trailing - expected) / expected_std``.  Returns ``None`` when no
    dispersion was recorded at validation time -- a z-score without a
    denominator is a guess, so the engine skips it instead of
    inventing one.
    """
    if expected_std is None or not math.isfinite(expected_std) \
            or expected_std <= 0:
        return None
    if not math.isfinite(trailing) or not math.isfinite(expected):
        return None
    return float((trailing - expected) / expected_std)


# ---------------------------------------------------------------------------
# half-life of a decaying edge
# ---------------------------------------------------------------------------

def fit_half_life(rolling: list[tuple],
                  min_points: int = 10) -> dict:
    """Fit exponential decay to a rolling-Sharpe series.

    Model: ``S(t) = S0 * exp(-t / tau)``, fit by log-linear regression
    of ``ln(S)`` on ``t`` (days).  Only strictly positive Sharpe points
    participate -- a decay-to-zero model has nothing to say about
    negative prints, which are regime breaks, not decay.

    Returns ``{"half_life_days", "tau_days", "r_squared", "n_points",
    "decaying"}``.  ``half_life_days`` is ``inf`` when the fitted slope
    is non-negative (the edge is *not* decaying -- flat or improving)
    and ``None`` when there are too few positive points to fit.

    Derivation and worked example: docs/METHODOLOGY.md.
    """
    pts = []
    for date_iso, s in rolling:
        if math.isfinite(s) and s > 0:
            pts.append((date_iso, s))
    if len(pts) < min_points:
        return {"half_life_days": None, "tau_days": None,
                "r_squared": None, "n_points": len(pts),
                "decaying": None}

    t0 = datetime.fromisoformat(pts[0][0])
    t = np.array([(datetime.fromisoformat(d) - t0).days
                  for d, _ in pts], dtype=float)
    y = np.log(np.array([s for _, s in pts], dtype=float))

    # Guard: all points on the same day -> no time axis to fit.
    if float(t.max() - t.min()) <= 0:
        return {"half_life_days": None, "tau_days": None,
                "r_squared": None, "n_points": len(pts),
                "decaying": None}

    slope, intercept = np.polyfit(t, y, 1)
    y_hat = slope * t + intercept
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    if slope >= 0:
        return {"half_life_days": float("inf"), "tau_days": float("inf"),
                "r_squared": float(r_squared), "n_points": len(pts),
                "decaying": False}

    tau = float(-1.0 / slope)
    return {"half_life_days": float(tau * math.log(2)),
            "tau_days": tau,
            "r_squared": float(r_squared),
            "n_points": len(pts),
            "decaying": True}


# ---------------------------------------------------------------------------
# drawdown
# ---------------------------------------------------------------------------

def max_drawdown(daily: list[tuple]) -> dict:
    """Maximum peak-to-trough drawdown of a daily equity series.

    Returns ``{"max_dd" (fraction, positive), "peak_date",
    "trough_date", "current_dd"}``.  Empty for series shorter than 2
    points (``max_dd`` NaN).
    """
    if len(daily) < 2:
        return {"max_dd": float("nan"), "peak_date": None,
                "trough_date": None, "current_dd": float("nan")}
    eq = np.array([e for _, e in daily], dtype=float)
    running_peak = np.maximum.accumulate(eq)
    dd = 1.0 - eq / running_peak
    i = int(np.argmax(dd))
    peak_i = int(np.argmax(eq[:i + 1]))
    peak = float(running_peak[-1])
    current_dd = float(1.0 - eq[-1] / peak) if peak > 0 else 0.0
    return {
        "max_dd": float(dd[i]),
        "peak_date": daily[peak_i][0].date().isoformat(),
        "trough_date": daily[i][0].date().isoformat(),
        "current_dd": float(current_dd),
    }
