"""Market-data views over the book: BBO, midprice, spread, depth imbalance,
microprice.  All are pure functions of an OrderBook — cheap enough to call
per event or per snapshot.
"""

from __future__ import annotations

from .book import OrderBook


def bbo(book: OrderBook) -> tuple[float | None, float | None]:
    return book.best_bid, book.best_ask


def midprice(book: OrderBook) -> float | None:
    bid, ask = bbo(book)
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2.0


def spread(book: OrderBook) -> float | None:
    bid, ask = bbo(book)
    if bid is None or ask is None:
        return None
    return ask - bid


def spread_bps(book: OrderBook) -> float | None:
    sp, mid = spread(book), midprice(book)
    if sp is None or mid is None or mid == 0:
        return None
    return sp / mid * 10_000.0


def imbalance(book: OrderBook, levels: int = 5) -> float | None:
    """(bid qty − ask qty) / (bid qty + ask qty) over the top ``levels``.

    Ranges −1 (all offers) … +1 (all bids); a rough proxy for short-term
    price pressure.
    """
    bid_qty = sum(q for _, q in book.depth("bid", levels))
    ask_qty = sum(q for _, q in book.depth("ask", levels))
    total = bid_qty + ask_qty
    if total <= 0:
        return None
    return (bid_qty - ask_qty) / total


def microprice(book: OrderBook, levels: int = 1) -> float | None:
    """Imbalance-weighted midprice: heavy bid pressure pulls it toward the
    ask (the direction price is likely to move), and vice versa."""
    bid_qty = sum(q for _, q in book.depth("bid", levels))
    ask_qty = sum(q for _, q in book.depth("ask", levels))
    bid, ask = bbo(book)
    total = bid_qty + ask_qty
    if bid is None or ask is None or total <= 0:
        return None
    return (ask * bid_qty + bid * ask_qty) / total


def features(book: OrderBook, levels: int = 5, timestamp: int = 0) -> dict:
    """One flat feature dict for agents and analytics (JSON-safe)."""
    return {
        "timestamp": timestamp,
        "best_bid": book.best_bid,
        "best_ask": book.best_ask,
        "midprice": midprice(book),
        "spread": spread(book),
        "spread_bps": spread_bps(book),
        "imbalance": imbalance(book, levels),
        "microprice": microprice(book),
        "bid_depth": sum(q for _, q in book.depth("bid", levels)),
        "ask_depth": sum(q for _, q in book.depth("ask", levels)),
        "n_resting_orders": len(book),
    }
