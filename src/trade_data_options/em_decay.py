"""EM-decay entry trigger: a timing filter on premium decay.

The maths
---------
Let ``EM_open`` be the at-the-money straddle price at the *opening* of the
session for a given expiry (see :mod:`trade_data_options.expected_move`),
and let ``C_t + P_t`` be the current ATM straddle for the same expiry.
The decay fraction is::

    decay = (C_t + P_t) / EM_open

``decay = 0.83`` means 83% of the opening expected move's premium remains;
the rest has decayed. A trigger fires when::

    decay <= threshold

with the pre-registered hypothesis ``threshold = 0.83``.

Per-expiry semantics: the opening EM and the current straddle must come
from the *same expiry's* chain. For the 0DTE use case that is today's
expiry, and ``EM_open`` is read from the opening chain (first usable
quotes of the session). No ``sqrt(T)`` scaling is involved: this is a
ratio of two quoted straddles, not a time-scaled estimate.

What this is NOT
---------------
This module is a trigger, not an edge. It reports *how much premium has
decayed*; it says nothing about whether selling the remaining premium is
profitable. The edge claim — that entering short-premium positions only
after X% of the opening EM has decayed improves risk-adjusted returns —
lives in the pre-registered hypothesis document
(``trade_strategies/research/0dte-em-decay-ironfly.md``) and must survive
Tier-1 validation like everything else.

The default ``threshold = 0.83`` is the PRE-REGISTERED HYPOTHESIS VALUE
taken from the source video (Dale Perryman's 0DTE iron-fly approach). It
is explicitly NOT a tuned optimum: it was written down before any
backtest, and changing it after seeing results would be overfitting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from .expected_move import ExpectedMove
from .models import ensure_utc

#: Pre-registered hypothesis value for the decay trigger threshold.
#: From the source video; NOT a tuned optimum. See module docstring.
HYPOTHESIS_THRESHOLD = 0.83


def _require_opening_em(value: float) -> float:
    if not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
        raise ValueError(
            f"opening_em must be a positive finite number, got {value!r}"
        )
    return float(value)


def _require_quote(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        raise ValueError(
            f"{name} must be a non-negative finite number, got {value!r}"
        )
    return float(value)


def _require_threshold(value: float) -> float:
    if not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"threshold must be finite, got {value!r}")
    if not 0.0 < value <= 1.0:
        raise ValueError(
            f"threshold must be in (0, 1], got {value!r}"
        )
    return float(value)


def em_decay(opening_em: float, current_call: float, current_put: float) -> float:
    """Current ATM straddle as a fraction of the opening EM.

    ``0.83`` means 83% of the opening expected move's premium remains.
    """
    opening = _require_opening_em(opening_em)
    call = _require_quote(current_call, "current_call")
    put = _require_quote(current_put, "current_put")
    return (call + put) / opening


def em_decay_from_expected_move(
    opening: ExpectedMove, current_call: float, current_put: float
) -> float:
    """Decay fraction using an :class:`ExpectedMove` for the opening EM.

    Takes ``opening.em_points`` as the opening straddle. The current legs
    are raw quotes (mids preferred, same convention as
    :mod:`trade_data_options.expected_move`).
    """
    if not isinstance(opening, ExpectedMove):
        raise ValueError(
            f"opening must be an ExpectedMove, got {type(opening).__name__}"
        )
    return em_decay(opening.em_points, current_call, current_put)


@dataclass(frozen=True)
class DecayTrigger:
    """A single evaluation of the EM-decay entry trigger.

    ``triggered`` is True when ``decay_pct <= threshold``. ``as_of`` is
    normalized to UTC on construction.
    """

    decay_pct: float
    as_of: datetime
    threshold: float = HYPOTHESIS_THRESHOLD
    triggered: bool = False  # derived in __post_init__

    def __post_init__(self) -> None:
        decay = _require_quote(self.decay_pct, "decay_pct")
        object.__setattr__(self, "decay_pct", decay)
        object.__setattr__(self, "as_of", ensure_utc(self.as_of))
        threshold = _require_threshold(self.threshold)
        object.__setattr__(self, "threshold", threshold)
        object.__setattr__(self, "triggered", decay <= threshold)


def decay_trigger(
    opening_em: float,
    current_call: float,
    current_put: float,
    threshold: float = HYPOTHESIS_THRESHOLD,
    *,
    as_of: datetime,
) -> DecayTrigger:
    """Evaluate the EM-decay entry trigger at one point in time.

    ``threshold`` defaults to the pre-registered hypothesis value
    (:data:`HYPOTHESIS_THRESHOLD`); overriding it is allowed for
    sensitivity analysis but the override is not the hypothesis.
    """
    pct = em_decay(opening_em, current_call, current_put)
    return DecayTrigger(decay_pct=pct, as_of=as_of, threshold=threshold)
