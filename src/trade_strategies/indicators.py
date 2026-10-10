"""Pure technical indicators over plain float sequences.

Every function takes oldest-first lists and returns the *current* value
(or ``None`` when there is not enough data). No NumPy, no pandas -- these
are the primitives the strategy library and the research agents compose.
Conventions follow the standard textbook definitions (Wilder's smoothing
for RSI/ATR/ADX).
"""

from __future__ import annotations

import math


def sma(values: list[float], n: int) -> float | None:
    if len(values) < n or n <= 0:
        return None
    return sum(values[-n:]) / n


def ema(values: list[float], n: int) -> float | None:
    """Exponential moving average, seeded with the SMA of the first ``n``."""
    if len(values) < n or n <= 0:
        return None
    k = 2.0 / (n + 1)
    avg = sum(values[:n]) / n
    for v in values[n:]:
        avg = v * k + avg * (1 - k)
    return avg


def stdev(values: list[float], n: int) -> float | None:
    if len(values) < n or n <= 0:
        return None
    window = values[-n:]
    mean = sum(window) / n
    return math.sqrt(sum((v - mean) ** 2 for v in window) / n)


def rolling_max(values: list[float], n: int) -> float | None:
    if len(values) < n or n <= 0:
        return None
    return max(values[-n:])


def rolling_min(values: list[float], n: int) -> float | None:
    if len(values) < n or n <= 0:
        return None
    return min(values[-n:])


def roc(values: list[float], n: int) -> float | None:
    """Rate of change over ``n`` bars, as a fraction."""
    if len(values) < n + 1 or n <= 0:
        return None
    base = values[-n - 1]
    return (values[-1] - base) / base if base != 0 else None


def zscore(values: list[float], n: int) -> float | None:
    """(last - mean) / stdev over the last ``n`` values."""
    sd = stdev(values, n)
    if sd is None or sd == 0:
        return None
    mean = sum(values[-n:]) / n
    return (values[-1] - mean) / sd


def rsi(closes: list[float], n: int = 14) -> float | None:
    """Wilder's RSI."""
    if len(closes) < n + 1 or n <= 0:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    for g, loss in zip(gains[n:], losses[n:]):
        avg_gain = (avg_gain * (n - 1) + g) / n
        avg_loss = (avg_loss * (n - 1) + loss) / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1 + rs)


