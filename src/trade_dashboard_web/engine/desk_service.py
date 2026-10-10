"""Run the agent desk and return its report as plain data (lazy)."""


def run_desk_job(symbols: list[str], bars_by_symbol: dict[str, list], equity: float = 100_000.0) -> dict:
    """Run ``trade_agents.default_desk`` over the given bars.

    ``bars_by_symbol`` maps symbol -> bar list (dicts).  Symbols are
    upper-cased; scouts whose universe has no overlap with ``symbols``
    simply produce empty briefs.
    """
    try:
        from trade_agents import DictBarsProvider, default_desk
    except ImportError as exc:
        raise RuntimeError(
            "the desk needs the trade-agents package (and its siblings) installed"
        ) from exc

    symbols = [s.strip().upper() for s in symbols if s and s.strip()]
    if not symbols:
        raise ValueError("at least one symbol is required")
    provider = DictBarsProvider(
        {s: bars_by_symbol.get(s, []) for s in symbols}
    )
    desk = default_desk()
    for scout in desk.researchers:
        universe = getattr(scout, "universe", None)
        if universe:
            overlap = [s for s in universe if s in provider.symbols()]
            scout.universe = tuple(overlap) if overlap else tuple(symbols)
    report = desk.run(provider, equity=equity)
    return report.to_dict()
