"""Options provider backed by yfinance (free, delayed).

Expiries, chains, and a reference underlying price come from Yahoo Finance.
Data is delayed ~15 minutes and intended for research, backtesting, and
paper trading -- not for live execution.

yfinance is an *optional* dependency, imported lazily::

    pip install trade-data-options[yfinance]
"""

from __future__ import annotations

import math
import time
from datetime import date, datetime, timezone

from ..exceptions import ExpiryNotFoundError, ProviderError, RateLimitError
from ..models import (
    OptionContract,
    OptionQuote,
    OptionRight,
    OptionStyle,
    ensure_utc,
)
from ..symbols import parse_occ
from .base import OptionsDataProvider, RawChain


def _num(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


class YFinanceOptionsProvider(OptionsDataProvider):
    """Free delayed options chains via the yfinance package."""

    name = "yfinance"
    delay_minutes = 15

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

    def _ticker(self, underlying: str):
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ProviderError(
                "yfinance is not installed; run `pip install trade-data-options[yfinance]`"
            ) from exc
        return yf.Ticker(underlying.strip().upper())

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

    @staticmethod
    def _quotes(df, underlying: str, expiry: date, right: OptionRight, asof: datetime) -> list[OptionQuote]:
        quotes: list[OptionQuote] = []
        for _, row in df.iterrows():
            occ = str(row.get("contractSymbol", ""))
            try:
                contract = parse_occ(occ)
            except Exception:  # noqa: BLE001 - fall back to row fields
                strike = _num(row.get("strike"))
                if strike is None:
                    continue
                contract = OptionContract(
                    underlying=underlying, expiry=expiry, strike=strike,
                    right=right, style=OptionStyle.AMERICAN,
                )
            trade_ts = row.get("lastTradeDate")
            stamp = asof
            try:
                candidate = ensure_utc(trade_ts.to_pydatetime())
            except (AttributeError, TypeError, ValueError):
                candidate = None
            # pandas NaT survives to_pydatetime() in some versions; it is
            # the only datetime-like value that is not equal to itself.
            if candidate is not None and candidate == candidate:
                stamp = candidate
            quotes.append(
                OptionQuote(
                    contract=contract,
                    timestamp=stamp,
                    bid=_num(row.get("bid")),
                    ask=_num(row.get("ask")),
                    last=_num(row.get("lastPrice")),
                    volume=_num(row.get("volume"), 0.0) or 0.0,
                    open_interest=_num(row.get("openInterest"), 0.0) or 0.0,
                    implied_volatility=_num(row.get("impliedVolatility")),
                )
            )
        quotes.sort(key=lambda q: q.contract.strike)
        return quotes

    # -- OptionsDataProvider -------------------------------------------
    def get_expiries(self, underlying: str) -> list[date]:
        ticker = self._ticker(underlying)
        raw = self._call(lambda: ticker.options)
        expiries = []
        for item in raw or []:
            try:
                expiries.append(date.fromisoformat(str(item)))
            except ValueError:
                continue
        return sorted(expiries)

    def get_chain(self, underlying: str, expiry: date) -> RawChain:
        ticker = self._ticker(underlying)
        under = underlying.strip().upper()
        try:
            result = self._call(ticker.option_chain, expiry.isoformat())
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ExpiryNotFoundError(f"no {under} chain for expiry {expiry}: {exc}") from exc
        asof = datetime.now(timezone.utc)
        calls = self._quotes(result.calls, under, expiry, OptionRight.CALL, asof)
        puts = self._quotes(result.puts, under, expiry, OptionRight.PUT, asof)
        if not calls and not puts:
            raise ExpiryNotFoundError(f"no {under} chain for expiry {expiry}")
        return RawChain(underlying=under, expiry=expiry, asof=asof, calls=tuple(calls), puts=tuple(puts))

    def get_underlying_price(self, underlying: str) -> float:
        ticker = self._ticker(underlying)
        try:
            price = _num(self._call(lambda: ticker.fast_info.last_price))
        except ProviderError:
            price = None
        if price is None:
            hist = self._call(ticker.history, period="1d", interval="1d", auto_adjust=False, actions=False)
            if hist is None or len(hist) == 0:
                raise ProviderError(f"yfinance has no price for {underlying}")
            price = float(hist["Close"].iloc[-1])
        return price
