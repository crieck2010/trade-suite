"""Provider interface for futures market data."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from ..exceptions import ProviderError
from ..models import FuturesBar, FuturesContract, Timeframe


class FuturesDataProvider(ABC):
    """Abstract futures data source."""

    #: Human-readable source name, used in cache keys and logs.
    name: str = "base"

    #: Expected data delay in minutes (None = unknown).
    delay_minutes: int | None = None

    #: True when the provider only serves a continuous front-month feed
    #: (e.g. yfinance ``ES=F``) rather than true per-contract histories.
    #: The client then tags that feed directly instead of stitching.
    serves_continuous_only: bool = False

    @abstractmethod
    def get_contracts(self, root: str, n: int = 12) -> list[FuturesContract]:
        """Next ``n`` listed contracts for ``root``, nearest first."""
        raise NotImplementedError

    @abstractmethod
    def get_bars(
        self,
        contract: FuturesContract,
        timeframe: Timeframe,
        start: date,
        end: date,
    ) -> list[FuturesBar]:
        """Bars for one contract over ``[start, end)``."""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{type(self).__name__}(name={self.name!r})"
