"""Realized-volatility estimators from OHLC bars.

All estimators work on log prices and return *variances* over the
sample window; multiply by ``annualize`` (default 252 trading days) and
take the square root for annualized volatility.

Estimators, in order of statistical efficiency:

- ``close_to_close`` — Σ r²; needs closes only, wastes intraday info.
- ``parkinson`` — uses the high-low range; ~5x more efficient than
  close-to-close under ideal diffusion (Parkinson, 1980).
- ``garman_klass`` — adds open/close; ~7x efficiency (Garman & Klass,
  1980).
- ``rogers_satchell`` — drift-robust range estimator (Rogers &
  Satchell, 1991).
- ``yang_zhang`` — combines overnight, close-to-open, and
  Rogers-Satchell pieces; handles jumps and drift, the default choice
  (Yang & Zhang, 2000).

Bars are plain dicts with ``open``/``high``/``low``/``close`` keys —
the same shape the dashboards pass around.
"""

from __future__ import annotations

import math

_LOG2 = math.log(2.0)


def _logs(bar: dict) -> tuple[float, float, float, float]:
    o, h, l, c = (bar["open"], bar["high"], bar["low"], bar["close"])
    if min(o, h, l, c) <= 0:
        raise ValueError("OHLC values must be positive for log estimators")
    return math.log(o), math.log(h), math.log(l), math.log(c)


def log_returns(bars: list[dict]) -> list[float]:
    """Close-to-close log returns."""
    closes = [b["close"] for b in bars]
    if any(c <= 0 for c in closes):
        raise ValueError("close prices must be positive")
    return [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]


def close_to_close(bars: list[dict]) -> float:
    """Realized variance from close-to-close log returns (Σ r²)."""
    rets = log_returns(bars)
    if not rets:
        raise ValueError("need at least 2 bars")
    return sum(r * r for r in rets)


def parkinson(bars: list[dict]) -> float:
    """Parkinson (1980) range variance: (1 / 4 ln 2) · Σ ln(H/L)²."""
    if len(bars) < 1:
        raise ValueError("need at least 1 bar")
    total = 0.0
    for b in bars:
        _, h, l, _ = _logs(b)
        total += (h - l) ** 2
    return total / (4.0 * _LOG2)


def garman_klass(bars: list[dict]) -> float:
    """Garman-Klass (1980) variance.

    Σ [ ½·ln(H/L)² − (2 ln 2 − 1)·ln(C/O)² ]
    """
    if len(bars) < 1:
        raise ValueError("need at least 1 bar")
    total = 0.0
    for b in bars:
        o, h, l, c = _logs(b)
        total += 0.5 * (h - l) ** 2 - (2.0 * _LOG2 - 1.0) * (c - o) ** 2
    return total


def rogers_satchell(bars: list[dict]) -> float:
    """Rogers-Satchell (1991) drift-robust variance.

    Σ [ ln(H/C)·ln(H/O) + ln(L/C)·ln(L/O) ]
    """
    if len(bars) < 1:
        raise ValueError("need at least 1 bar")
    total = 0.0
    for b in bars:
        o, h, l, c = _logs(b)
        total += (h - c) * (h - o) + (l - c) * (l - o)
    return total


def yang_zhang(bars: list[dict]) -> float:
    """Yang-Zhang (2000) variance: overnight + open-to-close + RS.

    σ² = σ_o² + k·σ_c² + (1 − k)·σ_rs²,
    k = 0.34 / (1.34 + (n+1)/(n−1)).
    Handles overnight jumps and drift; the default estimator here.
    """
    n = len(bars)
    if n < 2:
        raise ValueError("need at least 2 bars")
    o = [math.log(b["open"]) for b in bars]
    c = [math.log(b["close"]) for b in bars]
    # overnight: log(Open_t / Close_{t-1})
    ov = [o[i] - c[i - 1] for i in range(1, n)]
    # open-to-close
    oc = [c[i] - o[i] for i in range(n)]
    m_ov = sum(ov) / len(ov)
    m_oc = sum(oc) / len(oc)
    var_o = sum((x - m_ov) ** 2 for x in ov) / (len(ov) - 1) if len(ov) > 1 else 0.0
    var_c = sum((x - m_oc) ** 2 for x in oc) / (len(oc) - 1) if len(oc) > 1 else 0.0
    var_rs = rogers_satchell(bars)
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    return var_o + k * var_c + (1.0 - k) * var_rs


ESTIMATORS = {
    "close_to_close": close_to_close,
    "parkinson": parkinson,
    "garman_klass": garman_klass,
    "rogers_satchell": rogers_satchell,
    "yang_zhang": yang_zhang,
}


def realized_vol(
    bars: list[dict],
    estimator: str = "yang_zhang",
    window: int = 21,
    annualize: int = 252,
) -> list[dict]:
    """Rolling annualized realized volatility.

    Returns ``[{"index": i, "vol": vol}, ...]`` aligned to the last bar
    of each window, so the series can be plotted or fed to HAR as RV.
    """
    if estimator not in ESTIMATORS:
        raise ValueError(f"unknown estimator {estimator!r}; pick from {sorted(ESTIMATORS)}")
    if window < 2:
        raise ValueError("window must be >= 2")
    if len(bars) < window:
        raise ValueError(f"need at least {window} bars, got {len(bars)}")
    fn = ESTIMATORS[estimator]
    out = []
    for end in range(window, len(bars) + 1):
        var = fn(bars[end - window : end])
        # variance over `window` days → annualized vol
        vol = math.sqrt(max(var, 0.0) / window * annualize)
        out.append({"index": end - 1, "vol": vol, "var": var / window * annualize})
    return out


def realized_var_series(
    bars: list[dict],
    estimator: str = "yang_zhang",
    window: int = 21,
) -> list[float]:
    """Daily (per-day) realized variance series for HAR / evaluation.

    One value per rolling window, aligned to the window's last bar.
    """
    if estimator not in ESTIMATORS:
        raise ValueError(f"unknown estimator {estimator!r}; pick from {sorted(ESTIMATORS)}")
    if window < 2:
        raise ValueError("window must be >= 2")
    if len(bars) < window:
        raise ValueError(f"need at least {window} bars, got {len(bars)}")
    fn = ESTIMATORS[estimator]
    return [fn(bars[end - window : end]) / window for end in range(window, len(bars) + 1)]