def macd(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[float | None, float | None, float | None]:
    """(macd_line, signal_line, histogram), each None until warmed up."""
    if len(closes) < slow + signal:
        return None, None, None
    macd_line = ema(closes, fast) - ema(closes, slow)  # type: ignore[operator]
    # Signal line = EMA of the MACD series; build it from the tail.
    macd_series = []
    for end in range(slow, len(closes) + 1):
        window = closes[:end]
        macd_series.append(ema(window, fast) - ema(window, slow))  # type: ignore[operator]
    signal_line = ema(macd_series, signal)
    if signal_line is None:
        return macd_line, None, None
    return macd_line, signal_line, macd_line - signal_line


def bollinger(
    closes: list[float], n: int = 20, k: float = 2.0
) -> dict[str, float | None]:
    """Bollinger bands plus %b and bandwidth."""
    mid = sma(closes, n)
    sd = stdev(closes, n)
    if mid is None or sd is None:
        return {"mid": None, "upper": None, "lower": None, "pct_b": None, "bandwidth": None}
    upper, lower = mid + k * sd, mid - k * sd
    width = upper - lower
    return {
        "mid": mid,
        "upper": upper,
        "lower": lower,
        "pct_b": (closes[-1] - lower) / width if width else None,
        "bandwidth": width / mid if mid else None,
    }


def true_range(high: float, low: float, prev_close: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr(highs: list[float], lows: list[float], closes: list[float], n: int = 14) -> float | None:
    """Wilder's ATR."""
    if len(closes) < n + 1 or n <= 0:
        return None
    trs = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        trs.append(true_range(highs[i], lows[i], closes[i - 1]))
    avg = sum(trs[:n]) / n
    for tr in trs[n:]:
        avg = (avg * (n - 1) + tr) / n
    return avg


def stochastic(
    highs: list[float], lows: list[float], closes: list[float], k: int = 14, d: int = 3
) -> tuple[float | None, float | None]:
    """(%K, %D)."""
    if len(closes) < k + d - 1 or k <= 0:
        return None, None
    k_values = []
    for end in range(k, len(closes) + 1):
        hh = max(highs[end - k : end])
        ll = min(lows[end - k : end])
        span = hh - ll
        k_values.append((closes[end - 1] - ll) / span * 100.0 if span else 50.0)
    return k_values[-1], sum(k_values[-d:]) / d


def obv(closes: list[float], volumes: list[float]) -> float | None:
    """On-balance volume (cumulative)."""
    if not closes or len(closes) != len(volumes):
        return None
    total = 0.0
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            total += volumes[i]
        elif closes[i] < closes[i - 1]:
            total -= volumes[i]
    return total


def rolling_vwap(
    highs: list[float], lows: list[float], closes: list[float],
    volumes: list[float], n: int = 20,
) -> float | None:
    """VWAP over the last ``n`` bars (typical price x volume)."""
    if len(closes) < n or n <= 0:
        return None
    num = sum(
        (highs[i] + lows[i] + closes[i]) / 3.0 * volumes[i]
        for i in range(len(closes) - n, len(closes))
    )
    den = sum(volumes[len(closes) - n :])
    return num / den if den else None


def donchian(
    highs: list[float], lows: list[float], n: int
) -> tuple[float | None, float | None]:
    """(highest high, lowest low) over the last ``n`` bars, inclusive."""
    return rolling_max(highs, n), rolling_min(lows, n)


def keltner(
    highs: list[float], lows: list[float], closes: list[float],
    ema_n: int = 20, atr_n: int = 10, mult: float = 2.0,
) -> dict[str, float | None]:
    mid = ema(closes, ema_n)
    atr_v = atr(highs, lows, closes, atr_n)
    if mid is None or atr_v is None:
        return {"mid": None, "upper": None, "lower": None}
    return {"mid": mid, "upper": mid + mult * atr_v, "lower": mid - mult * atr_v}


def adx(
    highs: list[float], lows: list[float], closes: list[float], n: int = 14
) -> float | None:
    """Wilder's ADX -- trend strength 0..100 (directionless)."""
    if len(closes) < 2 * n + 1 or n <= 0:
        return None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(closes)):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        trs.append(true_range(highs[i], lows[i], closes[i - 1]))
    atr_v = sum(trs[:n]) / n
    p_dm = sum(plus_dm[:n]) / n
    m_dm = sum(minus_dm[:n]) / n
    dx_values = []
    for i in range(n, len(trs)):
        atr_v = (atr_v * (n - 1) + trs[i]) / n
        p_dm = (p_dm * (n - 1) + plus_dm[i]) / n
        m_dm = (m_dm * (n - 1) + minus_dm[i]) / n
        p_di = 100 * p_dm / atr_v if atr_v else 0.0
        m_di = 100 * m_dm / atr_v if atr_v else 0.0
        denom = p_di + m_di
        dx_values.append(100 * abs(p_di - m_di) / denom if denom else 0.0)
    if len(dx_values) < n:
        return None
    adx_v = sum(dx_values[:n]) / n
    for dx in dx_values[n:]:
        adx_v = (adx_v * (n - 1) + dx) / n
    return adx_v


def crossed_above(fast_now: float, slow_now: float,
                  fast_prev: float | None, slow_prev: float | None) -> bool:
    """True on the bar where ``fast`` crosses above ``slow``."""
    if fast_prev is None or slow_prev is None:
        return fast_now > slow_now
    return fast_now > slow_now and fast_prev <= slow_prev


def crossed_below(fast_now: float, slow_now: float,
                  fast_prev: float | None, slow_prev: float | None) -> bool:
    if fast_prev is None or slow_prev is None:
        return fast_now < slow_now
    return fast_now < slow_now and fast_prev >= slow_prev
