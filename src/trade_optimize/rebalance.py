"""Rebalancing: turn target weights into concrete orders."""

from __future__ import annotations


def trades_to_target(current_qty: dict[str, float],
                     target_weights: dict[str, float],
                     prices: dict[str, float],
                     capital: float,
                     min_qty: float = 1e-9) -> list[dict]:
    """Compute the trades that move a portfolio to ``target_weights``.

    ``current_qty`` maps symbol → shares held (0 if absent); ``prices``
    maps symbol → price per share; ``capital`` is total portfolio value
    the weights are fractions of.  Returns plain order dicts with
    ``side`` in {"buy", "sell"} — the shape trade-paper's order queue
    expects.  Dust below ``min_qty`` is skipped.
    """
    if capital <= 0:
        raise ValueError("capital must be positive")
    if abs(sum(target_weights.values()) - 1.0) > 1e-6:
        raise ValueError("target weights must sum to 1")
    orders = []
    for sym, w in target_weights.items():
        price = prices.get(sym)
        if price is None or price <= 0:
            raise ValueError(f"missing/invalid price for {sym!r}")
        target_qty = w * capital / price
        delta = target_qty - current_qty.get(sym, 0.0)
        if abs(delta) < min_qty:
            continue
        orders.append({
            "symbol": sym,
            "side": "buy" if delta > 0 else "sell",
            "quantity": abs(delta),
            "price": price,
            "target_weight": w,
        })
    # liquidation of names that fell out of the target
    for sym, qty in current_qty.items():
        if sym not in target_weights and abs(qty) >= min_qty:
            price = prices.get(sym)
            if price is None or price <= 0:
                raise ValueError(f"missing/invalid price for {sym!r}")
            orders.append({"symbol": sym, "side": "sell", "quantity": abs(qty),
                           "price": price, "target_weight": 0.0})
    return orders
