"""Multi-asset strategies: pairs and cross-sectional momentum."""

from __future__ import annotations

from datetime import datetime

from . import indicators as ind
from .base import Signal, SignalAction, Strategy, field, timestamp_of


class PairsTrading(Strategy):
    """Trade the z-score of the A/B price ratio: short the rich leg, long the cheap leg.

    Expects exactly two symbols. Position state is tracked virtually from the
    strategy's own signals (assumes fills follow signals one bar later, as in
    ``trade-backtest``).
    """

    name = "pairs_trading"
    family = "multi_asset"
    description = "Z-score of the price ratio; dollar-neutral pair."
    DEFAULT_PARAMS = {"lookback": 60, "entry_z": 2.0, "exit_z": 0.5}

    def __init__(self, symbols: list[str], **params) -> None:
        if len(symbols) != 2:
            raise ValueError("pairs_trading needs exactly two symbols")
        super().__init__(symbols, **params)
        self._ratio: list[float] = []
        self._open: bool = False

    @property
    def warmup_bars(self) -> int:
        return self.params["lookback"] + 1

    def on_bar(self, timestamp: datetime, bars: dict) -> list[Signal]:
        a, b = self.symbols
        if a not in bars or b not in bars:
            return []
        price_a = float(field(bars[a], "close"))
        price_b = float(field(bars[b], "close"))
        if price_b == 0:
            return []
        self._ratio.append(price_a / price_b)
        if len(self._ratio) < self.warmup_bars:
            return []
        z = ind.zscore(self._ratio, self.params["lookback"])
        if z is None:
            return []
        ts = timestamp_of(bars[a])
        entry, exit_ = self.params["entry_z"], self.params["exit_z"]
        signals: list[Signal] = []
        if not self._open:
            if z > entry:      # A rich vs B -> short A, long B
                signals = [Signal(a, ts, SignalAction.SHORT),
                           Signal(b, ts, SignalAction.LONG)]
                self._open = True
            elif z < -entry:   # A cheap vs B -> long A, short B
                signals = [Signal(a, ts, SignalAction.LONG),
                           Signal(b, ts, SignalAction.SHORT)]
                self._open = True
        elif abs(z) < exit_:
            signals = [Signal(a, ts, SignalAction.EXIT),
                       Signal(b, ts, SignalAction.EXIT)]
            self._open = False
        return signals


class CrossSectionalMomentum(Strategy):
    """Rank the universe by trailing return; own the winners (and optionally short losers).

    Virtual positions are tracked from emitted signals. Rebalances whenever
    the top/bottom sets change.
    """

    name = "cross_sectional_momentum"
    family = "multi_asset"
    description = "Winner/loser rotation across the symbol universe."
    DEFAULT_PARAMS = {"lookback": 60, "top_n": 3, "long_only": True}

    def __init__(self, symbols: list[str], **params) -> None:
        super().__init__(symbols, **params)
        self._histories: dict[str, list[float]] = {s: [] for s in self.symbols}
        self._long: set[str] = set()
        self._short: set[str] = set()

    @property
    def warmup_bars(self) -> int:
        return self.params["lookback"] + 1

    def on_bar(self, timestamp: datetime, bars: dict) -> list[Signal]:
        for symbol in self.symbols:
            if symbol in bars:
                self._histories[symbol].append(float(field(bars[symbol], "close")))
        if any(len(h) < self.warmup_bars for h in self._histories.values()):
            return []
        scored = []
        for symbol, hist in self._histories.items():
            momentum = ind.roc(hist, self.params["lookback"])
            if momentum is not None:
                scored.append((momentum, symbol))
        scored.sort(reverse=True)
        top = {s for _, s in scored[: self.params["top_n"]]}
        bottom = set() if self.params["long_only"] else {s for _, s in scored[-self.params["top_n"] :]}
        signals: list[Signal] = []
        ts = timestamp
        for symbol in sorted(top - self._long):
            signals.append(Signal(symbol, ts, SignalAction.LONG))
        for symbol in sorted(self._long - top):
            signals.append(Signal(symbol, ts, SignalAction.EXIT))
        for symbol in sorted(bottom - self._short):
            signals.append(Signal(symbol, ts, SignalAction.SHORT))
        for symbol in sorted(self._short - bottom):
            signals.append(Signal(symbol, ts, SignalAction.EXIT))
        self._long, self._short = top, bottom
        return signals
