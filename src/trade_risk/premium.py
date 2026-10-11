"""Short-premium risk primitives: "the stop loss is the credit collected".

A one-parameter risk discipline for premium-selling research (0DTE iron
flies, credit spreads): the stop distance on a short-premium position
equals the credit received for it.  No ATR multiples, no tuned
thresholds -- the premium itself is the ruler.

The mechanics
-------------
Consider a 0DTE iron fly: short an at-the-money call and put, long wings
``W`` points out.  If the underlying moves ``$X`` against the short
strike, the fly's value grows by roughly ``$X`` (the tested side's delta
runs toward 1.0) until it hits the structural cap of ``W - credit``.
Cutting the position when the adverse move reaches the credit therefore
locks the loss near the credit -- well inside the structural maximum.

Worked example
--------------
``$20`` credit on 50-wide wings:

* stop distance = ``credit_stop(20.0)`` = ``$20`` -- cut the fly when the
  underlying moves ``$20`` from the short strike;
* realised loss at the cut ~= ``$20`` (the fly repriced ~$1-per-$1);
* structural max loss = ``defined_risk_max_loss(50.0, 20.0)`` = ``$30``,
  so the discipline exits at two-thirds of the worst case, mechanically.

Sizing follows the same ruler: a credit-distance stop means one contract
risks ``credit`` dollars, so ``premium_size`` floors
``account * risk_pct / credit`` -- never rounding up, so the position can
only ever risk *less* than the stated fraction.

What this is not
---------------
This module is a *risk-definition primitive* for research, not an edge
and not a strategy.  It does not pick entries, time exits beyond the
cut rule, or know anything about brokers, fills, or live positions.
It is not wired into any strategy; consumers import it and apply it in
their own order path, exactly like :mod:`trade_risk.trailing`.

Everything here is stdlib-only and broker-free.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _positive_finite(name: str, value: float) -> float:
    """Validate a strictly-positive finite dollar amount."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number, got {type(value).__name__}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    if value <= 0.0:
        raise ValueError(f"{name} must be positive, got {value!r}")
    return value


def _unit_fraction(name: str, value: float) -> float:
    """Validate a fraction in [0, 1]."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number, got {type(value).__name__}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {value!r}")
    return value


def credit_stop(credit: float) -> float:
    """Stop distance for a short-premium position.

    The rule is the whole function: the stop *is* the credit collected.
    ``credit`` must be positive and finite; anything else raises
    :class:`ValueError` -- a zero or negative "credit" is a data error,
    never a tradable input.
    """
    return _positive_finite("credit", credit)


def defined_risk_max_loss(wing_width: float, credit: float) -> float:
    """Structural max loss of a defined-risk spread: ``wing_width - credit``.

    For an iron fly / iron condor, the most the position can ever lose is
    the wing width minus the premium received.  Requires
    ``wing_width > credit > 0`` (a spread whose wings don't cover its own
    credit is degenerate, not tradeable).
    """
    wing_width = _positive_finite("wing_width", wing_width)
    credit = _positive_finite("credit", credit)
    if wing_width <= credit:
        raise ValueError(
            f"wing_width ({wing_width!r}) must exceed credit ({credit!r})"
        )
    return wing_width - credit


def premium_size(account: float, risk_pct: float, credit: float) -> int:
    """Contracts such that a credit-distance stop risks ``risk_pct`` of account.

    ``contracts = floor(account * risk_pct / credit)``.  The floor is
    deliberate and never rounds up: the position can only ever risk *less*
    than the stated fraction.  Returns ``0`` when the account cannot afford
    a single contract (including ``risk_pct == 0``) -- the caller treats 0
    as "do not trade", not as an error.
    """
    account = _positive_finite("account", account)
    risk_pct = _unit_fraction("risk_pct", risk_pct)
    credit = _positive_finite("credit", credit)
    return int(math.floor(account * risk_pct / credit))


@dataclass(frozen=True)
class PremiumRiskProfile:
    """One short-premium position's risk, fully described.

    ``stop_distance`` is always the credit (see :func:`credit_stop`);
    ``max_loss`` is the structural cap (see :func:`defined_risk_max_loss`);
    ``contracts`` is the floored size (see :func:`premium_size`).
    ``reason`` is a human-readable one-liner for logs and ledgers.
    """

    credit: float
    stop_distance: float
    max_loss: float
    contracts: int
    reason: str

    def to_dict(self) -> dict:
        """Plain-data contract for journals, ledgers, and sibling engines."""
        return {
            "credit": self.credit,
            "stop_distance": self.stop_distance,
            "max_loss": self.max_loss,
            "contracts": self.contracts,
            "reason": self.reason,
        }


def premium_profile(
    credit: float, wing_width: float, account: float, risk_pct: float
) -> PremiumRiskProfile:
    """Build a :class:`PremiumRiskProfile` from raw inputs, validated once.

    All validation from :func:`credit_stop`,
    :func:`defined_risk_max_loss`, and :func:`premium_size` applies; the
    profile is just the three answers bundled with a readable reason.
    """
    stop = credit_stop(credit)
    cap = defined_risk_max_loss(wing_width, credit)
    n = premium_size(account, risk_pct, credit)
    reason = (
        f"stop=credit=${credit:.2f}; structural max loss ${cap:.2f}/contract; "
        f"{n} contract(s) risk {risk_pct:.1%} of ${account:,.2f}"
    )
    return PremiumRiskProfile(
        credit=float(credit),
        stop_distance=stop,
        max_loss=cap,
        contracts=n,
        reason=reason,
    )
