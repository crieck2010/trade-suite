"""Core models for futures market data.

Immutable, stdlib-only dataclasses. The key modeling difference from
equities: a futures *instrument* is a (root, expiry) pair, bars carry open
interest alongside volume, and contract specifications (multiplier, tick
size) turn price moves into P&L.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from math import isfinite


class Timeframe(Enum):
    HOURLY = "1h"
    DAILY = "1d"
    WEEKLY = "1wk"
    MONTHLY = "1mo"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class Settlement(Enum):
    CASH = "cash"
    PHYSICAL = "physical"


def ensure_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _nonneg(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a non-negative number, got {value!r}")
    return float(value)


def _positive(name: str, value: float) -> float:
    if not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive number, got {value!r}")
    return float(value)


@dataclass(frozen=True, slots=True)
class ContractSpec:
    """Exchange specification for one futures root.

    ``multiplier`` converts quoted price to currency per contract
    (e.g. ES: 50 USD per index point). ``tick_value`` is always
    ``multiplier * tick_size``. Values are reference data -- verify
    against the exchange before live use.
    """

    root: str
    description: str
    exchange: str
    currency: str
    multiplier: float
    tick_size: float
    settlement: Settlement
    cycle_months: tuple[int, ...]  # contract months, e.g. (3, 6, 9, 12)

    def __post_init__(self) -> None:
        root = self.root.strip().upper()
        if not root:
            raise ValueError("root must be a non-empty string")
        object.__setattr__(self, "root", root)
        _positive("multiplier", self.multiplier)
        _positive("tick_size", self.tick_size)
        if not self.cycle_months or any(not 1 <= m <= 12 for m in self.cycle_months):
            raise ValueError(f"cycle_months must be 1-12 month numbers, got {self.cycle_months!r}")
        object.__setattr__(self, "cycle_months", tuple(sorted(set(self.cycle_months))))

    @property
    def tick_value(self) -> float:
        """P&L per contract for a one-tick move, in ``currency``."""
        return self.multiplier * self.tick_size

    def pnl(self, entry: float, exit: float, quantity: float = 1.0) -> float:
        """P&L in ``currency`` for a long position."""
        return (exit - entry) * self.multiplier * quantity


@dataclass(frozen=True, slots=True)
class FuturesContract:
    """One listed futures contract: a root plus an expiry month."""

    root: str
    year: int
    month: int
    expiry: date | None = None  # last trading day; None when unknown
    spec: ContractSpec | None = None

    def __post_init__(self) -> None:
        root = self.root.strip().upper()
        if not root:
            raise ValueError("root must be a non-empty string")
        object.__setattr__(self, "root", root)
        if not 1 <= self.month <= 12:
            raise ValueError(f"month must be 1-12, got {self.month!r}")
        if self.expiry is not None and not isinstance(self.expiry, date):
            raise TypeError("expiry must be a datetime.date or None")

    @property
    def contract_code(self) -> str:
        """CME-style code, e.g. ``ESZ25``."""
        from .symbols import build_contract_code

        return build_contract_code(self.root, self.year, self.month)

    def __str__(self) -> str:
        return self.contract_code


@dataclass(frozen=True, slots=True)
class FuturesBar:
    """One OHLCV bar for a futures contract, plus open interest.

    ``contract_code`` is the listed code (``ESZ25``) or a continuous code
    (``ESc1``); ``source_contract`` records the listed contract behind a
    continuous bar, else None.
    """

    contract_code: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    open_interest: float | None = None
    source_contract: str | None = None

    def __post_init__(self) -> None:
        code = self.contract_code.strip().upper()
        if not code:
            raise ValueError("contract_code must be a non-empty string")
        object.__setattr__(self, "contract_code", code)
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        for name in ("open", "high", "low", "close"):
            # Futures can print negative prices (WTI, Apr-2020): only
            # finiteness is enforced.
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not isfinite(value):
                raise ValueError(f"{name} must be a finite number, got {value!r}")
        if not (self.low <= self.open <= self.high and self.low <= self.close <= self.high):
            raise ValueError(
                f"bar violates low <= open/close <= high: {self.low}, {self.open}, {self.close}, {self.high}"
            )
        _nonneg("volume", self.volume)
        object.__setattr__(self, "open_interest", _nonneg("open_interest", self.open_interest))
