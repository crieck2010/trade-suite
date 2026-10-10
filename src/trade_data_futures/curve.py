"""Term-structure (futures curve) analytics.

Given settlement prices for successive expiries, the curve shows whether
the market is in **contango** (deferred > nearby, positive roll yield for
longs rolling) or **backwardation** (nearby > deferred). Pure functions
over plain data -- provider-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite


@dataclass(frozen=True, slots=True)
class CurvePoint:
    contract_code: str
    expiry: date
    settle: float


@dataclass(frozen=True, slots=True)
class CurveSegment:
    near: CurvePoint
    far: CurvePoint
    days_between: int
    roll_yield_annualized: float  # > 0 in contango

    @property
    def contango(self) -> bool:
        return self.roll_yield_annualized > 0


def build_curve(points: list[CurvePoint]) -> list[CurveSegment]:
    """Sort points by expiry and link consecutive contracts.

    Annualized roll yield between near and far:
    ``(F_far / F_near - 1) * (365 / days)``.
    """
    ordered = sorted(points, key=lambda p: p.expiry)
    segments: list[CurveSegment] = []
    for near, far in zip(ordered, ordered[1:]):
        days = (far.expiry - near.expiry).days
        if days <= 0 or not all(isfinite(p.settle) and p.settle > 0 for p in (near, far)):
            continue
        ry = (far.settle / near.settle - 1.0) * (365.0 / days)
        segments.append(CurveSegment(near=near, far=far, days_between=days, roll_yield_annualized=ry))
    return segments


def curve_state(segments: list[CurveSegment]) -> str:
    """``"contango"``, ``"backwardation"``, or ``"mixed"``/``"flat"``."""
    if not segments:
        return "unknown"
    signs = {s.contango for s in segments}
    if signs == {True}:
        return "contango"
    if signs == {False}:
        return "backwardation"
    if all(abs(s.roll_yield_annualized) < 1e-9 for s in segments):
        return "flat"
    return "mixed"
