"""Chain analytics: pure functions over enriched (or raw) chains.

Everything here is provider-agnostic and side-effect free, so the same
analytics run on live chains, cached chains, and synthetic chains in
backtests.
"""

from __future__ import annotations

import math
from datetime import date

from .models import OptionChain, OptionQuote, OptionRight
from .times import time_to_expiry


def _paired_quotes(chain: OptionChain) -> list[tuple[OptionQuote, OptionQuote]]:
    """Match calls to puts by strike."""
    puts_by_strike = {q.contract.strike: q for q in chain.puts}
    return [(c, puts_by_strike[c.contract.strike]) for c in chain.calls if c.contract.strike in puts_by_strike]


def put_call_parity_deviation(
    call: OptionQuote,
    put: OptionQuote,
    s: float,
    t: float,
    r: float,
    q: float = 0.0,
) -> float | None:
    """Deviation from put-call parity: ``(C - P) - (S*e^-qT - K*e^-rT)``.

    Returns None when either quote lacks a reference price. Persistent
    non-zero values flag stale quotes, bad IVs, or early-exercise effects
    (American options) rather than arbitrage.
    """
    c, p = call.reference_price, put.reference_price
    if c is None or p is None:
        return None
    k = call.contract.strike
    return (c - p) - (s * math.exp(-q * t) - k * math.exp(-r * t))


def parity_report(chain: OptionChain) -> list[tuple[float, float]]:
    """``(strike, deviation)`` for every strike with both a call and a put."""
    if chain.underlying_price is None:
        return []
    t = time_to_expiry(chain.expiry, chain.asof)
    out = []
    for call, put in _paired_quotes(chain):
        dev = put_call_parity_deviation(
            call, put, chain.underlying_price, t, chain.risk_free_rate, chain.dividend_yield
        )
        if dev is not None:
            out.append((call.contract.strike, dev))
    return sorted(out)


def max_pain(chain: OptionChain) -> tuple[float, float] | None:
    """Strike minimizing total option-writer payout at expiry.

    Returns ``(strike, payout)``. Payout at candidate ``s`` is
    ``sum(call_oi * max(s - K, 0) + put_oi * max(K - s, 0))`` over all
    quotes with open interest. Returns None for an empty chain.
    """
    strikes = chain.strikes
    if not strikes:
        return None
    quotes = chain.calls + chain.puts
    best: tuple[float, float] | None = None
    for s in strikes:
        payout = 0.0
        for quote in quotes:
            k = quote.contract.strike
            if quote.contract.is_call:
                payout += quote.open_interest * max(s - k, 0.0)
            else:
                payout += quote.open_interest * max(k - s, 0.0)
        if best is None or payout < best[1]:
            best = (s, payout)
    return best


def volatility_smile(chain: OptionChain, right: OptionRight) -> list[tuple[float, float]]:
    """``(strike, model_iv)`` sorted by strike for one side of the chain."""
    quotes = chain.calls if right is OptionRight.CALL else chain.puts
    return sorted(
        (q.contract.strike, q.model_iv) for q in quotes if q.model_iv is not None
    )


def atm_iv(chain: OptionChain) -> float | None:
    """Average model IV of the call and put nearest the money."""
    strike = chain.atm_strike()
    if strike is None:
        return None
    ivs = [
        q.model_iv
        for q in chain.calls + chain.puts
        if q.contract.strike == strike and q.model_iv is not None
    ]
    if not ivs:
        return None
    return sum(ivs) / len(ivs)


def breakevens(chain: OptionChain, right: OptionRight, strike: float) -> tuple[float, ...]:
    """Placeholder-free breakeven strikes for single-leg positions.

    Kept here (rather than in strategies) because it needs nothing but a
    quote: breakeven = strike +/- premium paid.
    """
    side = chain.calls if right is OptionRight.CALL else chain.puts
    for q in side:
        if q.contract.strike == strike and q.reference_price is not None:
            premium = q.reference_price
            if right is OptionRight.CALL:
                return (strike + premium,)
            return (strike - premium,)
    return ()
