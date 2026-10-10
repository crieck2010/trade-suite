"""Strategy catalog for the dashboard (via trade-strategies, lazy)."""


def list_strategies() -> list[dict]:
    try:
        from trade_strategies.registry import describe_strategies
    except ImportError as exc:
        raise RuntimeError(
            "the strategy catalog needs the trade-strategies package installed"
        ) from exc
    return describe_strategies()


def describe_strategy(name: str) -> dict:
    for desc in list_strategies():
        if desc["name"] == name:
            return desc
    raise KeyError(f"unknown strategy {name!r}")
