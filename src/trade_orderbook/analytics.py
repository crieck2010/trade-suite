"""Execution analytics: what would it cost to trade *now*?

``estimate_slippage`` walks the live book — the same walk a real order would
take — so backtests and risk checks can price liquidity instead of guessing
it in basis points.
"""

from __future__ import annotations

import math

from . import marketdata
from .book import OrderBook
from .models import BID, Trade


def estimate_slippage(book: OrderBook, side: str, quantity: float,
                      levels: int = 50) -> dict:
    """Walk the book like an incoming market order and price the fill.

    Returns the volume-weighted average fill price, slippage vs midprice in
    bps (positive = cost to the trader), filled quantity, and any shortfall
    when the book is too thin.  JSON-safe.
    """
    if side not in (BID, "bid", "ask", "ASK"):
        raise ValueError("side must be 'bid' or 'ask'")
    side = side.lower()
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    opp = "ask" if side == "bid" else "bid"  # a buy lifts the asks
    mid = marketdata.midprice(book)

    filled, cost = 0.0, 0.0
    for price, qty in book.depth(opp, levels):
        take = min(qty, quantity - filled)
        filled += take
        cost += take * price
        if filled >= quantity:
            break

    if filled <= 0 or mid is None or mid == 0:
        return {"avg_price": None, "midprice": mid, "slippage_bps": math.inf,
                "filled_qty": 0.0, "shortfall_qty": quantity,
                "side": side, "quantity": quantity}
    avg = cost / filled
    bps = (avg - mid) / mid * 10_000.0 if side == "bid" else (mid - avg) / mid * 10_000.0
    return {"avg_price": avg, "midprice": mid, "slippage_bps": bps,
            "filled_qty": filled, "shortfall_qty": quantity - filled,
            "side": side, "quantity": quantity}


def effective_spread(trades: list[Trade], mids: list[float | None]) -> float | None:
    """Mean 2·side·(trade_price − mid): what liquidity takers actually paid.

    ``mids[i]`` is the midprice just before ``trades[i]``; side is +1 for
    aggressor buys, −1 for aggressor sells.
    """
    vals = []
    for t, m in zip(trades, mids):
        if m is None:
            continue
        direction = 1.0 if t.aggressor_side == BID else -1.0
        vals.append(2.0 * direction * (t.price - m))
    return sum(vals) / len(vals) if vals else None


def kyle_lambda(trades: list[Trade], mid_before: list[float | None],
                mid_after: list[float | None]) -> float | None:
    """Crude Kyle's-lambda: OLS slope of midprice move on signed volume.

    Positive lambda = it costs more (in price movement) to trade size.
    """
    xs, ys = [], []
    for t, mb, ma in zip(trades, mid_before, mid_after):
        if mb is None or ma is None:
            continue
        signed = t.quantity if t.aggressor_side == BID else -t.quantity
        xs.append(signed)
        ys.append(ma - mb)
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
