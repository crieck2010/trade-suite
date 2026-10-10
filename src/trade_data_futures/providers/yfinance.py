"""Futures provider backed by yfinance (free, delayed).

Yahoo serves futures as continuous front-month series (``ES=F``); it does
not publish per-contract histories. Consequently:

* :meth:`get_contracts` lists contracts from the local expiry calendar
  (real listed months, approximate last-trading dates).
* :meth:`get_bars` returns the **continuous front-month** series for any
  requested contract and tags bars with that contract's code -- treat it
  as the front-month proxy, not true per-contract data.

For genuine per-contract histories (volume/OI by expiry, true back-
adjusted rolls), plug in a paid feed behind :class:`FuturesDataProvider`.

yfinance is an *optional* dependency, imported lazily::

    pip install trade-data-futures[yfinance]
"""

from __future__ import annotations

import math
import time
from datetime import date, datetime, timezone

from ..calendar import ContractCalendar
from ..exceptions import ProviderError, RateLimitError, UnknownRootError
from ..models import FuturesBar, FuturesContract, Timeframe
from ..specs import known_roots
from .base import FuturesDataProvider

_INTERVALS = {
    Timeframe.HOURLY: "1h",
    Timeframe.DAILY: "1d",
    Timeframe.WEEKLY: "1wk",
    Timeframe.MONTHLY: "1mo",
}

#: Roots with a Yahoo ``<ROOT>=F`` continuous ticker.
_YAHOO_ROOTS = {
    "ES", "MES", "NQ", "MNQ", "YM", "RTY",
    "CL", "NG", "HO", "RB", "GC", "SI", "HG",
    "ZC", "ZS", "ZW", "6E", "6J", "6B", "ZB", "ZN",
}


class YFinanceFuturesProvider(FuturesDataProvider):
    """Free delayed front-month futures via the yfinance package."""

    name = "yfinance"
    delay_minutes = 15
    serves_continuous_only = True

    def __init__(self, min_interval: float = 0.5, max_retries: int = 3) -> None:
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._last_call = 0.0

    # -- internals ----------------------------------------------------
    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _ticker(self, yahoo_symbol: str):
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ProviderError(
                "yfinance is not installed; run `pip install trade-data-futures[yfinance]`"
            ) from exc
        return yf.Ticker(yahoo_symbol)

    def _call(self, func, *args, **kwargs):
        last: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - vendor errors vary
                last = exc
                if "429" in str(exc) or "rate" in str(exc).lower():
                    raise RateLimitError(f"yfinance rate limit hit: {exc}") from exc
                time.sleep(2**attempt)
        raise ProviderError(
            f"yfinance request failed after {self.max_retries} attempts: {last}"
        ) from last

    # -- FuturesDataProvider -------------------------------------------
    def get_contracts(self, root: str, n: int = 12) -> list[FuturesContract]:
        return ContractCalendar(root=root).upcoming(n)

    def get_bars(
        self,
        contract: FuturesContract,
        timeframe: Timeframe,
        start: date,
        end: date,
    ) -> list[FuturesBar]:
        root = contract.root
        if root not in _YAHOO_ROOTS:
            raise ProviderError(f"yfinance has no continuous ticker for root {root!r}")
        ticker = self._ticker(f"{root}=F")
        frame = self._call(
            ticker.history,
            start=start.isoformat(),
            end=end.isoformat(),
            interval=_INTERVALS[timeframe],
            auto_adjust=False,
            actions=False,
        )
        bars: list[FuturesBar] = []
        for ts, row in frame.iterrows():
            try:
                stamp = ts.to_pydatetime()
            except (AttributeError, TypeError, ValueError):
                continue
            if stamp != stamp:  # NaT guard
                continue
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            vals = {k: _num(row.get(k)) for k in ("Open", "High", "Low", "Close", "Volume")}
            if vals["Open"] is None or vals["Close"] is None:
                continue
            bars.append(
                FuturesBar(
                    contract_code=contract.contract_code,
                    timestamp=stamp,
                    open=vals["Open"],
                    high=vals["High"] if vals["High"] is not None else vals["Open"],
                    low=vals["Low"] if vals["Low"] is not None else vals["Open"],
                    close=vals["Close"],
                    volume=vals["Volume"] or 0.0,
                    open_interest=None,  # yfinance futures carry no OI
                )
            )
        return sorted(bars, key=lambda b: b.timestamp)


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
