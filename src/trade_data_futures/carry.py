"""Cost-of-carry pricing for futures.

The fair value of a futures contract is the spot price grown at the net
cost of carry::

    F = S * exp(carry * T)

where ``carry`` is the all-in annualized rate: financing minus yield plus
storage minus convenience (whatever applies to the underlying). Two
helpers cover both directions: price a future from carry, or back out the
market's implied carry from a quoted future.
"""

from __future__ import annotations

import math


def fair_value(spot: float, carry: float, t_years: float) -> float:
    """Theoretical futures price ``S * exp(carry * T)``."""
    if spot <= 0:
        raise ValueError(f"spot must be positive, got {spot!r}")
    if t_years < 0:
        raise ValueError(f"t_years must be non-negative, got {t_years!r}")
    return spot * math.exp(carry * t_years)


def implied_carry(futures_price: float, spot: float, t_years: float) -> float:
    """Annualized carry implied by a quoted future: ``ln(F/S) / T``."""
    if futures_price <= 0 or spot <= 0:
        raise ValueError("futures_price and spot must be positive")
    if t_years <= 0:
        raise ValueError(f"t_years must be positive, got {t_years!r}")
    return math.log(futures_price / spot) / t_years


def basis(futures_price: float, spot: float) -> float:
    """Simple basis ``F - S`` (positive in contango)."""
    return futures_price - spot
