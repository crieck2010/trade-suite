"""Interop adapters: plain-data bridges to sibling suite modules.

All imports of siblings are lazy (inside functions) so ``trade-orderbook``
stays importable and testable on its own.
"""

from __future__ import annotations

from . import marketdata
from .analytics import estimate_slippage
from .book import OrderBook
from .models import Order


# ---------------------------------------------------------------- trade-agents

def to_agent_features(book: OrderBook, levels: int = 5,
                      symbol: str = "SYM") -> dict:
    """Microstructure features for researcher agents.

    Gives an agent the tape-level read — spread, imbalance, microprice —
    without handing it the engine.
    """
    feats = marketdata.features(book, levels=levels)
    feats["symbol"] = symbol
    feats["source"] = "trade-orderbook"
    return feats


# --------------------------------------------------------------- trade-backtest

def slippage_bps_for_backtest(book: OrderBook, side: str,
                              quantity: float) -> float:
    """Drop-in slippage estimate (bps) for trade-backtest's slippage hook.

    Returns +inf when the book cannot fill the quantity — the caller should
    treat that as "do not trade".
    """
    return estimate_slippage(book, side, quantity)["slippage_bps"]


def fills_for_paper_order(book: OrderBook, order: Order) -> list[dict]:
    """Simulate how ``trade-paper``'s FakeBroker would fill an order.

    Runs the order through a throwaway matching engine on a *copy* of the
    book state, so the live book is untouched.  Returns plain trade dicts.
    """
    from .engine import MatchingEngine

    mirror = MatchingEngine()
    # replay resting orders (limit only) into the mirror, oldest first
    for o in book.resting_orders():
        mirror.submit(Order(o.order_id, o.side, o.leaves, o.price,
                            order_type="limit", tif="GTC"))
    probe = Order(order.order_id + ":probe", order.side, order.quantity,
                  order.price, order.order_type, order.tif)
    _, trades = mirror.submit(probe)
    return [t.to_dict() for t in trades]


# ------------------------------------------------------------------ trade-risk

def depth_limit_check(book: OrderBook, side: str, quantity: float,
                      max_fraction: float = 0.10, levels: int = 5) -> dict:
    """Pre-trade depth check for trade-risk style limits.

    Flags orders that would consume more than ``max_fraction`` of visible
    top-of-book depth — a standard "don't be the market" guard.
    """
    opp = "ask" if side.lower() == "bid" else "bid"
    visible = sum(q for _, q in book.depth(opp, levels))
    ratio = (quantity / visible) if visible > 0 else float("inf")
    return {
        "side": side.lower(),
        "quantity": quantity,
        "visible_depth": visible,
        "fraction_of_depth": ratio,
        "passes": ratio <= max_fraction,
        "reason": (f"order is {ratio:.1%} of visible {opp} depth "
                   f"(limit {max_fraction:.0%})"),
    }
