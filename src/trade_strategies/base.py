"""Strategy interface and shared building blocks.

``trade-strategies`` deliberately does **not** import ``trade-backtest``:
strategies are pure decision logic over bar-like inputs, which keeps this
package independently installable and lets the agents compose strategies
without a backtester on hand. :mod:`trade_strategies.adapters` bridges to
``trade-backtest`` lazily (only when you actually run a backtest).

A *bar-like* is anything with ``timestamp/open/high/low/close/volume``
attributes or dict keys -- raw dicts, sibling engine bars, or
``trade_backtest.Bar`` all work.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class SignalAction(Enum):
    LONG = "long"
    SHORT = "short"
    EXIT = "exit"


@dataclass(frozen=True, slots=True)
class Signal:
    """A strategy's intent for one symbol at one timestamp."""

    symbol: str
    timestamp: datetime
    action: SignalAction
    strength: float = 1.0       # 0..1 conviction; sizers may scale by it
    limit_price: float | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("symbol must be a non-empty string")
        object.__setattr__(self, "symbol", symbol)
        ts = self.timestamp
        if ts.tzinfo is None:
            object.__setattr__(self, "timestamp", ts.replace(tzinfo=timezone.utc))
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"strength must be 0..1, got {self.strength!r}")


def field(bar, name: str, default=None):
    """Read a field from a dict-like or attribute-like bar."""
    if isinstance(bar, Mapping):
        return bar.get(name, default)
    return getattr(bar, name, default)


def closes(history: list) -> list[float]:
    return [float(field(b, "close")) for b in history]


def highs(history: list) -> list[float]:
    return [float(field(b, "high")) for b in history]


def lows(history: list) -> list[float]:
    return [float(field(b, "low")) for b in history]


def volumes(history: list) -> list[float]:
    return [float(field(bar, "volume", 0.0) or 0.0) for bar in history]


def timestamp_of(bar) -> datetime:
    ts = field(bar, "timestamp")
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


class Strategy(ABC):
    """Abstract strategy: bars in, signals out.

    Subclasses declare ``name``, ``family``, ``description``, and
    ``DEFAULT_PARAMS``. Agents enumerate the library through
    :mod:`trade_strategies.registry`, which reads exactly these fields.
    """

    name = "strategy"
    family = "general"
    description = ""
    DEFAULT_PARAMS: dict = {}

    def __init__(self, symbols: list[str], **params) -> None:
        self.symbols = [s.strip().upper() for s in symbols]
        if not self.symbols:
            raise ValueError("strategy needs at least one symbol")
        merged = dict(self.DEFAULT_PARAMS)
        unknown = set(params) - set(merged)
        if unknown:
            raise ValueError(f"unknown parameters for {self.name}: {sorted(unknown)}")
        merged.update(params)
        self.params = merged

    @abstractmethod
    def on_bar(self, timestamp: datetime, bars: dict) -> list[Signal]:
        """Return signals for this timestamp (possibly empty)."""
        raise NotImplementedError

    @property
    def warmup_bars(self) -> int:
        """Minimum bars before the first signal can fire."""
        return 1

    def get_parameters(self) -> dict:
        return dict(self.params)

    def describe(self) -> dict:
        """Agent-facing metadata: identity, family, params, warmup."""
        return {
            "name": self.name,
            "family": self.family,
            "description": self.description,
            "parameters": self.get_parameters(),
            "warmup_bars": self.warmup_bars,
            "symbols": list(self.symbols),
        }

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name}({', '.join(f'{k}={v}' for k, v in self.params.items())})"


class SingleAssetStrategy(Strategy):
    """Base for strategies that decide each symbol independently.

    Subclasses implement :meth:`on_symbol`, receiving the symbol's bar
    history (oldest -> newest, including the current bar). History length
    is capped at :meth:`history_bars` to bound memory on long runs.
    """

    def __init__(self, symbols: list[str], **params) -> None:
        super().__init__(symbols, **params)
        cap = self.history_bars()
        self._history: dict[str, deque] = {
            s: deque(maxlen=cap if cap else None) for s in self.symbols
        }
        self._regime: dict[str, int] = {}  # symbol -> 1 long / -1 short / 0 flat

    def _transition(self, symbol: str, target: int | None) -> int | None:
        """Edge-trigger helper: returns ``target`` only when the regime
        changed (1 long, -1 short, 0 flat); ``None`` means hold / no signal."""
        if target is None:
            return None
        prev = self._regime.get(symbol, 0)
        if target == prev:
            return None
        self._regime[symbol] = target
        return target

    def _signal_for(self, timestamp: datetime, symbol: str, regime: int,
                    long_only: bool = True, strength: float = 1.0) -> Signal:
        if regime == 1:
            return Signal(symbol, timestamp, SignalAction.LONG, strength=strength)
        if regime == -1:
            action = SignalAction.EXIT if long_only else SignalAction.SHORT
            return Signal(symbol, timestamp, action, strength=strength)
        return Signal(symbol, timestamp, SignalAction.EXIT, strength=strength)

    def history_bars(self) -> int | None:
        """Cap on stored bars per symbol; None = unbounded."""
        return self.warmup_bars + 5

    @abstractmethod
    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        raise NotImplementedError

    def on_bar(self, timestamp: datetime, bars: dict) -> list[Signal]:
        signals: list[Signal] = []
        for symbol in self.symbols:
            bar = bars.get(symbol)
            if bar is None:
                continue
            history = self._history[symbol]
            history.append(bar)
            if len(history) >= self.warmup_bars:
                signal = self.on_symbol(timestamp, symbol, list(history))
                if signal is not None:
                    signals.append(signal)
        return signals
