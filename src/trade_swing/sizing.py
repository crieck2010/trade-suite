"""ATR position sizing: risk a fixed fraction of equity per trade.

``shares = floor((equity * risk_per_trade) / (atr * stop_multiple))``

The denominator is the dollar risk per share if the trailing stop is hit,
so a stopped-out trade loses approximately ``risk_per_trade`` of equity —
the position is *volatility-normalized*: calm stocks get bigger positions,
wild stocks get smaller ones, for the same dollar risk.
"""

from __future__ import annotations

import math


def atr_position_size(equity: float, atr: float, stop_multiple: float,
                      risk_per_trade: float, price: float,
                      max_position_pct: float = 0.25) -> int:
    """Whole shares to buy. Returns 0 when sizing is impossible.

    The ``max_position_pct`` cap keeps a tiny-ATR stock from becoming an
    outsized portfolio bet: ``shares * price <= equity * max_position_pct``.
    """
    if equity <= 0 or price <= 0:
        return 0
    if atr is None or atr <= 0 or stop_multiple <= 0:
        return 0
    if not 0 < risk_per_trade <= 1:
        raise ValueError(f"risk_per_trade must be in (0, 1], got {risk_per_trade}")
    risk_amount = equity * risk_per_trade
    risk_per_share = atr * stop_multiple
    shares = math.floor(risk_amount / risk_per_share)
    max_shares = math.floor(equity * max_position_pct / price)
    return max(0, min(shares, max_shares))
