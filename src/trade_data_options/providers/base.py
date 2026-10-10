"""Provider interface for listed options data.

Every source implements :class:`OptionsDataProvider`. Providers return
**raw** chains (vendor quotes, no model math); the client attaches the
underlying price, implied volatilities, and greeks during enrichment.
This keeps providers thin and interchangeable and keeps model
assumptions (rate, dividend yield, day count) in one place.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime

from ..exceptions import ProviderError
from ..models import OptionQuote, ensure_utc


@dataclass(frozen=True, slots=True)
class RawChain:
    """A provider's un-enriched chain snapshot for one expiry."""

    underlying: str
    expiry: date
    asof: datetime
    calls: tuple[OptionQuote, ...] = ()
    puts: tuple[OptionQuote, ...] = ()

    def __post_init__(self) -> None:
        underlying = self.underlying.strip().upper()
        if not underlying:
            raise ValueError("underlying must be a non-empty string")
        object.__setattr__(self, "underlying", underlying)
        object.__setattr__(self, "asof", ensure_utc(self.asof))
        object.__setattr__(self, "calls", tuple(self.calls))
        object.__setattr__(self, "puts", tuple(self.puts))


class OptionsDataProvider(ABC):
    """Abstract listed-options data source."""

    #: Human-readable source name, used in cache keys and logs.
    name: str = "base"

    #: Expected data delay in minutes (None = unknown).
    delay_minutes: int | None = None

    @abstractmethod
    def get_expiries(self, underlying: str) -> list[date]:
        """Listed expiry dates for ``underlying``, ascending."""
        raise NotImplementedError

    @abstractmethod
    def get_chain(self, underlying: str, expiry: date) -> RawChain:
        """Raw quote snapshot for one expiry (no model math attached)."""
        raise NotImplementedError

    def get_underlying_price(self, underlying: str) -> float:
        """Latest underlying price. Optional; default raises."""
        raise ProviderError(f"provider {self.name!r} does not supply underlying prices")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{type(self).__name__}(name={self.name!r})"
