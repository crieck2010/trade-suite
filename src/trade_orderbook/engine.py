"""The matching engine: price-time priority execution.

Semantics (standard continuous limit-order-book):
- Incoming orders match against the opposite side, best price first, then
  oldest (lowest sequence number) within a price level.
- Trade price is always the *resting* order's price.
- Limit orders match while the spread is crossed (buy price >= best ask,
  sell price <= best bid); any remainder rests if GTC.
- Market orders match until filled or the book is empty; remainders cancel.
- IOC: match what is available, cancel the rest.
- FOK: fill completely at acceptable prices or cancel with no partial fills.
"""

from __future__ import annotations

from .book import OrderBook
from .models import ASK, BID, Order, Trade


class MatchingEngine:
    def __init__(self, book: OrderBook | None = None) -> None:
        self.book = book or OrderBook()
        self._seq = 0  # time-priority sequence
        self._trade_id = 0
        self.trades: list[Trade] = []

    # ------------------------------------------------------------------

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _matchable_qty(self, order: Order) -> float:
        """Total opposite-side quantity available at acceptable prices."""
        opp = ASK if order.side == BID else BID
        total = 0.0
        for price, qty in self.book.depth(opp, levels=10**6):
            if not order.is_market:
                assert order.price is not None
                if order.side == BID and price > order.price:
                    break
                if order.side == ASK and price < order.price:
                    break
            total += qty
        return total

    # ------------------------------------------------------------------

    def submit(self, order: Order) -> tuple[Order, list[Trade]]:
        """Process one order.  Returns (order, trades from this submit)."""
        if order.side not in (BID, ASK):
            raise ValueError(f"side must be 'bid' or 'ask', got {order.side!r}")
        if order.quantity <= 0:
            raise ValueError("quantity must be positive")
        if not order.is_market and (order.price is None or order.price <= 0):
            raise ValueError("limit orders need a positive price")
        if order.tif not in ("GTC", "IOC", "FOK"):
            raise ValueError(f"unknown TIF {order.tif!r}")

        order.timestamp = self._next_seq()
        order.leaves = order.quantity
        trades: list[Trade] = []

        if order.tif == "FOK" and self._matchable_qty(order) < order.quantity:
            order.status = "cancelled"  # killed: could not fill completely
            return order, trades

        opp = ASK if order.side == BID else BID
        while order.leaves > 0:
            queue = self.book.best_queue(opp)
            if queue is None:
                break
            resting = queue[0]
            if not order.is_market:
                assert order.price is not None
                crossed = (resting.price <= order.price if order.side == BID
                           else resting.price >= order.price)
                if not crossed:
                    break
            fill = min(order.leaves, resting.leaves)
            self._trade_id += 1
            trades.append(Trade(
                trade_id=self._trade_id,
                price=resting.price,  # resting price wins
                quantity=fill,
                aggressor_side=order.side,
                resting_order_id=resting.order_id,
                aggressor_order_id=order.order_id,
                timestamp=order.timestamp,
            ))
            order.leaves -= fill
            resting.leaves -= fill
            if resting.leaves <= 0:
                resting.status = "filled"
                self.book.remove_filled(resting)
            else:
                resting.status = "partially_filled"

        self.trades.extend(trades)

        if order.leaves <= 0:
            order.status = "filled"
        elif order.is_market or order.tif in ("IOC", "FOK"):
            # remainder killed; any partial fills stand
            order.status = "cancelled"
        else:  # GTC limit with remainder -> rest on the book
            order.status = "partially_filled" if trades else "new"
            self.book.add(order)
        return order, trades

    # ------------------------------------------------------------------

    def cancel(self, order_id: str) -> bool:
        return self.book.cancel(order_id)

    def modify(self, order_id: str, *, price: float | None = None,
               quantity: float | None = None) -> Order | None:
        """Cancel/replace: the replaced order loses time priority (standard)."""
        old = self.book.get(order_id)
        if old is None:
            return None
        filled_qty = old.quantity - old.leaves
        self.book.cancel(order_id)
        new = Order(
            order_id=old.order_id,
            side=old.side,
            quantity=(quantity if quantity is not None else old.quantity) - filled_qty,
            price=old.price if price is None else price,
            order_type=old.order_type,
            tif=old.tif,
        )
        if new.quantity <= 0:
            return None
        order, _ = self.submit(new)
        return order
