"""Deterministic keyword theme classifier (spec §4.3).

An item belongs to a theme when at least ``theme.min_hits`` of the
theme's ``include_terms`` appear in its title + summary and **no**
``exclude_terms`` appear.  Matching is case-insensitive substring
matching — deliberately simple, fully deterministic, and explainable:
the exact terms that fired are returned and stored on the archived
item, so any classification can be audited later.

No ML here.  An LLM-assisted classifier is Phase 3 of the spec and sits
in the challenger seat (advisory, logged); it never silently overrides
this deterministic record.
"""

from __future__ import annotations

from .models import PressItem, ThemeDefinition


def classify_hits(item: PressItem,
                  theme: ThemeDefinition) -> tuple[str, ...] | None:
    """The include terms that fired for ``item`` under ``theme``.

    Returns the fired terms (in the pack's ``include_terms`` order) when
    the item matches the theme, or ``None`` when it does not — too few
    include hits, or any exclude term present (exclusions veto, however
    many includes fired).
    """
    text = f"{item.title}\n{item.summary}".lower()
    for term in theme.exclude_terms:
        if term.lower() in text:
            return None
    hits = tuple(
        term for term in theme.include_terms if term.lower() in text)
    if len(hits) < theme.min_hits:
        return None
    return hits


def classify_item(item: PressItem,
                  theme: ThemeDefinition) -> bool:
    """True when ``item`` belongs to ``theme``."""
    return classify_hits(item, theme) is not None


def classify_items(
    items: list[PressItem],
    theme: ThemeDefinition,
) -> list[tuple[PressItem, tuple[str, ...]]]:
    """Filter ``items`` to theme members, each with its fired terms."""
    out = []
    for item in items:
        hits = classify_hits(item, theme)
        if hits is not None:
            out.append((item, hits))
    return out
