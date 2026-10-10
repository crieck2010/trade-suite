"""Conservative / balanced / aggressive incubation postures."""

from __future__ import annotations

from .program import ProgramConfig


PRESETS: dict[str, dict] = {
    "conservative": {
        "description": "Slow to graduate, quick to pause. For unproven strategies.",
        "config": ProgramConfig(sharpe_tolerance=0.5, dd_multiple=1.15,
                                min_trades=25, kill_dd_multiple=1.35,
                                regime_min_conviction=40.0, warmup_size=0.25),
    },
    "balanced": {
        "description": "The defaults. For a strategy that passed validation cleanly.",
        "config": ProgramConfig(),
    },
    "aggressive": {
        "description": "Faster graduation, wider bands. For strategies with long paper history.",
        "config": ProgramConfig(sharpe_tolerance=1.0, dd_multiple=1.4,
                                min_trades=15, kill_dd_multiple=1.75,
                                regime_min_conviction=20.0, warmup_size=0.75),
    },
}


def get_preset(name: str) -> ProgramConfig:
    try:
        return PRESETS[name]["config"]
    except KeyError:
        raise ValueError(f"unknown preset {name!r}; choose from {sorted(PRESETS)}")
