"""High-level client: contracts, bars, and continuous series.

:class:`FuturesDataClient` is the primary entry point:

* :meth:`get_contracts` -- listed contracts from the provider (cached).
* :meth:`get_bars` -- per-contract bars, cached and deduplicated.
* :meth:`get_continuous` -- front-month continuous series built with
  :func:`build_continuous` from per-contract bars. With providers that
  only serve a continuous feed (yfinance), this returns that feed
  directly; the real stitching happens with per-contract feeds.

For interop with ``trade-data-equities``: ``FuturesBar`` mirrors the
equity ``Bar`` shape (timestamp, OHLC, volume) plus ``open_interest``
and ``contract_code``, so downstream engines can treat them uniformly.
"""

from __future__ import annotations

from datetime import date
from typing import Iterator

from .cache import DiskCache
from .continuous import ContractSeries, build_continuous
from .exceptions import ContractNotFoundError
from .models import FuturesBar, FuturesContract, Timeframe
from .providers.base import FuturesDataProvider
from .symbols import parse_contract_code


class FuturesDataClient:
    """Fetch, cache, and stitch futures market data."""

    def __init__(
        self,
        provider: FuturesDataProvider,
        cache: DiskCache | None = None,
    ) -> None:
        self.provider = provider
        self.cache = cache if cache is not None else DiskCache()

    # -- contracts ------------------------------------------------------
    def get_contracts(self, root: str, n: int = 12, *, use_cache: bool = True) -> list[FuturesContract]:
        root = root.strip().upper()
        if use_cache and self.cache is not None:
            hit = self.cache.get_contracts(self.provider.name, root)
            if hit is not None:
                return hit[:n]
        contracts = self.provider.get_contracts(root, n)
        if use_cache and self.cache is not None:
            self.cache.put_contracts(self.provider.name, root, contracts)
        return contracts

    def get_contract(self, code: str) -> FuturesContract:
        """Resolve a contract code (``ESZ25``) against listed contracts."""
        root, year, month = parse_contract_code(code)
        for contract in self.get_contracts(root, n=24):
            if (contract.year, contract.month) == (year, month):
                return contract
        raise ContractNotFoundError(f"no listed contract for {code}")

    # -- bars -------------------------------------------------------------
    def get_bars(
        self,
        contract: FuturesContract | str,
        timeframe: Timeframe,
        start: date,
        end: date,
        *,
        use_cache: bool = True,
    ) -> list[FuturesBar]:
        """Bars for one contract over ``[start, end)``."""
        if isinstance(contract, str):
            contract = self.get_contract(contract)
        code = contract.contract_code
        if use_cache and self.cache is not None:
            hit = self.cache.get_bars(self.provider.name, code, timeframe, start, end)
            if hit is not None:
                return hit
        bars = self._dedup(self.provider.get_bars(contract, timeframe, start, end))
        if use_cache and self.cache is not None:
            self.cache.put_bars(self.provider.name, code, timeframe, start, end, bars)
        return bars

    @staticmethod
    def _dedup(bars: list[FuturesBar]) -> list[FuturesBar]:
        seen: dict = {}
        for bar in bars:
            seen[bar.timestamp] = bar
        return [seen[k] for k in sorted(seen)]

    # -- continuous ---------------------------------------------------------
    def get_continuous(
        self,
        root: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        *,
        contracts: list[FuturesContract] | None = None,
        roll: str = "volume",
        roll_days_before: int = 5,
        adjust: str = "ratio",
        use_cache: bool = True,
    ) -> list[FuturesBar]:
        """Front-month continuous series over ``[start, end)``.

        Fetches each listed contract's bars and stitches them with
        :func:`build_continuous`. Providers serving only a continuous
        feed (yfinance) return that feed tagged ``<ROOT>=F`` directly.
        """
        root = root.strip().upper()
        if contracts is None:
            contracts = self.get_contracts(root, use_cache=use_cache)
        if getattr(self.provider, "serves_continuous_only", False):
            # Continuous-only feed: one fetch of the front contract's feed,
            # tagged as the continuous series (no degenerate stitching).
            front = contracts[0]
            return [
                FuturesBar(
                    contract_code=f"{root}=F", timestamp=b.timestamp,
                    open=b.open, high=b.high, low=b.low, close=b.close,
                    volume=b.volume, open_interest=b.open_interest,
                    source_contract=front.contract_code,
                )
                for b in self.get_bars(front, timeframe, start, end, use_cache=use_cache)
            ]
        series = [
            ContractSeries(
                contract=c,
                bars=tuple(self.get_bars(c, timeframe, start, end, use_cache=use_cache)),
            )
            for c in contracts
        ]
        series = [s for s in series if s.bars]
        if not series:
            return []
        return build_continuous(series, roll=roll, roll_days_before=roll_days_before, adjust=adjust)

    def stream_bars(
        self,
        contract: FuturesContract | str,
        timeframe: Timeframe,
        start: date,
        end: date,
        *,
        chunk_days: int = 90,
        use_cache: bool = True,
    ) -> Iterator[FuturesBar]:
        """Yield bars in date chunks (bounded memory for long histories)."""
        from datetime import timedelta

        cursor = start
        while cursor < end:
            chunk_end = min(cursor + timedelta(days=chunk_days), end)
            yield from self.get_bars(contract, timeframe, cursor, chunk_end, use_cache=use_cache)
            cursor = chunk_end
