"""Interoperability bridges.  All sibling imports are lazy.

- :func:`to_dashboard_rows` — flat per-theme rows for the dashboard
  data viewers.
- :func:`to_agent_context` — ``press.narrative_state.v1`` payloads
  keyed by theme, ready to merge into the agents' ``market_context``.
"""

from __future__ import annotations

from .models import NarrativeState


def to_dashboard_rows(states: list[NarrativeState]) -> list[dict]:
    """Flat, JSON-safe rows for dashboard tables (one row per theme/day)."""
    return [s.to_dict() for s in states]


def to_agent_context(states: list[NarrativeState]) -> dict:
    """{theme_id: press.narrative_state.v1 payload} for ``market_context``.

    Later states for the same theme win, so pass them oldest-first.
    """
    return {s.theme_id: s.to_dict() for s in states}


def describe() -> dict:
    """Machine-readable capability summary for the suite registry."""
    return {
        "name": "trade-press",
        "capabilities": ["scan", "rollup", "narrative_input",
                         "to_dashboard_rows", "to_agent_context"],
        "outputs": ["press.observation.v1", "press.narrative_state.v1"],
    }
