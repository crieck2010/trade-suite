"""Mean-reversion strategies: fade stretched moves back toward average."""

from __future__ import annotations

from datetime import datetime

from . import indicators as ind
from .base import SingleAssetStrategy, closes, highs, lows


class BollingerReversion(SingleAssetStrategy):
    """Fade band tags: long the lower band, short the upper band, exit at the midline."""

    name = "bollinger_reversion"
    family = "mean_reversion"
    description = "Buy lower-band tags, sell upper-band tags, exit at the basis."
    DEFAULT_PARAMS = {"period": 20, "num_std": 2.0, "long_only": True}

    @property
    def warmup_bars(self) -> int:
        return self.params["period"] + 1

    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        c = closes(history)
        bands = ind.bollinger(c, self.params["period"], self.params["num_std"])
        if bands["mid"] is None:
            return None
        close = c[-1]
        target: int | None = None
        if close < bands["lower"]:
            target = 1
        elif close > bands["upper"]:
            target = -1
        else:
            prev = c[-2]
            if prev < bands["mid"] <= close or prev > bands["mid"] >= close:
                target = 0  # stretched position reclaimed the midline
        regime = self._transition(symbol, target)
        if regime is None:
            return None
        return self._signal_for(timestamp, symbol, regime,
                                long_only=self.params["long_only"])


class RSI2MeanReversion(SingleAssetStrategy):
    """Connors-style: 2-period RSI washouts bought above a long trend filter."""

    name = "rsi2_mean_reversion"
    family = "mean_reversion"
    description = "Buy sharp RSI(2) pullbacks in an uptrend; exit on strength."
    DEFAULT_PARAMS = {"rsi_period": 2, "trend_period": 200, "oversold": 10,
                      "exit_sma": 5, "long_only": True}

    @property
    def warmup_bars(self) -> int:
        return self.params["trend_period"] + 1

    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        c = closes(history)
        p = self.params
        trend = ind.sma(c, p["trend_period"])
        rsi_v = ind.rsi(c, p["rsi_period"])
        if trend is None or rsi_v is None:
            return None
        close = c[-1]
        target: int | None = None
        strength = 1.0
        if close > trend and rsi_v < p["oversold"]:
            target = 1
            strength = max(0.2, 1 - rsi_v / 100)
        else:
            exit_level = ind.sma(c, p["exit_sma"])
            if exit_level is not None and close > exit_level:
                target = 0
        regime = self._transition(symbol, target)
        if regime is None:
            return None
        return self._signal_for(timestamp, symbol, regime, strength=strength)


class ZScoreReversion(SingleAssetStrategy):
    """Trade z-score extremes of price back toward the rolling mean."""

    name = "zscore_reversion"
    family = "mean_reversion"
    description = "Fade +/-entry_z deviations; cover inside exit_z."
    DEFAULT_PARAMS = {"lookback": 20, "entry_z": 2.0, "exit_z": 0.5, "long_only": True}

    @property
    def warmup_bars(self) -> int:
        return self.params["lookback"] + 1

    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        c = closes(history)
        z = ind.zscore(c, self.params["lookback"])
        if z is None:
            return None
        entry, exit_ = self.params["entry_z"], self.params["exit_z"]
        target: int | None = None
        strength = 1.0
        if z < -entry:
            target, strength = 1, min(1.0, abs(z) / entry / 2 + 0.5)
        elif z > entry:
            target, strength = -1, min(1.0, z / entry / 2 + 0.5)
        elif abs(z) < exit_:
            target = 0
        regime = self._transition(symbol, target)
        if regime is None:
            return None
        return self._signal_for(timestamp, symbol, regime,
                                long_only=self.params["long_only"],
                                strength=strength)


class StochasticReversion(SingleAssetStrategy):
    """Buy stochastic washouts below ``oversold``; exit on recovery."""

    name = "stochastic_reversion"
    family = "mean_reversion"
    description = "Level-based stochastic mean reversion."
    DEFAULT_PARAMS = {"k": 14, "d": 3, "oversold": 20, "exit_level": 50, "long_only": True}

    @property
    def warmup_bars(self) -> int:
        return self.params["k"] + self.params["d"]

    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        h, l, c = highs(history), lows(history), closes(history)
        k_now, _ = ind.stochastic(h, l, c, self.params["k"], self.params["d"])
        if k_now is None:
            return None
        target: int | None = None
        strength = 1.0
        if k_now < self.params["oversold"]:
            target, strength = 1, max(0.2, 1 - k_now / 100)
        elif k_now > self.params["exit_level"]:
            target = 0
        regime = self._transition(symbol, target)
        if regime is None:
            return None
        return self._signal_for(timestamp, symbol, regime, strength=strength)
