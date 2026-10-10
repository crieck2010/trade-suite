"""The limit order book: price-time priority storage.

Bids are ordered highest-price-first, asks lowest-price-first; within a
price level, orders are FIFO by engine sequence number.  Heaps index the
price levels with lazy deletion (a level whose queue drained is skipped).
"""

from __future__ import annotations

import heapq
from collections import deque

from .models import ASK, BID, BookSnapshot, Order


class OrderBook:
    def __init__(self) -> None:
        self._bids: dict[float, deque[Order]] = {}
        self._asks: dict[float, deque[Order]] = {}
        self._bid_prices: list[float] = []  # max-heap via negation
        self._ask_prices: list[float] = []  # min-heap
        self._orders: dict[str, Order] = {}  # resting orders by id

    # ------------------------------------------------------------------
    # resting-order management
    # ------------------------------------------------------------------

    def add(self, order: Order) -> None:
        """Rest a limit order on the book (no matching)."""
        levels, heap = self._side_structs(order.side)
        if order.price not in levels:
            levels[order.price] = deque()
            heapq.heappush(heap, -order.price if order.side == BID else order.price)
        levels[order.price].append(order)
        self._orders[order.order_id] = order

    def cancel(self, order_id: str) -> bool:
        """Remove a resting order.  Returns False when unknown/already gone."""
        order = self._orders.pop(order_id, None)
        if order is None:
            return False
        levels, _ = self._side_structs(order.side)
        queue = levels.get(order.price)
        if queue is None:
            return False
        try:
            queue.remove(order)
        except ValueError:
            return False
        if not queue:
            del levels[order.price]  # heap entry lazily skipped later
        order.status = "cancelled"
        return True

    def get(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def resting_orders(self) -> list[Order]:
        """All resting orders, oldest (best time priority) first."""
        return sorted(self._orders.values(), key=lambda o: o.timestamp)

    # ------------------------------------------------------------------
    # price-level access (matching engine use)
    # ------------------------------------------------------------------

    def _side_structs(self, side: str) -> tuple[dict[float, deque[Order]], list[float]]:
        if side == BID:
            return self._bids, self._bid_prices
        if side == ASK:
            return self._asks, self._ask_prices
        raise ValueError(f"side must be 'bid' or 'ask', got {side!r}")

    def _best_price(self, side: str) -> float | None:
        levels, heap = self._side_structs(side)
        while heap:
            raw = heap[0]
            price = -raw if side == BID else raw
            queue = levels.get(price)
            if queue:
                return price
            heapq.heappop(heap)  # stale entry for a drained level
        return None

    @property
    def best_bid(self) -> float | None:
        return self._best_price(BID)

    @property
    def best_ask(self) -> float | None:
        return self._best_price(ASK)

    def best_queue(self, side: str) -> deque[Order] | None:
        """The FIFO queue at the best price of ``side`` (for matching)."""
        price = self._best_price(side)
        if price is None:
            return None
        levels, _ = self._side_structs(side)
        return levels[price]

    def remove_filled(self, order: Order) -> None:
        """Drop a fully-filled resting order from the book."""
        self._orders.pop(order.order_id, None)
        levels, _ = self._side_structs(order.side)
        queue = levels.get(order.price)
        if queue:
            try:
                queue.remove(order)
            except ValueError:
                pass
            if not queue:
                del levels[order.price]

    # ------------------------------------------------------------------
    # views
    # ------------------------------------------------------------------

    def depth(self, side: str, levels: int = 5) -> list[tuple[float, float]]:
        """Aggregate (price, total qty) per level, best-first."""
        out: list[tuple[float, float]] = []
        book_levels, _ = self._side_structs(side)
        prices = sorted(book_levels, reverse=(side == BID))[:levels]
        for p in prices:
            out.append((p, sum(o.leaves for o in book_levels[p])))
        return out

    def snapshot(self, timestamp: int = 0, levels: int = 5) -> BookSnapshot:
        return BookSnapshot(
            timestamp=timestamp,
            bids=self.depth(BID, levels),
            asks=self.depth(ASK, levels),
        )

    def __len__(self) -> int:
        return len(self._orders)
