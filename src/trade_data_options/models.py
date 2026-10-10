"""Core models for listed options market data.

The models are plain immutable dataclasses with no third-party dependencies.
Providers produce them, the cache serializes them, and downstream engines
(backtesting, strategies, risk, agents) consume them.

Conventions
-----------
* Moneyness and time use the same UTC discipline as ``trade-data-equities``:
  all datetimes are tz-aware UTC.
* ``OptionQuote`` carries both the vendor's quoted implied volatility (when
  supplied) and optional model-derived fields (``model_iv``, ``greeks``)
  attached by the client during enrichment. Raw cached chains never carry
  model fields -- they are always recomputed on read.
* Greeks in :class:`Greeks` are **annualized** (theta per year, vega per 1.00
  = 100 vol points, rho per 1.00 = 100% rate move). See the ``per_day`` /
  ``per_point`` helpers for market conventions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from math import isfinite


class OptionRight(Enum):
    CALL = "C"
    PUT = "P"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class OptionStyle(Enum):
    AMERICAN = "american"  # US equity/ETF options
    EUROPEAN = "european"  # many index options

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


def ensure_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _positive(name: str, value: float) -> float:
    if not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value!r}")
    return float(value)


@dataclass(frozen=True, slots=True)
class OptionContract:
    """A single listed option contract.

    ``underlying`` is the normalized (upper-case) ticker of the underlying
    equity/ETF. ``multiplier`` is 100 for standard US equity options.
    """

    underlying: str
    expiry: date
    strike: float
    right: OptionRight
    style: OptionStyle = OptionStyle.AMERICAN
    multiplier: float = 100.0

    def __post_init__(self) -> None:
        underlying = self.underlying.strip().upper()
        if not underlying:
            raise ValueError("underlying must be a non-empty string")
        object.__setattr__(self, "underlying", underlying)
        if not isinstance(self.expiry, date):
            raise TypeError("expiry must be a datetime.date")
        _positive("strike", self.strike)
        if not isinstance(self.right, OptionRight):
            raise ValueError(f"right must be an OptionRight, got {self.right!r}")
        if not isinstance(self.style, OptionStyle):
            raise ValueError(f"style must be an OptionStyle, got {self.style!r}")
        _positive("multiplier", self.multiplier)

    @property
    def is_call(self) -> bool:
        return self.right is OptionRight.CALL

    @property
    def is_put(self) -> bool:
        return self.right is OptionRight.PUT

    @property
    def occ_symbol(self) -> str:
        """OCC option symbol, e.g. ``AAPL  260116C00250000``."""
        from .symbols import to_occ

        return to_occ(self.underlying, self.expiry, self.right, self.strike)

    def __str__(self) -> str:
        return self.occ_symbol


@dataclass(frozen=True, slots=True)
class Greeks:
    """First-order sensitivities, annualized (see module docstring)."""

    delta: float
    gamma: float
    theta: float  # per year; see theta_per_day
    vega: float  # per 1.00 (100 vol points); see vega_per_point
    rho: float  # per 1.00 (100% rate); see rho_per_point

    @property
    def theta_per_day(self) -> float:
        """Theta in price per calendar day (market convention)."""
        return self.theta / 365.0

    @property
    def vega_per_point(self) -> float:
        """Vega per 1 vol point (e.g. IV 20% -> 21%)."""
        return self.vega / 100.0

    @property
    def rho_per_point(self) -> float:
        """Rho per 1 percentage point of rates."""
        return self.rho / 100.0


@dataclass(frozen=True, slots=True)
class OptionQuote:
    """A quote snapshot for one contract.

    ``bid``/``ask``/``last`` may be None when the vendor omits them.
    ``implied_volatility`` is the vendor's quoted IV (decimal, e.g. 0.25);
    ``model_iv`` and ``greeks`` are attached by client enrichment.
    """

    contract: OptionContract
    timestamp: datetime
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    volume: float = 0.0
    open_interest: float = 0.0
    implied_volatility: float | None = None
    model_iv: float | None = None
    greeks: Greeks | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        for name in ("bid", "ask", "last"):
            value = getattr(self, name)
            if value is not None:
                # Zero bids/asks are common on illiquid contracts; only
                # negatives and non-finite values are rejected.
                if not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
                    raise ValueError(f"{name} must be a non-negative number, got {value!r}")
                object.__setattr__(self, name, float(value))
        for name in ("volume", "open_interest"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a non-negative number, got {value!r}")
            object.__setattr__(self, name, float(value))
        if self.implied_volatility is not None:
            _positive("implied_volatility", self.implied_volatility)
        if self.model_iv is not None:
            _positive("model_iv", self.model_iv)

    @property
    def mid(self) -> float | None:
        """Mid price, or None when bid/ask are missing."""
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid

    @property
    def reference_price(self) -> float | None:
        """Best available price for modeling: mid, else last."""
        return self.mid if self.mid is not None else self.last


@dataclass(frozen=True, slots=True)
class OptionChain:
    """All listed contracts for one underlying and expiry.

    ``underlying_price`` is the spot used for enrichment (None when the
    chain has not been enriched). ``asof`` is the quote timestamp.
    """

    underlying: str
    expiry: date
    asof: datetime
    calls: tuple[OptionQuote, ...] = ()
    puts: tuple[OptionQuote, ...] = ()
    underlying_price: float | None = None
    risk_free_rate: float = 0.0
    dividend_yield: float = 0.0

    def __post_init__(self) -> None:
        underlying = self.underlying.strip().upper()
        if not underlying:
            raise ValueError("underlying must be a non-empty string")
        object.__setattr__(self, "underlying", underlying)
        object.__setattr__(self, "asof", ensure_utc(self.asof))
        object.__setattr__(self, "calls", tuple(self.calls))
        object.__setattr__(self, "puts", tuple(self.puts))

    def __len__(self) -> int:
        return len(self.calls) + len(self.puts)

    @property
    def strikes(self) -> list[float]:
        """Sorted unique strikes across calls and puts."""
        return sorted({q.contract.strike for q in self.calls} | {q.contract.strike for q in self.puts})

    @property
    def enriched(self) -> bool:
        """True when quotes carry model IVs/greeks."""
        quotes = self.calls + self.puts
        return bool(quotes) and all(q.model_iv is not None for q in quotes)

    def atm_strike(self) -> float | None:
        """Strike nearest the underlying price."""
        if self.underlying_price is None or not self.strikes:
            return None
        return min(self.strikes, key=lambda k: abs(k - self.underlying_price))

    def filter(
        self,
        right: OptionRight | None = None,
        min_strike: float | None = None,
        max_strike: float | None = None,
        min_delta: float | None = None,
        max_delta: float | None = None,
        min_open_interest: float | None = None,
        in_the_money: bool | None = None,
    ) -> "OptionChain":
        """Return a sub-chain of quotes matching all given predicates.

        Delta bounds use absolute delta and require an enriched chain.
        """

        def keep(q: OptionQuote) -> bool:
            if right is not None and q.contract.right is not right:
                return False
            if min_strike is not None and q.contract.strike < min_strike:
                return False
            if max_strike is not None and q.contract.strike > max_strike:
                return False
            if min_open_interest is not None and q.open_interest < min_open_interest:
                return False
            if in_the_money is not None and self.underlying_price is not None:
                if q.contract.is_call:
                    itm = q.contract.strike < self.underlying_price
                else:
                    itm = q.contract.strike > self.underlying_price
                if itm is not in_the_money:
                    return False
            if (min_delta is not None or max_delta is not None):
                if q.greeks is None:
                    return False
                d = abs(q.greeks.delta)
                if min_delta is not None and d < min_delta:
                    return False
                if max_delta is not None and d > max_delta:
                    return False
            return True

        from dataclasses import replace

        return replace(
            self,
            calls=tuple(q for q in self.calls if keep(q)),
            puts=tuple(q for q in self.puts if keep(q)),
        )
