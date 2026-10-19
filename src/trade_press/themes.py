"""Theme registry.  Theme packs are data, not code (spec §6).

A pack carries the RSS search strings that surface a narrative, the
keyword rules the deterministic classifier matches on, and the tickers
the desk already watches for cross-reference.  Adding a theme is a new
entry here plus tests — no engine change.  Bump a pack's ``version``
whenever its queries or terms change: archived reads must stay
attributable to the pack that produced them.
"""

from __future__ import annotations

from .models import ThemeDefinition

AI_INFRASTRUCTURE_CAPEX = ThemeDefinition(
    theme_id="ai_infrastructure_capex",
    title="AI infrastructure spending",
    queries=(
        '"AI data center" capex',
        "hyperscaler capital expenditure",
        "AI infrastructure spending",
        '"data center" buildout AI',
    ),
    include_terms=(
        "data center",
        "capex",
        "capital expenditure",
        "hyperscaler",
        "AI infrastructure",
        "GPU cluster",
        "power capacity",
        "buildout",
    ),
    exclude_terms=(
        "earnings calendar",
        "stock price target",
        "lawsuit",
        "obituary",
    ),
    min_hits=2,
    related_symbols=("NVDA", "AVGO", "MSFT", "GOOGL", "AMZN", "META", "ORCL"),
    version="1.0.0",
)

THEME_PACKS: dict[str, ThemeDefinition] = {
    AI_INFRASTRUCTURE_CAPEX.theme_id: AI_INFRASTRUCTURE_CAPEX,
}


def get_theme(theme_id: str) -> ThemeDefinition:
    """Look up a theme pack; ``KeyError`` with a hint otherwise."""
    try:
        return THEME_PACKS[theme_id]
    except KeyError:
        raise KeyError(
            f"unknown press theme {theme_id!r}; "
            f"available: {', '.join(sorted(THEME_PACKS))}"
        ) from None
