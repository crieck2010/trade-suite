"""Meta strategies: overlays and composites.

These wrap or combine other strategies -- the "complex" end of the
library that the research agents assemble and tune.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from . import indicators as ind
from .base import Signal, SignalAction, Strategy, closes, highs, lows, timestamp_of, field


class TrailingStop(Strategy):
    """ATR trailing-stop overlay around any strategy.

    Passes the wrapped strategy's signals through, tracks virtual entries
    from them (assumes fills follow signals, as in ``trade-backtest``),
    and emits EXIT when price breaches the trailing stop. Also clears
    tracking when the inner strategy exits on its own.
    """

    name = "trailing_stop"
    family = "meta"
    description = "ATR trailing-stop exit overlay for any strategy."
    DEFAULT_PARAMS = {"atr_period": 14, "multiplier": 3.0}

    def __init__(self, strategy: Strategy, **params) -> None:
        super().__init__(strategy.symbols, **params)
        self.inner = strategy
        self._entries: dict[str, tuple[float, float]] = {}  # symbol -> (direction, entry_price)
        self._histories: dict[str, list] = {s: [] for s in self.symbols}

    @property
    def warmup_bars(self) -> int:
        return max(self.inner.warmup_bars, self.params["atr_period"] + 1)

    def on_bar(self, timestamp: datetime, bars: dict) -> list[Signal]:
        for symbol in self.symbols:
            if symbol in bars:
                self._histories[symbol].append(bars[symbol])
        inner_signals = self.inner.on_bar(timestamp, bars)
        out: list[Signal] = []
        for signal in inner_signals:
            out.append(signal)
            if signal.action is SignalAction.EXIT:
                self._entries.pop(signal.symbol, None)
            else:
                direction = 1 if signal.action is SignalAction.LONG else -1
                price = float(field(bars[signal.symbol], "close"))
                self._entries[signal.symbol] = (direction, price)
        # Trailing-stop check on the current bar.
        for symbol, (direction, entry) in list(self._entries.items()):
            if symbol not in bars:
                continue
            history = self._histories[symbol]
            if len(history) < self.params["atr_period"] + 1:
                continue
            atr_v = ind.atr(highs(history), lows(history), closes(history),
                            self.params["atr_period"])
            if atr_v is None:
                continue
            m = self.params["multiplier"]
            bar = bars[symbol]
            if direction == 1 and float(field(bar, "low")) <= entry - m * atr_v:
                out.append(Signal(symbol, timestamp_of(bar), SignalAction.EXIT, strength=1.0))
                del self._entries[symbol]
            elif direction == -1 and float(field(bar, "high")) >= entry + m * atr_v:
                out.append(Signal(symbol, timestamp_of(bar), SignalAction.EXIT, strength=1.0))
                del self._entries[symbol]
        return out

    def describe(self) -> dict:
        info = super().describe()
        info["wraps"] = self.inner.describe()
        return info


class RegimeFilter(Strategy):
    """Delegate to a trend strategy when ADX is strong, else a mean-reversion one.

    Both sub-strategies observe every bar (so their indicator state stays
    current); only the regime-appropriate one's signals are returned.
    """

    name = "regime_filter"
    family = "meta"
    description = "ADX regime switch between trend and mean-reversion legs."
    DEFAULT_PARAMS = {"adx_period": 14, "adx_threshold": 25.0}

    def __init__(self, trend: Strategy, mean_reversion: Strategy, **params) -> None:
        symbols = sorted(set(trend.symbols) | set(mean_reversion.symbols))
        super().__init__(symbols, **params)
        self.trend = trend
        self.mean_reversion = mean_reversion
        self._histories: dict[str, list] = {s: [] for s in self.symbols}

    @property
    def warmup_bars(self) -> int:
        return max(self.trend.warmup_bars, self.mean_reversion.warmup_bars,
                   2 * self.params["adx_period"] + 1)

    def _regime(self, symbol: str) -> str:
        history = self._histories[symbol]
        adx_v = ind.adx(highs(history), lows(history), closes(history),
                        self.params["adx_period"])
        if adx_v is None:
            return "mean_reversion"
        return "trend" if adx_v >= self.params["adx_threshold"] else "mean_reversion"

    def on_bar(self, timestamp: datetime, bars: dict) -> list[Signal]:
        for symbol in self.symbols:
            if symbol in bars:
                self._histories[symbol].append(bars[symbol])
        trend_signals = self.trend.on_bar(timestamp, bars)
        mr_signals = self.mean_reversion.on_bar(timestamp, bars)
        by_symbol_trend = {s.symbol: s for s in trend_signals}
        by_symbol_mr = {s.symbol: s for s in mr_signals}
        out: list[Signal] = []
        for symbol in self.symbols:
            regime = self._regime(symbol) if len(self._histories[symbol]) >= self.warmup_bars else None
            if regime == "trend" and symbol in by_symbol_trend:
                out.append(by_symbol_trend[symbol])
            elif regime == "mean_reversion" and symbol in by_symbol_mr:
                out.append(by_symbol_mr[symbol])
        return out

    def describe(self) -> dict:
        info = super().describe()
        info["trend_leg"] = self.trend.describe()
        info["mean_reversion_leg"] = self.mean_reversion.describe()
        return info


class EnsembleVote(Strategy):
    """Majority vote across strategies: act only when ``min_votes`` agree."""

    name = "ensemble_vote"
    family = "meta"
    description = "Multi-strategy voting ensemble per symbol."
    DEFAULT_PARAMS = {"min_votes": 2}

    def __init__(self, strategies: list[Strategy], **params) -> None:
        if not strategies:
            raise ValueError("ensemble_vote needs at least one strategy")
        symbols = sorted({s for strat in strategies for s in strat.symbols})
        super().__init__(symbols, **params)
        self.strategies = strategies

    @property
    def warmup_bars(self) -> int:
        return max(s.warmup_bars for s in self.strategies)

    def on_bar(self, timestamp: datetime, bars: dict) -> list[Signal]:
        votes: dict[str, Counter] = {s: Counter() for s in self.symbols}
        for strat in self.strategies:
            for signal in strat.on_bar(timestamp, bars):
                votes[signal.symbol][signal.action] += 1
        out: list[Signal] = []
        need = self.params["min_votes"]
        for symbol, counter in votes.items():
            if not counter:
                continue
            action, count = counter.most_common(1)[0]
            if count >= need:
                out.append(Signal(symbol, timestamp, action,
                                  strength=count / len(self.strategies)))
        return out

    def describe(self) -> dict:
        info = super().describe()
        info["members"] = [s.describe() for s in self.strategies]
        return info
