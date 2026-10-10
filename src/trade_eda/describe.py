"""Per-asset summary statistics and data-quality checks.

``describe_series`` gives the EDA moments (mean, vol, skew, kurtosis,
Jarque-Bera) for one return series; ``data_quality`` scans raw bars for the
problems that silently corrupt correlation work: missing closes,
zero-volume prints, stale (repeated) closes, and MAD-based price outliers.
"""

from __future__ import annotations

import math
from datetime import datetime


def describe_series(xs: list[float], annualize: int = 252) -> dict:
    """Moments of a return series as plain data (vol/skew annualized)."""
    n = len(xs)
    if n < 2:
        raise ValueError("need >= 2 observations")
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    std = math.sqrt(max(var, 0.0))
    if std > 0 and n > 2:
        m3 = sum((x - mean) ** 3 for x in xs) / n
        m4 = sum((x - mean) ** 4 for x in xs) / n
        skew = m3 / std ** 3
        kurt = m4 / std ** 4 - 3.0  # excess kurtosis
    else:
        skew, kurt = 0.0, -3.0
    # Jarque-Bera: n/6 * (skew^2 + kurt^2/4); ~ chi2(2) under normality.
    jb = n / 6.0 * (skew ** 2 + kurt ** 2 / 4.0) if n > 2 else 0.0
    return {
        "n": n,
        "mean": round(mean, 8),
        "mean_annualized": round(mean * annualize, 6),
        "vol_annualized": round(std * math.sqrt(annualize), 6),
        "skew": round(skew, 6),
        "kurtosis_excess": round(kurt, 6),
        "jarque_bera": round(jb, 4),
        "min": round(min(xs), 8),
        "max": round(max(xs), 8),
    }


def describe_returns(
    returns: dict[str, list[float]],
    annualize: int = 252,
) -> dict[str, dict]:
    """``describe_series`` for every symbol."""
    return {s: describe_series(xs, annualize=annualize)
            for s, xs in sorted(returns.items())}


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _as_bar(b) -> dict:
    if isinstance(b, dict):
        return b
    return {"close": b.close,
            "volume": getattr(b, "volume", None),
            "timestamp": getattr(b, "timestamp", None),
            "open": getattr(b, "open", None),
            "high": getattr(b, "high", None),
            "low": getattr(b, "low", None)}


def data_quality(bars_by_symbol: dict) -> dict[str, dict]:
    """Data-quality report per symbol as plain data.

    Flags: missing/NaN closes, zero-volume bars, stale closes (the same
    close printing 3+ bars in a row — a frozen feed), and price outliers
    via the median absolute deviation (|x - median| > 8 * MAD).
    """
    out: dict[str, dict] = {}
    for sym in sorted(bars_by_symbol):
        bars = [_as_bar(b) for b in bars_by_symbol[sym]]
        n = len(bars)
        closes = [b.get("close") for b in bars]
        missing = sum(1 for c in closes
                      if c is None or (isinstance(c, float)
                                       and math.isnan(c)))
        vols = [b.get("volume") for b in bars]
        zero_vol = sum(1 for v in vols if v == 0)
        # Stale closes: runs of >= 3 identical consecutive closes.
        stale = 0
        run = 1
        for i in range(1, n):
            if closes[i] == closes[i - 1] and closes[i] is not None:
                run += 1
            else:
                if run >= 3:
                    stale += 1
                run = 1
        if run >= 3:
            stale += 1
        # MAD outliers on closes.
        valid = [c for c in closes
                 if c is not None and not (isinstance(c, float)
                                           and math.isnan(c))]
        outliers = 0
        if len(valid) >= 5:
            med = _median(valid)
            mad = _median([abs(c - med) for c in valid])
            if mad > 0:
                outliers = sum(1 for c in valid if abs(c - med) > 8 * mad)
        stamps = [b.get("timestamp") for b in bars if b.get("timestamp")]
        out[sym] = {
            "n_bars": n,
            "missing_closes": missing,
            "zero_volume_bars": zero_vol,
            "stale_close_runs": stale,
            "price_outliers_mad": outliers,
            "first": str(stamps[0]) if stamps else None,
            "last": str(stamps[-1]) if stamps else None,
            "clean": not (missing or zero_vol or stale or outliers),
        }
    return out
