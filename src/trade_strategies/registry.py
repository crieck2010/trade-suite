"""Strategy registry: the agents' menu.

:func:`describe_strategies` returns agent-ready metadata for every
strategy -- name, family, description, default parameters, warmup --
so research agents can enumerate, compare, and propose candidates
without importing each module by hand.
"""

from __future__ import annotations

from .base import Strategy
from .mean_reversion import (
    BollingerReversion,
    RSI2MeanReversion,
    StochasticReversion,
    ZScoreReversion,
)
from .meta import EnsembleVote, RegimeFilter, TrailingStop
from .momentum import (
    BollingerSqueezeBreakout,
    KeltnerBreakout,
    OBVTrend,
    TimeSeriesMomentum,
    VWAPDeviation,
)
from .multi_asset import CrossSectionalMomentum, PairsTrading
from .regcond_1 import RegCond1
from .trend import DonchianBreakout, EMACrossover, MACDTrend, SMACrossover, Supertrend

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls
    for cls in (
        SMACrossover,
        EMACrossover,
        MACDTrend,
        DonchianBreakout,
        Supertrend,
        BollingerReversion,
        RSI2MeanReversion,
        ZScoreReversion,
        StochasticReversion,
        TimeSeriesMomentum,
        KeltnerBreakout,
        BollingerSqueezeBreakout,
        OBVTrend,
        VWAPDeviation,
        PairsTrading,
        CrossSectionalMomentum,
        RegCond1,
        TrailingStop,
        RegimeFilter,
        EnsembleVote,
    )
}


def list_strategies(family: str | None = None) -> list[str]:
    """Strategy names, optionally filtered by family."""
    names = [n for n, c in STRATEGY_REGISTRY.items()
             if family is None or c.family == family]
    return sorted(names)


def list_families() -> list[str]:
    return sorted({c.family for c in STRATEGY_REGISTRY.values()})


def get_strategy(name: str) -> type[Strategy]:
    try:
        return STRATEGY_REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"unknown strategy {name!r}; choose from {list_strategies()}") from None


def describe_strategies(family: str | None = None) -> list[dict]:
    """Agent-facing metadata for every (or one family's) strategy.

    Meta strategies need members to instantiate; they are described from
    class attributes instead.
    """
    demo_symbols = {"pairs_trading": ["A", "B"],
                    "regcond_1": ["SPY", "CPER", "TLT", "GLD"]}
    out: list[dict] = []
    for name in list_strategies(family):
        cls = STRATEGY_REGISTRY[name]
        if cls.family == "meta":
            out.append({
                "name": cls.name,
                "family": cls.family,
                "description": cls.description,
                "parameters": dict(cls.DEFAULT_PARAMS),
                "warmup_bars": "depends on members",
                "symbols": [],
            })
        else:
            try:
                out.append(cls(demo_symbols.get(name, ["DEMO"])).describe())
            except Exception:  # pragma: no cover - defensive
                out.append({"name": cls.name, "family": cls.family,
                            "description": cls.description,
                            "parameters": dict(cls.DEFAULT_PARAMS),
                            "warmup_bars": "depends on parameters",
                            "symbols": []})
    return out
