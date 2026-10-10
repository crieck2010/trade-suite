"""Risk evaluation for the dashboard (via trade-risk, lazy)."""


def describe_limits() -> list[dict]:
    try:
        from trade_risk.registry import describe_limits
    except ImportError as exc:
        raise RuntimeError(
            "risk tools need the trade-risk package installed"
        ) from exc
    return describe_limits()


def evaluate_orders_job(
    orders: list[dict],
    limits: list[list] | None = None,
    equity: float = 100_000.0,
) -> dict:
    """Evaluate ``orders`` against a ``[[name, params], ...]`` limit stack.

    Uses the desk's cumulative-fill review so later orders see earlier fills.
    """
    try:
        from trade_agents.risk_agent import RiskManagerAgent
    except ImportError as exc:
        raise RuntimeError(
            "risk evaluation needs the trade-agents and trade-risk "
            "packages installed"
        ) from exc

    limits_cfg = (
        [(name, params or {}) for name, params in limits]
        if limits
        else None
    )
    agent = RiskManagerAgent(limits=limits_cfg)
    approved, vetoes = agent.review(orders, equity=equity)
    return {
        "approved": [{k: v for k, v in o.items() if k != "idea"} for o in approved],
        "vetoed": [v.to_dict() for v in vetoes],
    }
