"""Lazy adapters to sibling repos in the trade-suite.

Every sibling import happens inside the function that needs it, so
trade-breadth imports and tests clean with nothing else installed.
Each adapter degrades to a clear, actionable error (never a bare
ImportError at module import time).
"""

from __future__ import annotations


def _sibling(name: str, hint: str):
    try:
        return __import__(name)
    except ImportError as exc:
        raise ImportError(
            f"trade-breadth adapter needs {name}: {hint} "
            f"(pip install git+https://github.com/crieck2010/{name}.git)"
        ) from exc


def bars_from_trade_data_equities(
    symbols: list[str],
    start: str | None = None,
    end: str | None = None,
    **kwargs,
) -> dict[str, list[dict]]:
    """Fetch constituent bars via trade-data-equities (lazy).

    Expected sibling shape: ``trade_data_equities.get_bars(symbols, start,
    end)`` returning ``{symbol: [bars]}`` with the standard bar dicts.
    Pass ``bars_loader=callable`` to override the lookup entirely
    (useful for tests and for pinned sibling versions).
    """
    loader = kwargs.pop("bars_loader", None)
    if loader is None:
        tde = _sibling(
            "trade_data_equities",
            "for constituent price history",
        )
        loader = tde.get_bars
    return loader(symbols, start=start, end=end, **kwargs)


def market_context_provider(
    universe: dict,
    weights: dict[str, float] | None = None,
    preset: str = "standard",
):
    """Return a zero-arg callable producing the snapshot dict.

    trade-agents registers the returned callable as a ``market_context``
    provider and merges its output into every idea and debate brief.
    The universe is captured by closure — call the provider fresh each
    time the desk needs current context.
    """
    from .snapshot import snapshot

    def provider() -> dict:
        return snapshot(universe, weights=weights, preset=preset)

    provider.__name__ = "trade_breadth_market_context"
    return provider


def risk_regime_input(snap: dict) -> dict:
    """Regime-conditional input for trade-risk limits (plain data).

    Suggested mapping (trade-risk owns the policy): NARROWING or
    fragility > 0.6 -> tighten gross-exposure and per-name limits;
    BROADENING -> standard limits.
    """
    frag = snap.get("fragility")
    return {
        "regime": snap.get("regime"),
        "regime_score": snap.get("regime_score"),
        "fragility": frag,
        "tighten_limits": bool(snap.get("regime") == "NARROWING"
                               or (frag is not None and frag > 0.6)),
        "asof": snap.get("date"),
    }


def hedge_tilt_input(snap: dict) -> dict:
    """Defensive-tilt input for trade-hedge (plain data).

    trade-hedge combines this with its own vol-regime read; breadth
    fragility is an independent vote for defense.
    """
    frag = snap.get("fragility")
    return {
        "fragility": frag,
        "defensive_tilt": bool(frag is not None and frag > 0.6),
        "regime": snap.get("regime"),
        "asof": snap.get("date"),
    }
