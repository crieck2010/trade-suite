"""The copper:gold ratio and its trailing statistics.

``ratio = copper_price / gold_price`` per aligned date.  Everything derived
from the ratio (moving averages, rate of change, z-score) uses trailing
windows ending at or before ``t`` — no look-ahead, so a regime read at
``t`` is reproducible from data available at ``t``.
"""

from __future__ import annotations

from ._stats import moving_average, rate_of_change, rolling_zscore
from .series import align_series


def ratio_series(
    copper: list[dict],
    gold: list[dict],
) -> list[dict]:
    """Build ``[{"date", "copper", "gold", "ratio"}]`` on shared dates."""
    cu, au, _dates = align_series(copper, gold)
    return [
        {
            "date": c["date"],
            "copper": c["price"],
            "gold": a["price"],
            "ratio": c["price"] / a["price"],
        }
        for c, a in zip(cu, au)
    ]


def enrich_ratios(
    rows: list[dict],
    ma_fast: int = 50,
    ma_slow: int = 200,
    roc_n: int = 21,
    z_lookback: int = 252,
    z_min_periods: int = 63,
) -> list[dict]:
    """Attach trailing statistics to ratio rows.

    Adds ``ratio_ma50``, ``ratio_ma200``, ``roc_21`` (percent) and
    ``z_252`` (trailing z-score).  Warm-up entries are ``None``.
    """
    ratios = [r["ratio"] for r in rows]
    ma50 = moving_average(ratios, ma_fast)
    ma200 = moving_average(ratios, ma_slow)
    roc = rate_of_change(ratios, roc_n)
    z = rolling_zscore(ratios, lookback=z_lookback, min_periods=z_min_periods)
    out = []
    for r, m50, m200, rc, zz in zip(rows, ma50, ma200, roc, z):
        row = dict(r)
        row["ratio_ma50"] = m50
        row["ratio_ma200"] = m200
        row["roc_21"] = rc
        row["z_252"] = zz
        out.append(row)
    return out
