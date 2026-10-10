"""Momentum, volatility-breakout, and volume strategies."""

from __future__ import annotations

from datetime import datetime

from . import indicators as ind
from .base import Signal, SignalAction, SingleAssetStrategy, closes, highs, lows, volumes


class TimeSeriesMomentum(SingleAssetStrategy):
    """Own the sign of the trailing return: long positive drift, flat/short negative."""

    name = "time_series_momentum"
    family = "momentum"
    description = "Time-series momentum on trailing rate of change."
    DEFAULT_PARAMS = {"lookback": 60, "skip": 1, "long_only": True}

    @property
    def warmup_bars(self) -> int:
        return self.params["lookback"] + self.params["skip"] + 1

    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        c = closes(history)
        skip = self.params["skip"]
        series = c if skip <= 0 else c[:-skip]
        momentum = ind.roc(series, self.params["lookback"])
        if momentum is None:
            return None
        target = 1 if momentum > 0 else -1
        regime = self._transition(symbol, target)
        if regime is None:
            return None
        return self._signal_for(timestamp, symbol, regime,
                                long_only=self.params["long_only"],
                                strength=min(1.0, abs(momentum) * 10))


class KeltnerBreakout(SingleAssetStrategy):
    """Volatility breakout: enter outside the Keltner channel, exit at the EMA."""

    name = "keltner_breakout"
    family = "volatility"
    description = "ATR-channel breakout with midline exits."
    DEFAULT_PARAMS = {"ema_period": 20, "atr_period": 10, "mult": 2.0, "long_only": True}

    @property
    def warmup_bars(self) -> int:
        return max(self.params["ema_period"], self.params["atr_period"]) + 2

    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        h, l, c = highs(history), lows(history), closes(history)
        p = self.params
        ch = ind.keltner(h, l, c, p["ema_period"], p["atr_period"], p["mult"])
        if ch["mid"] is None:
            return None
        close = c[-1]
        target: int | None = None
        if close > ch["upper"]:
            target = 1
        elif close < ch["lower"]:
            target = -1
        else:
            prev = c[-2]
            if prev > ch["mid"] >= close or prev < ch["mid"] <= close:
                target = 0
        regime = self._transition(symbol, target)
        if regime is None:
            return None
        return self._signal_for(timestamp, symbol, regime,
                                long_only=p["long_only"])


class BollingerSqueezeBreakout(SingleAssetStrategy):
    """Enter when price breaks out after bandwidth compression (the 'squeeze')."""

    name = "bollinger_squeeze_breakout"
    family = "volatility"
    description = "Low-bandwidth coiling resolved by a band breakout."
    DEFAULT_PARAMS = {"period": 20, "num_std": 2.0, "squeeze_quantile": 0.2,
                      "squeeze_lookback": 60, "long_only": True}

    @property
    def warmup_bars(self) -> int:
        return self.params["squeeze_lookback"] + 1

    def history_bars(self) -> int | None:
        # Needs period + squeeze_lookback bars of bandwidth history,
        # which exceeds the default warmup+5 cap.
        return self.params["period"] + self.params["squeeze_lookback"] + 1

    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        c = closes(history)
        p = self.params
        # Bandwidth history *excluding* the current bar: the squeeze is
        # judged on the coil, the breakout on the signal bar.
        widths = []
        for end in range(p["period"], len(c)):
            b = ind.bollinger(c[:end], p["period"], p["num_std"])
            if b["bandwidth"] is not None:
                widths.append(b["bandwidth"])
        if len(widths) < p["squeeze_lookback"]:
            return None
        tail = widths[-p["squeeze_lookback"]:]
        squeezed = tail[-1] <= sorted(tail)[max(0, int(len(tail) * p["squeeze_quantile"]) - 1)]
        bands = ind.bollinger(c, p["period"], p["num_std"])
        close = c[-1]
        target: int | None = None
        if squeezed:
            if close > bands["upper"]:
                target = 1
            elif close < bands["lower"]:
                target = -1
        regime = self._transition(symbol, target)
        if regime is None:
            return None
        return self._signal_for(timestamp, symbol, regime,
                                long_only=p["long_only"], strength=0.8)


class OBVTrend(SingleAssetStrategy):
    """Trend-follow the on-balance-volume line's own moving-average cross."""

    name = "obv_trend"
    family = "volume"
    description = "Volume-confirmed trend via OBV MA cross."
    DEFAULT_PARAMS = {"fast": 10, "slow": 30, "long_only": True}

    @property
    def warmup_bars(self) -> int:
        return self.params["slow"] + 2

    def _obv_series(self, history: list) -> list[float]:
        c, v = closes(history), volumes(history)
        series = []
        total = 0.0
        for i in range(1, len(c)):
            if c[i] > c[i - 1]:
                total += v[i]
            elif c[i] < c[i - 1]:
                total -= v[i]
            series.append(total)
        return series

    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        obv_s = self._obv_series(history)
        fast, slow = self.params["fast"], self.params["slow"]
        f_now, s_now = ind.ema(obv_s, fast), ind.ema(obv_s, slow)
        f_prev, s_prev = ind.ema(obv_s[:-1], fast), ind.ema(obv_s[:-1], slow)
        if f_now is None or s_now is None:
            return None
        if ind.crossed_above(f_now, s_now, f_prev, s_prev):
            return Signal(symbol, timestamp, SignalAction.LONG)
        if ind.crossed_below(f_now, s_now, f_prev, s_prev):
            action = SignalAction.EXIT if self.params["long_only"] else SignalAction.SHORT
            return Signal(symbol, timestamp, action)
        return None


class VWAPDeviation(SingleAssetStrategy):
    """Fade stretches away from rolling VWAP; exit when price reclaims it."""

    name = "vwap_deviation"
    family = "volume"
    description = "Mean reversion to rolling VWAP."
    DEFAULT_PARAMS = {"lookback": 20, "threshold": 0.02, "long_only": True}

    @property
    def warmup_bars(self) -> int:
        return self.params["lookback"] + 1

    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        h, l, c, v = highs(history), lows(history), closes(history), volumes(history)
        vwap = ind.rolling_vwap(h, l, c, v, self.params["lookback"])
        if vwap is None or vwap == 0:
            return None
        dev = (c[-1] - vwap) / vwap
        threshold = self.params["threshold"]
        target: int | None = None
        strength = 1.0
        if dev < -threshold:
            target, strength = 1, min(1.0, abs(dev) / threshold / 2 + 0.5)
        elif dev > threshold:
            target, strength = -1, min(1.0, dev / threshold / 2 + 0.5)
        elif abs(dev) < threshold / 4:
            target = 0
        regime = self._transition(symbol, target)
        if regime is None:
            return None
        return self._signal_for(timestamp, symbol, regime,
                                long_only=self.params["long_only"],
                                strength=strength)
