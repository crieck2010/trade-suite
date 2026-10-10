"""Daily market-breadth panel from constituent bars.

All inputs/outputs are plain data.  Missing values are ``None`` — never
NaN, never invented.
"""

from __future__ import annotations

from ._stats import ema
from .universe import validate_universe


def _normalize_weights(
    weights: dict[str, float] | None,
    symbols: list[str],
) -> dict[str, float] | None:
    if weights is None:
        return None
    w = {s: float(weights[s]) for s in symbols if s in weights and weights[s] > 0}
    total = sum(w.values())
    if total <= 0 or not w:
        return None
    return {s: v / total for s, v in w.items()}


def mcclellan(net_advances: list[float]) -> tuple[list[float], list[float]]:
    """McClellan Oscillator and Summation Index from daily net advances.

    Oscillator = EMA(19) − EMA(39) of net advances (advancers − decliners);
    the Summation Index is its cumulative sum.  EMAs are seeded with the
    first observation (see ``_stats.ema``).
    """
    fast = ema([float(x) for x in net_advances], 19)
    slow = ema([float(x) for x in net_advances], 39)
    osc = [f - s for f, s in zip(fast, slow)]
    summation: list[float] = []
    total = 0.0
    for o in osc:
        total += o
        summation.append(total)
    return osc, summation


def breadth_panel(
    universe: dict,
    weights: dict[str, float] | None = None,
    ma_short: int = 50,
    ma_long: int = 200,
    high_low_lookback: int = 252,
) -> list[dict]:
    """Compute the daily breadth panel for a constituent universe.

    Returns one dict per trading date (ascending).  A symbol contributes
    to a day's cross-section only if it has a bar that day; moving-average
    and high/low statistics additionally require enough of that symbol's
    own history.  Days with no priced symbols cannot occur (the universe
    validator rejects empty input).
    """
    clean = validate_universe(universe)
    symbols = sorted(clean)
    wnorm = _normalize_weights(weights, symbols)

    closes: dict[str, list[float]] = {s: [b["close"] for b in clean[s]] for s in symbols}
    dates_of: dict[str, list[str]] = {s: [b["date"] for b in clean[s]] for s in symbols}
    idx_of: dict[str, dict[str, int]] = {
        s: {d: i for i, d in enumerate(dates_of[s])} for s in symbols
    }
    all_dates = sorted({d for ds in dates_of.values() for d in ds})
    # rebase level for the EW/CW indices: each symbol's first close in sample
    base = {s: closes[s][0] for s in symbols}

    panel: list[dict] = []
    ad_line = 0.0
    net_series: list[float] = []
    for d in all_dates:
        adv = dec = unch = 0
        priced = 0  # symbols with a bar on this date (incl. first bars)
        up_vol = down_vol = 0.0
        above_s = above_l = denom_s = denom_l = 0
        new_highs = new_lows = 0
        hl_defined = False
        ew_sum = cw_sum = cw_w = 0.0
        for s in symbols:
            i = idx_of[s].get(d)
            if i is None:
                continue
            priced += 1
            b = clean[s][i]
            if i > 0:
                prev = closes[s][i - 1]
                if b["close"] > prev:
                    adv += 1
                    up_vol += b["volume"]
                elif b["close"] < prev:
                    dec += 1
                    down_vol += b["volume"]
                else:
                    unch += 1
            hist = closes[s][: i + 1]
            if len(hist) >= ma_short and b["close"] > sum(hist[-ma_short:]) / ma_short:
                above_s += 1
            if len(hist) >= ma_short:
                denom_s += 1
            if len(hist) >= ma_long and b["close"] > sum(hist[-ma_long:]) / ma_long:
                above_l += 1
            if len(hist) >= ma_long:
                denom_l += 1
            if i >= high_low_lookback:
                hl_defined = True
                prior_high = max(bb["high"] for bb in clean[s][i - high_low_lookback:i])
                prior_low = min(bb["low"] for bb in clean[s][i - high_low_lookback:i])
                if b["high"] > prior_high:
                    new_highs += 1
                if b["low"] < prior_low:
                    new_lows += 1
            rebased = b["close"] / base[s]
            ew_sum += rebased
            if wnorm and s in wnorm:
                cw_sum += wnorm[s] * rebased
                cw_w += wnorm[s]
        n_priced = priced  # present bars; A/D needs a prior close, so a
        # symbol's first bar counts as priced but not as adv/dec/unch
        net = float(adv - dec)
        net_series.append(net)
        ad_line += net
        row = {
            "date": d,
            "n_symbols": len(symbols),
            "n_priced": n_priced,
            "advancers": adv,
            "decliners": dec,
            "unchanged": unch,
            "ad_ratio": (adv / dec) if dec > 0 else None,
            "ad_line": ad_line,
            "pct_above_50dma": (100.0 * above_s / denom_s) if denom_s else None,
            "pct_above_200dma": (100.0 * above_l / denom_l) if denom_l else None,
            "new_highs": new_highs if hl_defined else None,
            "new_lows": new_lows if hl_defined else None,
            "highs_minus_lows": (new_highs - new_lows) if hl_defined else None,
            "up_down_volume_ratio": (up_vol / down_vol) if down_vol > 0 else None,
            "ew_index": 100.0 * ew_sum / n_priced if n_priced else None,
            "cw_index": (100.0 * cw_sum / cw_w) if (wnorm and cw_w > 0) else None,
        }
        row["ew_cw_ratio"] = (
            (row["ew_index"] / row["cw_index"])
            if row["ew_index"] is not None and row["cw_index"] not in (None, 0)
            else None
        )
        panel.append(row)

    osc, summation = mcclellan(net_series)
    for row, o, s in zip(panel, osc, summation):
        row["mcclellan_oscillator"] = o
        row["mcclellan_summation"] = s

    # EW/CW ratio vs its own 63-day trend (the broadening read).
    # The reference window excludes the current day -> no lookahead.
    ratios = [r["ew_cw_ratio"] for r in panel]
    trend_aligned: list[float | None] = []
    for i in range(len(panel)):
        window = [v for v in ratios[max(0, i - 63):i] if v is not None]
        # note: excludes the current day -> no lookahead
        trend_aligned.append(sum(window) / len(window) if len(window) >= 63 else None)
    for row, t in zip(panel, trend_aligned):
        r = row["ew_cw_ratio"]
        row["ew_cw_ratio_vs_63dma"] = (r / t - 1.0) if (r is not None and t) else None
    return panel
