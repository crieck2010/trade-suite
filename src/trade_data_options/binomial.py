"""Cox-Ross-Rubinstein binomial pricer for American and European options.

American exercise matters for US equity options (the engine's default
contract style): deep in-the-money puts and calls on dividend-paying
stocks can be worth more alive-exercised than the European value.
The CRR tree converges to Black-Scholes as steps grow; ``steps=200``
is a good default balancing accuracy and speed (O(steps^2) time,
O(steps) memory via the single-array backward induction).
"""

from __future__ import annotations

import math

from .models import OptionRight
from .pricing import intrinsic_value


def crr_price(
    right: OptionRight,
    s: float,
    k: float,
    t: float,
    r: float,
    sigma: float,
    q: float = 0.0,
    steps: int = 200,
    american: bool = True,
) -> float:
    """Price an option on a CRR binomial tree.

    :param american: when True, allow early exercise at every node.
    """
    if not math.isfinite(s) or s <= 0:
        raise ValueError(f"S must be positive, got {s!r}")
    if not math.isfinite(k) or k <= 0:
        raise ValueError(f"K must be positive, got {k!r}")
    if t <= 0:
        return intrinsic_value(right, s, k)
    if sigma <= 0:
        # Deterministic forward: option is worth discounted intrinsic of
        # the forward price, with early exercise for Americans.
        fwd = s * math.exp((r - q) * t)
        euro = math.exp(-r * t) * intrinsic_value(right, fwd, k)
        return max(euro, intrinsic_value(right, s, k)) if american else euro
    if steps < 1:
        raise ValueError(f"steps must be >= 1, got {steps!r}")

    dt = t / steps
    u = math.exp(sigma * math.sqrt(dt))
    d = 1.0 / u
    disc = math.exp(-r * dt)
    p = (math.exp((r - q) * dt) - d) / (u - d)

    # Asset prices and option values at expiry.
    values = [
        intrinsic_value(right, s * (u**j) * (d ** (steps - j)), k)
        for j in range(steps + 1)
    ]
    # Backward induction with a single array.
    for i in range(steps - 1, -1, -1):
        for j in range(i + 1):
            hold = disc * (p * values[j + 1] + (1.0 - p) * values[j])
            if american:
                spot = s * (u**j) * (d ** (i - j))
                exercise = intrinsic_value(right, spot, k)
                values[j] = max(hold, exercise)
            else:
                values[j] = hold
    return values[0]


def early_exercise_premium(
    right: OptionRight,
    s: float,
    k: float,
    t: float,
    r: float,
    sigma: float,
    q: float = 0.0,
    steps: int = 200,
) -> float:
    """American price minus European price on the same tree."""
    amer = crr_price(right, s, k, t, r, sigma, q, steps, american=True)
    euro = crr_price(right, s, k, t, r, sigma, q, steps, american=False)
    return amer - euro
