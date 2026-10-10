"""Trend-following strategies: ride sustained directional moves."""

from __future__ import annotations

from datetime import datetime

from . import indicators as ind
from .base import Signal, SignalAction, SingleAssetStrategy, closes, highs, lows


class SMACrossover(SingleAssetStrategy):
    """Long when the fast SMA crosses above the slow SMA; exit/short on cross down."""

    name = "sma_crossover"
    family = "trend"
    description = "Classic dual-moving-average trend system."
    DEFAULT_PARAMS = {"fast": 10, "slow": 30, "long_only": True}

    @property
    def warmup_bars(self) -> int:
        return self.params["slow"] + 1

    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        c = closes(history)
        fast, slow = self.params["fast"], self.params["slow"]
        f_now, s_now = ind.sma(c, fast), ind.sma(c, slow)
        f_prev, s_prev = ind.sma(c[:-1], fast), ind.sma(c[:-1], slow)
        if ind.crossed_above(f_now, s_now, f_prev, s_prev):  # type: ignore[arg-type]
            return Signal(symbol, timestamp, SignalAction.LONG)
        if ind.crossed_below(f_now, s_now, f_prev, s_prev):  # type: ignore[arg-type]
            action = SignalAction.EXIT if self.params["long_only"] else SignalAction.SHORT
            return Signal(symbol, timestamp, action)
        return None


class EMACrossover(SingleAssetStrategy):
    """EMA version of the dual-MA cross: faster to adapt, quicker to whipsaw."""

    name = "ema_crossover"
    family = "trend"
    description = "Dual exponential-moving-average crossover."
    DEFAULT_PARAMS = {"fast": 12, "slow": 26, "long_only": True}

    @property
    def warmup_bars(self) -> int:
        return self.params["slow"] + 1

    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        c = closes(history)
        fast, slow = self.params["fast"], self.params["slow"]
        f_now, s_now = ind.ema(c, fast), ind.ema(c, slow)
        f_prev, s_prev = ind.ema(c[:-1], fast), ind.ema(c[:-1], slow)
        if ind.crossed_above(f_now, s_now, f_prev, s_prev):  # type: ignore[arg-type]
            return Signal(symbol, timestamp, SignalAction.LONG)
        if ind.crossed_below(f_now, s_now, f_prev, s_prev):  # type: ignore[arg-type]
            action = SignalAction.EXIT if self.params["long_only"] else SignalAction.SHORT
            return Signal(symbol, timestamp, action)
        return None


class MACDTrend(SingleAssetStrategy):
    """Long while the MACD line is above its signal line; exit/short below."""

    name = "macd_trend"
    family = "trend"
    description = "MACD line vs signal line as a trend regime switch."
    DEFAULT_PARAMS = {"fast": 12, "slow": 26, "signal": 9, "long_only": True}

    @property
    def warmup_bars(self) -> int:
        return self.params["slow"] + self.params["signal"] + 1

    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        c = closes(history)
        p = self.params
        m_now, s_now, _ = ind.macd(c, p["fast"], p["slow"], p["signal"])
        m_prev, s_prev, _ = ind.macd(c[:-1], p["fast"], p["slow"], p["signal"])
        if m_now is None or s_now is None:
            return None
        if ind.crossed_above(m_now, s_now, m_prev, s_prev):
            return Signal(symbol, timestamp, SignalAction.LONG)
        if ind.crossed_below(m_now, s_now, m_prev, s_prev):
            action = SignalAction.EXIT if p["long_only"] else SignalAction.SHORT
            return Signal(symbol, timestamp, action)
        return None


class DonchianBreakout(SingleAssetStrategy):
    """Turtle-style: enter on an N-bar high/low breakout, exit on a shorter channel."""

    name = "donchian_breakout"
    family = "trend"
    description = "Channel breakout entries with a faster exit channel."
    DEFAULT_PARAMS = {"entry": 20, "exit": 10, "long_only": True}

    @property
    def warmup_bars(self) -> int:
        return self.params["entry"] + 1

    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        h, l, c = highs(history), lows(history), closes(history)
        entry, exit_ = self.params["entry"], self.params["exit"]
        # Breakout measured against the channel *excluding* the current bar,
        # so the signal bar itself is the breakout bar.
        up, _ = ind.donchian(h[:-1], l[:-1], entry)
        _, dn = ind.donchian(h[:-1], l[:-1], exit_)
        target: int | None = None
        if up is not None and c[-1] > up:
            target = 1
        elif dn is not None and c[-1] < dn:
            target = -1
        regime = self._transition(symbol, target)
        if regime is None:
            return None
        return self._signal_for(timestamp, symbol, regime,
                                long_only=self.params["long_only"])


class Supertrend(SingleAssetStrategy):
    """ATR-based trend flip with persistent bands (standard Supertrend).

    Bands only tighten against the trend, so genuine breakdowns pierce
    them: long while the close holds above the trailing lower band,
    short/exit below it.
    """

    name = "supertrend"
    family = "trend"
    description = "Supertrend flips; volatility-scaled entries."
    DEFAULT_PARAMS = {"atr_period": 10, "multiplier": 3.0, "long_only": True}

    def __init__(self, symbols: list[str], **params) -> None:
        super().__init__(symbols, **params)
        # symbol -> (trend, prev_upper, prev_lower)
        self._state: dict[str, tuple[int, float, float]] = {}

    @property
    def warmup_bars(self) -> int:
        return self.params["atr_period"] + 2

    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        h, l, c = highs(history), lows(history), closes(history)
        atr_v = ind.atr(h, l, c, self.params["atr_period"])
        if atr_v is None:
            return None
        basis = (h[-1] + l[-1]) / 2.0
        m = self.params["multiplier"]
        basic_upper, basic_lower = basis + m * atr_v, basis - m * atr_v
        if symbol not in self._state:
            self._state[symbol] = (1, basic_upper, basic_lower)
            return None
        prev_trend, prev_upper, prev_lower = self._state[symbol]
        prev_close = c[-2]
        final_upper = basic_upper if (basic_upper < prev_upper or prev_close > prev_upper) else prev_upper
        final_lower = basic_lower if (basic_lower > prev_lower or prev_close < prev_lower) else prev_lower
        close = c[-1]
        if prev_trend == 1 and close <= final_lower:
            trend = -1
        elif prev_trend == -1 and close >= final_upper:
            trend = 1
        else:
            trend = prev_trend
        self._state[symbol] = (trend, final_upper, final_lower)
        if trend != prev_trend:
            if trend == 1:
                return Signal(symbol, timestamp, SignalAction.LONG)
            action = SignalAction.EXIT if self.params["long_only"] else SignalAction.SHORT
            return Signal(symbol, timestamp, action)
        return None
