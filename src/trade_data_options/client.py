"""High-level client: fetch, cache, and enrich option chains.

:class:`OptionsDataClient` is the primary entry point. Given an
:class:`OptionsDataProvider` it:

* serves expiry lists and raw chains from :class:`DiskCache` when fresh,
* resolves the underlying spot price,
* enriches every quote with model implied volatility (from the mid price)
  and Black-Scholes greeks.

Enrichment assumptions live in exactly one place -- the client's
``risk_free_rate`` and ``dividend_yield`` -- and never leak into cached
data. For interop with ``trade-data-equities``, fetch the spot there and
pass it as ``underlying_price`` to skip the provider's price lookup.

Time convention: ``T = max(expiry - asof, 0) / 365`` in days. A chain
expiring today (0DTE) uses T = 6h as a documented approximation, since
Black-Scholes is degenerate at T = 0.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Iterator

from .analysis import atm_iv
from .cache import DiskCache
from .exceptions import ConvergenceError, ExpiryNotFoundError
from .models import Greeks, OptionChain, OptionQuote, OptionRight, ensure_utc
from .pricing import bs_greeks, implied_volatility
from .providers.base import OptionsDataProvider, RawChain
from .times import time_to_expiry


class OptionsDataClient:
    """Fetch, cache, and enrich listed option chains."""

    def __init__(
        self,
        provider: OptionsDataProvider,
        cache: DiskCache | None = None,
        risk_free_rate: float = 0.04,
        dividend_yield: float = 0.0,
    ) -> None:
        """
        :param provider: the options data source.
        :param cache: disk cache; a default one is created when omitted.
        :param risk_free_rate: annualized risk-free rate for enrichment.
        :param dividend_yield: annualized underlying dividend yield.
        """
        self.provider = provider
        self.cache = cache if cache is not None else DiskCache()
        self.risk_free_rate = risk_free_rate
        self.dividend_yield = dividend_yield

    # -- expiries ---------------------------------------------------------
    def get_expiries(self, underlying: str, *, use_cache: bool = True) -> list[date]:
        under = underlying.strip().upper()
        if use_cache and self.cache is not None:
            hit = self.cache.get_expiries(self.provider.name, under)
            if hit is not None:
                return hit
        expiries = sorted(self.provider.get_expiries(under))
        if use_cache and self.cache is not None:
            self.cache.put_expiries(self.provider.name, under, expiries)
        return expiries

    # -- chains -----------------------------------------------------------
    def get_chain(
        self,
        underlying: str,
        expiry: date | None = None,
        *,
        underlying_price: float | None = None,
        use_cache: bool = True,
        enrich: bool = True,
    ) -> OptionChain:
        """Return the enriched chain for ``expiry`` (nearest when omitted)."""
        under = underlying.strip().upper()
        if expiry is None:
            expiries = self.get_expiries(under, use_cache=use_cache)
            if not expiries:
                raise ExpiryNotFoundError(f"no listed expiries for {under}")
            expiry = expiries[0]

        raw = self._raw_chain(under, expiry, use_cache)
        spot = underlying_price
        if spot is None and enrich:
            try:
                spot = self.provider.get_underlying_price(under)
            except Exception:  # noqa: BLE001 - enrichment is best-effort
                spot = None

        chain = OptionChain(
            underlying=raw.underlying,
            expiry=raw.expiry,
            asof=raw.asof,
            calls=raw.calls,
            puts=raw.puts,
            underlying_price=spot,
            risk_free_rate=self.risk_free_rate,
            dividend_yield=self.dividend_yield,
        )
        if enrich and spot is not None:
            chain = self._enrich(chain)
        return chain

    def _raw_chain(self, underlying: str, expiry: date, use_cache: bool) -> RawChain:
        if use_cache and self.cache is not None:
            hit = self.cache.get_chain(self.provider.name, underlying, expiry)
            if hit is not None:
                return hit
        raw = self.provider.get_chain(underlying, expiry)
        if use_cache and self.cache is not None:
            self.cache.put_chain(self.provider.name, raw)
        return raw

    def _enrich(self, chain: OptionChain) -> OptionChain:
        assert chain.underlying_price is not None
        t = time_to_expiry(chain.expiry, chain.asof)
        r, q, s = self.risk_free_rate, self.dividend_yield, chain.underlying_price

        def enrich_quote(quote: OptionQuote) -> OptionQuote:
            price = quote.reference_price
            if price is None:
                return quote
            try:
                iv = implied_volatility(price, quote.contract.right, s, quote.contract.strike, t, r, q)
            except ConvergenceError:
                return quote
            greeks = bs_greeks(quote.contract.right, s, quote.contract.strike, t, r, iv, q)
            return replace(quote, model_iv=iv, greeks=greeks)

        return replace(
            chain,
            calls=tuple(enrich_quote(q) for q in chain.calls),
            puts=tuple(enrich_quote(q) for q in chain.puts),
        )

    # -- multi-expiry -------------------------------------------------------
    def stream_chains(
        self,
        underlying: str,
        expiries: list[date] | None = None,
        *,
        use_cache: bool = True,
    ) -> Iterator[OptionChain]:
        """Yield enriched chains one expiry at a time (bounded memory)."""
        under = underlying.strip().upper()
        if expiries is None:
            expiries = self.get_expiries(under, use_cache=use_cache)
        spot: float | None = None
        try:
            spot = self.provider.get_underlying_price(under)
        except Exception:  # noqa: BLE001 - best effort
            spot = None
        for expiry in expiries:
            yield self.get_chain(under, expiry, underlying_price=spot, use_cache=use_cache)

    def term_structure(self, underlying: str, n: int = 6, *, use_cache: bool = True) -> list[tuple[date, float | None]]:
        """ATM implied volatility per expiry for the nearest ``n`` expiries."""
        under = underlying.strip().upper()
        expiries = self.get_expiries(under, use_cache=use_cache)[:n]
        return [(expiry, atm_iv(self.get_chain(under, expiry, use_cache=use_cache))) for expiry in expiries]

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
