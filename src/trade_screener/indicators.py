"""Technical indicators over OHLCV bars.  Stdlib-only, pure functions.

Bars are dicts with at least ``close``; ``high``/``low``/``volume`` are
needed for ATR / dollar volume / 52-week range.  Missing keys degrade
gracefully to ``None`` metrics rather than raising.
"""

from __future__ import annotations

import math


def closes(bars: list[dict]) -> list[float]:
    return [float(b["close"]) for b in bars if b.get("close") is not None]


def sma(values: list[float], n: int) -> float | None:
    """Simple moving average of the last ``n`` values."""
    if n <= 0 or len(values) < n:
        return None
    return sum(values[-n:]) / n


def ema(values: list[float], n: int) -> float | None:
    """Exponential moving average (Wilder-style seed: SMA of first ``n``)."""
    if n <= 0 or len(values) < n:
        return None
    k = 2.0 / (n + 1.0)
    avg = sum(values[:n]) / n
    for v in values[n:]:
        avg = v * k + avg * (1.0 - k)
    return avg


def log_returns(values: list[float]) -> list[float]:
    out = []
    for prev, cur in zip(values, values[1:]):
        if prev and prev > 0 and cur and cur > 0:
            out.append(math.log(cur / prev))
    return out


def momentum(values: list[float], n: int) -> float | None:
    """Total simple return over the last ``n`` bars: ``v[-1]/v[-n-1] - 1``."""
    if n <= 0 or len(values) < n + 1:
        return None
    base = values[-n - 1]
    if not base or base <= 0:
        return None
    return values[-1] / base - 1.0


def realized_vol(values: list[float], n: int, periods_per_year: int = 252) -> float | None:
    """Annualized stdev of log returns over the last ``n`` bars."""
    if n < 2:
        return None
    rets = log_returns(values[-(n + 1):])
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var * periods_per_year)


def rsi_wilder(bars_or_closes: list, n: int = 14) -> float | None:
    """Wilder's RSI(n): 100 - 100 / (1 + RS) with smoothed avg gain/loss."""
    values = [float(b["close"]) for b in bars_or_closes] if bars_or_closes and isinstance(bars_or_closes[0], dict) else list(bars_or_closes)
    if n <= 0 or len(values) < n + 1:
        return None
    gains, losses = 0.0, 0.0
    for prev, cur in zip(values[:n], values[1:n + 1]):
        diff = cur - prev
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain, avg_loss = gains / n, losses / n
    for prev, cur in zip(values[n:-1], values[n + 1:]):
        diff = cur - prev
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (n - 1) + gain) / n
        avg_loss = (avg_loss * (n - 1) + loss) / n
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def atr_wilder(bars: list[dict], n: int = 14) -> float | None:
    """Wilder's ATR(n) over true ranges."""
    if n <= 0 or len(bars) < n + 1:
        return None
    trs = []
    for prev, bar in zip(bars, bars[1:]):
        high, low = float(bar["high"]), float(bar["low"])
        prev_close = float(prev["close"])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    atr = sum(trs[:n]) / n
    for tr in trs[n:]:
        atr = (atr * (n - 1) + tr) / n
    return atr


def mean_dollar_volume(bars: list[dict], n: int = 21) -> float | None:
    """Mean close*volume over the last ``n`` bars (liquidity proxy)."""
    if n <= 0 or len(bars) < n:
        return None
    total = 0.0
    for bar in bars[-n:]:
        if bar.get("close") is None or bar.get("volume") is None:
            return None
        total += float(bar["close"]) * float(bar["volume"])
    return total / n


def distance_to_high(bars: list[dict], n: int = 252) -> float | None:
    """``close / max(high, n) - 1`` — non-positive; 0 means at the high."""
    window = bars[-n:]
    if len(window) < 2:
        return None
    high = max(float(b["high"]) for b in window)
    close = float(bars[-1]["close"])
    if high <= 0:
        return None
    return close / high - 1.0


def distance_to_low(bars: list[dict], n: int = 252) -> float | None:
    """``close / min(low, n) - 1`` — non-negative; 0 means at the low."""
    window = bars[-n:]
    if len(window) < 2:
        return None
    low = min(float(b["low"]) for b in window)
    close = float(bars[-1]["close"])
    if low <= 0:
        return None
    return close / low - 1.0


def max_drawdown(values: list[float], n: int = 252) -> float | None:
    """Worst peak-to-trough simple drawdown over the last ``n`` values (<= 0)."""
    window = values[-n:]
    if len(window) < 2:
        return None
    peak = window[0]
    worst = 0.0
    for v in window[1:]:
        if v > peak:
            peak = v
        elif peak > 0:
            worst = min(worst, v / peak - 1.0)
    return worst


def beta_vs(returns: list[float], benchmark: list[float]) -> float | None:
    """OLS slope of ``returns`` on ``benchmark`` (no intercept needed for slope)."""
    if len(returns) != len(benchmark) or len(returns) < 2:
        return None
    mb = sum(benchmark) / len(benchmark)
    mr = sum(returns) / len(returns)
    cov = sum((b - mb) * (r - mr) for b, r in zip(benchmark, returns))
    var = sum((b - mb) ** 2 for b in benchmark)
    if var == 0:
        return None
    return cov / var
