"""Expected Move (EM): deterministic arithmetic on an option chain.

The maths
---------
The expected move to an expiry is the price of the at-the-money straddle::

    EM (points) = C_ATM + P_ATM
    EM (%)      = EM (points) / S

where ``C_ATM`` and ``P_ATM`` are the market prices of the call and the put
struck nearest the underlying spot ``S``. Under risk-neutral pricing this
is the market's implied one-standard-deviation move to expiry: it is read
off quoted prices, not estimated from history and not produced by any
model. The ±1 and ±2 bands are::

    1x low / high = S -/+ EM
    2x low / high = S -/+ 2 * EM

Quote prices are mids ``(bid + ask) / 2``. A leg falls back to its ``last``
print only when no usable mid exists, and the result is then flagged with
``price_source="last"`` so a reader can never mistake it for a mid-based
read. Quotes with zero, negative, or non-finite mids are skipped
(signed-safe: this codebase has been bitten by negative prints before).

ATM selection uses the strike nearest the underlying *spot*. A forward-price
variant (strike nearest ``S * e^((r-q)T)``) is a possible follow-up; it is
deliberately not in this build.

Each expiry is computed from its own chain. No ``sqrt(T)`` scaling is
applied by default. :func:`scale_expected_move` exists as a documented
estimator for the case where only one expiry is available -- it is an
estimator, not a quote.

What this is NOT
---------------
This module is descriptive, not predictive. It reports what the option
market currently implies about the size of a move; it says nothing about
where the underlying will actually go, and the word "prediction" must
never appear in connection with it. It is a research tool, not a
strategy: there are no entry triggers, exit triggers, or spread-selection
rules here, and none may be added to this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import isfinite, sqrt

from .exceptions import NoUsableQuoteError, OptionsDataError
from .models import OptionQuote, ensure_utc


def _require_spot(value: float) -> float:
    if not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
        raise ValueError(f"underlying_price must be a positive finite number, got {value!r}")
    return float(value)


def _leg_price(quote: OptionQuote, allow_last_fallback: bool) -> tuple[float, str] | None:
    """Usable price for one straddle leg: (price, "mid" | "last")."""
    mid = quote.mid
    if mid is not None and isfinite(mid) and mid > 0:
        return mid, "mid"
    if not allow_last_fallback:
        return None
    last = quote.last
    if last is not None and isfinite(last) and last > 0:
        return last, "last"
    return None


@dataclass(frozen=True, slots=True)
class ExpectedMove:
    """The market-implied one-sigma move to an expiry, from quoted prices.

    ``price_source`` is ``"mid"`` only when *both* legs priced off mids;
    otherwise it is ``"last"``. ``data_delayed`` is True when the provider
    reports a quote delay (or an unknown one).
    """

    underlying: str
    expiry: date
    atm_strike: float
    call_price: float
    put_price: float
    em_points: float
    em_pct: float
    band_1_low: float
    band_1_high: float
    band_2_low: float
    band_2_high: float
    as_of: datetime
    price_source: str  # "mid" | "last"
    data_delayed: bool
    provider_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "underlying", self.underlying.strip().upper())
        object.__setattr__(self, "as_of", ensure_utc(self.as_of))
        if self.price_source not in ("mid", "last"):
            raise ValueError(f"price_source must be 'mid' or 'last', got {self.price_source!r}")


def expected_move(
    underlying_price: float,
    calls: list[OptionQuote] | tuple[OptionQuote, ...],
    puts: list[OptionQuote] | tuple[OptionQuote, ...],
    *,
    expiry: date,
    as_of: datetime | None = None,
    underlying: str = "",
    data_delayed: bool = True,
    provider_name: str | None = None,
    allow_last_fallback: bool = True,
) -> ExpectedMove:
    """Compute the expected move from one expiry's call/put quotes.

    The ATM strike is the strike nearest ``underlying_price`` (exact ties
    resolve to the lower strike) among strikes that have a usable price on
    *both* legs. Strikes missing a usable call or put are skipped. With
    ``allow_last_fallback=False`` a leg without a usable mid is unusable
    even when it has a ``last`` print. Raises :class:`NoUsableQuoteError`
    when no strike has both legs priced.
    """
    spot = _require_spot(underlying_price)
    calls_by_strike = {q.contract.strike: q for q in calls}
    puts_by_strike = {q.contract.strike: q for q in puts}
    # Sorted ascending so exact distance ties resolve to the lower strike.
    candidates = sorted(set(calls_by_strike) & set(puts_by_strike))
    best: tuple[float, float, float, str] | None = None  # (dist, strike, price_sum, source)
    best_legs: tuple[float, float] | None = None
    for strike in candidates:
        call_leg = _leg_price(calls_by_strike[strike], allow_last_fallback)
        put_leg = _leg_price(puts_by_strike[strike], allow_last_fallback)
        if call_leg is None or put_leg is None:
            continue
        (call_px, call_src), (put_px, put_src) = call_leg, put_leg
        source = "mid" if call_src == "mid" and put_src == "mid" else "last"
        dist = abs(strike - spot)
        if best is None or dist < best[0]:
            best = (dist, strike, call_px + put_px, source)
            best_legs = (call_px, put_px)
    if best is None or best_legs is None:
        raise NoUsableQuoteError(
            f"no strike with usable call+put quotes for expiry {expiry}"
        )
    _, strike, em_points, source = best
    call_px, put_px = best_legs
    em_pct = em_points / spot
    stamp = as_of if as_of is not None else datetime.now(timezone.utc)
    return ExpectedMove(
        underlying=underlying,
        expiry=expiry,
        atm_strike=strike,
        call_price=call_px,
        put_price=put_px,
        em_points=em_points,
        em_pct=em_pct,
        band_1_low=spot - em_points,
        band_1_high=spot + em_points,
        band_2_low=spot - 2.0 * em_points,
        band_2_high=spot + 2.0 * em_points,
        as_of=stamp,
        price_source=source,
        data_delayed=data_delayed,
        provider_name=provider_name,
    )


def scale_expected_move(em_points: float, from_days: float, to_days: float) -> float:
    """Rough ``sqrt(T)`` rescaling of an EM between horizons.

    ``EM(to) ≈ EM(from) * sqrt(to_days / from_days)``. This is an
    *estimator* for when only one expiry's chain is available -- it assumes
    flat variance across the window, which real term structures violate.
    Prefer computing each expiry from its own chain. Never present the
    output as a quoted expected move.
    """
    if not isfinite(em_points) or em_points < 0:
        raise ValueError(f"em_points must be a non-negative finite number, got {em_points!r}")
    if not isfinite(from_days) or from_days <= 0:
        raise ValueError(f"from_days must be positive, got {from_days!r}")
    if not isfinite(to_days) or to_days <= 0:
        raise ValueError(f"to_days must be positive, got {to_days!r}")
    return em_points * sqrt(to_days / from_days)


def expected_move_for_expiry(
    provider,  # OptionsDataProvider -- untyped to keep this module provider-agnostic
    underlying: str,
    expiry: date,
    *,
    allow_last_fallback: bool = True,
) -> ExpectedMove:
    """Convenience: EM for one expiry from any options data provider.

    Works with every :class:`OptionsDataProvider` implementation --
    yfinance today, ThetaData/Alpaca later -- with no calculator changes.
    Raises :class:`OptionsDataError` when the chain is missing, the
    underlying price is unavailable, or no strike has usable quotes.
    """
    from .providers.base import OptionsDataProvider

    if not isinstance(provider, OptionsDataProvider):
        raise TypeError(
            f"provider must be an OptionsDataProvider, got {type(provider).__name__}"
        )
    chain = provider.get_chain(underlying, expiry)
    spot = provider.get_underlying_price(underlying)
    delay = provider.delay_minutes
    return expected_move(
        spot,
        chain.calls,
        chain.puts,
        expiry=chain.expiry,
        as_of=chain.asof,
        underlying=chain.underlying,
        data_delayed=(delay is None or delay > 0),
        provider_name=provider.name,
        allow_last_fallback=allow_last_fallback,
    )
