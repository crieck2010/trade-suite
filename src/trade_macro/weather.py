"""Trading weather: a composite barometer for bet sizing — context, not signal.

Thesis (the barometer/umbrella analogy): a short-premium harvester does not
need a prediction of *direction*; it needs a read on *conditions*.  A
barometer does not tell you whether it will rain on your picnic — it tells
you whether to bring an umbrella, i.e. how much risk to carry.  This module
is that barometer: it composes the suite's existing, validated regime
inputs — the copper:gold regime label, the buyback-blackout calendar read,
and the forced-selling (vol) read — into one categorical readout plus a
0–100 score, for the bet-sizing layer to consume as *context*.

Usage contract (read this before calling):

- This module is **context for sizing only — NEVER an entry signal.**  A
  "storm" reading does not short anything, does not exit anything, and does
  not change any strategy's weights by itself.  It informs how much risk
  the sizing layer takes, alongside the regime label.  Promoting weather to
  a trading decision requires Charlie's explicit approval after validation.
- The rules below are **documented conventions, not fitted weights.**
  Every point value and every category boundary is stated here so it can
  be audited — and so that changing any of them is a deliberate,
  pre-registered decision, not silent tuning.  If anyone proposes
  statistically fitted weights, that proposal goes through pre-registration
  and Tier-1 validation first; it is NOT implemented here.
- Inputs must all be computed **as-of the same date** — this function
  enforces that (a classic look-ahead bug is feeding it a regime from
  Tuesday with a vol read from Friday).  ``em_state`` is accepted and
  ignored: the slot exists for a future EM term-structure input and is
  documented as unspecified until then.

Documented rules (each traceable to an input):

==========================  ========  ======================================
Condition                   Effect    Points
==========================  ========  ======================================
``forced_selling.elevated`` storm     50 — vol-control deleveraging in
                                      progress dominates the barometer
``regime == CONTRACTION``   storm     20 — no growth-expectations bid
and ``buyback.severity==2``           AND the corporate bid sidelined
any single flag:            caution   20 — deep blackout alone
``buyback.severity == 2``             20 — contraction alone
``regime == CONTRACTION``             10 — shoulder blackout
``buyback.severity == 1``             10 — vol risk present but below the
0 < ``forced_selling.                elevated bar
risk_score`` < 0.5
nothing fired               calm       0
==========================  ========  ======================================

``score`` is the clamped sum of the fired components (0–100).  Category is
decided by rule order, not by score: storm conditions first, then caution
if anything fired, else calm.  The point values are conventional —
auditable, not optimal — and changing them is a pre-registered decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .flow_context import BuybackContext, ForcedSellingContext
from .regime import REGIMES

__all__ = [
    "WeatherReport",
    "trading_weather",
    "WEATHER_RULES",
    "SCORE_COMPONENTS",
]

# Documented, conventional component points — NOT fitted.  See module
# docstring: changing any value below is a pre-registered decision.
SCORE_COMPONENTS = {
    "forced_selling_elevated": 50,
    "contraction": 20,
    "blackout_deep": 20,
    "blackout_shoulder": 10,
    "vol_present": 10,
}

WEATHER_RULES = (
    "storm if forced_selling.elevated "
    "(vol-control deleveraging in progress)",
    "storm if regime == CONTRACTION and buyback.severity == 2 "
    "(corporate bid sidelined into weakness)",
    "caution if any single flag fired "
    "(deep blackout alone, contraction alone, shoulder blackout, "
    "or vol risk present below the elevated bar)",
    "calm otherwise",
)

_VALID_CATEGORIES = ("calm", "caution", "storm")


def _as_date(value: date | str, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(
            f"{name}: expected date or ISO 'YYYY-MM-DD', got {value!r}"
        ) from None


@dataclass(frozen=True)
class WeatherReport:
    """Composite barometer read for ``as_of`` — sizing context, not signal."""

    as_of: str                     # ISO date the read applies to
    category: str                  # "calm" | "caution" | "storm"
    score: int                     # 0..100, documented rule mapping
    reasons: list[str] = field(default_factory=list)  # fired inputs, human-readable
    inputs: dict = field(default_factory=dict)        # traceable input echo

    def __post_init__(self) -> None:
        if self.category not in _VALID_CATEGORIES:
            raise ValueError(
                f"category must be one of {_VALID_CATEGORIES}, "
                f"got {self.category!r}"
            )
        if not isinstance(self.score, int) or not 0 <= self.score <= 100:
            raise ValueError(
                f"score must be an int in 0..100, got {self.score!r}"
            )

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "category": self.category,
            "score": self.score,
            "reasons": list(self.reasons),
            "inputs": dict(self.inputs),
        }


def trading_weather(
    as_of,
    *,
    regime: str,
    buyback: BuybackContext,
    forced_selling: ForcedSellingContext,
    em_state=None,
) -> WeatherReport:
    """Composite trading-weather barometer for ``as_of``.

    Pure function of already-computed, as-of-dated inputs.  ``em_state``
    is accepted and ignored — the slot for a future EM term-structure
    input, unspecified until then.
    """
    as_of_d = _as_date(as_of, "as_of")
    if regime not in REGIMES:
        raise ValueError(
            f"regime must be one of {REGIMES}, got {regime!r}"
        )
    if not isinstance(buyback, BuybackContext):
        raise TypeError(
            f"buyback must be BuybackContext, got {type(buyback).__name__}"
        )
    if not isinstance(forced_selling, ForcedSellingContext):
        raise TypeError(
            "forced_selling must be ForcedSellingContext, "
            f"got {type(forced_selling).__name__}"
        )
    # No-look-ahead discipline: every input must be computed for the same
    # date.  Mixing a Tuesday regime with a Friday vol read is the classic
    # bug this check exists to catch.
    for name, ctx in (("buyback", buyback),
                      ("forced_selling", forced_selling)):
        if _as_date(ctx.as_of, f"{name}.as_of") != as_of_d:
            raise ValueError(
                f"{name}.as_of ({ctx.as_of}) != as_of ({as_of_d.isoformat()}): "
                "all weather inputs must be computed for the same date"
            )

    reasons: list[str] = []
    score = 0

    elevated = forced_selling.elevated
    contraction = regime == "CONTRACTION"
    deep = buyback.severity == 2
    shoulder = buyback.severity == 1
    vol_present = 0.0 < forced_selling.risk_score < 0.5

    if elevated:
        score += SCORE_COMPONENTS["forced_selling_elevated"]
        if forced_selling.realized_vol_21d is not None:
            detail = f"21d vol {forced_selling.realized_vol_21d:.1%}"
        elif forced_selling.vol_ratio is not None:
            detail = f"{forced_selling.vol_ratio:.2f}x baseline vol"
        else:
            detail = "vol elevated"
        reasons.append(
            f"forced selling elevated ({detail})"
            " — vol-control deleveraging in progress"
        )
    if contraction:
        score += SCORE_COMPONENTS["contraction"]
        reasons.append("contraction regime (copper:gold growth-expectations)")
    if deep:
        score += SCORE_COMPONENTS["blackout_deep"]
        reasons.append(
            f"buyback blackout deep ({buyback.quarter}): corporate bid sidelined"
        )
    elif shoulder:
        score += SCORE_COMPONENTS["blackout_shoulder"]
        reasons.append(
            f"buyback blackout shoulder ({buyback.quarter}): corporate bid thinning"
        )
    if vol_present:
        score += SCORE_COMPONENTS["vol_present"]
        reasons.append(
            f"vol risk present (score {forced_selling.risk_score:.2f}) "
            "but below the elevated bar"
        )

    score = max(0, min(100, score))

    if elevated or (contraction and deep):
        category = "storm"
    elif reasons:
        category = "caution"
    else:
        category = "calm"

    return WeatherReport(
        as_of=as_of_d.isoformat(),
        category=category,
        score=score,
        reasons=reasons,
        inputs={
            "regime": regime,
            "buyback_severity": buyback.severity,
            "buyback_quarter": buyback.quarter,
            "forced_selling_elevated": elevated,
            "forced_selling_score": forced_selling.risk_score,
            "em_state": "ignored (slot unspecified)",
        },
    )
