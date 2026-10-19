"""Narrative context adapter — the agents' ``market_context`` surface.

``narrative_input()`` plays the same role for the press listener that
``weather_input`` plays for ``trade_macro.weather``: it returns the
frozen ``press.narrative_state.v1`` payload (spec §5) for one theme and
one date, shaped for direct insertion into the desk's
``market_context``.

Strict as-of agreement (the weather module's discipline): the payload
returned is exactly the rollup stored for the requested date.  A date
with no rollup **raises** — it never silently substitutes a stale read,
because a narrative state carried forward in silence is a look-ahead
bug wearing a trench coat.

This is context for the desk, never a signal (spec §3.7): nothing here
sizes, enters, or exits anything.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .archive import PressArchive
from .themes import get_theme

DEFAULT_THEME = "ai_infrastructure_capex"


def _as_date(value: date | str, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(
            f"{name}: expected date or ISO 'YYYY-MM-DD', got {value!r}"
        ) from None


def narrative_input(as_of, archive: PressArchive | str | Path,
                    theme_id: str = DEFAULT_THEME) -> dict:
    """The ``press.narrative_state.v1`` payload for ``theme_id`` as of a date.

    ``as_of`` is a date or ISO ``YYYY-MM-DD`` string; ``archive`` is a
    ``PressArchive`` (or a path to one).  Raises ``ValueError`` when no
    rollup exists for that exact (theme, date), or when the stored
    payload disagrees with the request — run ``pipeline.rollup`` (or the
    ``rollup`` CLI) for the date first.
    """
    day = _as_date(as_of, "as_of")
    get_theme(theme_id)  # KeyError with a hint for an unknown theme
    arc = archive if isinstance(archive, PressArchive) \
        else PressArchive(archive)
    payload = arc.get_rollup(theme_id, day.isoformat())
    if payload is None:
        raise ValueError(
            f"no narrative rollup for theme {theme_id!r} on "
            f"{day.isoformat()}: run a rollup for that date first "
            "(a stale read is never substituted)")
    if payload.get("theme_id") != theme_id \
            or payload.get("as_of") != day.isoformat():
        raise ValueError(
            f"stored rollup disagrees with the request: stored "
            f"({payload.get('theme_id')!r}, {payload.get('as_of')!r}) vs "
            f"requested ({theme_id!r}, {day.isoformat()!r})")
    return payload
