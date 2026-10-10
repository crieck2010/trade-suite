"""Gate strictness profiles."""

from __future__ import annotations

PRESETS = {
    "strict": {
        "description": "Default. No WARNs tolerated, 90-day report freshness, "
                       "two-person rule for LIVE.",
        "allow_warns": False,
        "max_age_days": 90,
        "require_distinct_approver": True,
    },
    "balanced": {
        "description": "WARNs tolerated with documentation, 120-day freshness, "
                       "two-person rule kept.",
        "allow_warns": True,
        "max_age_days": 120,
        "require_distinct_approver": True,
    },
    "lenient": {
        "description": "Research sandbox. WARNs tolerated, 180-day freshness, "
                       "same approver allowed. Never for LIVE capital.",
        "allow_warns": True,
        "max_age_days": 180,
        "require_distinct_approver": False,
    },
}


def get_preset(name: str) -> dict:
    try:
        return dict(PRESETS[name])
    except KeyError:
        raise ValueError(f"Unknown preset {name!r}; choose from {sorted(PRESETS)}.")


def list_presets() -> dict:
    return {name: dict(cfg) for name, cfg in PRESETS.items()}
