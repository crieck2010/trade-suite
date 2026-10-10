"""Suite adapters — all sibling imports are lazy.

This module imports cleanly with nothing else installed. Sibling packages are
imported inside functions, and a helpful error is raised when one is missing.
"""

from __future__ import annotations


def _import_sibling(name: str, pip_name: str):
    try:
        return __import__(name)
    except ImportError as exc:
        raise RuntimeError(
            f"trade-overfit adapter needs the sibling package {pip_name!r} "
            f"(import {name!r} failed). Install it or pass plain data directly."
        ) from exc


def returns_from_backtest(result) -> list[float]:
    """Extract a returns series from a trade-backtest result.

    Accepts (in order of preference):
    - a plain list of floats (passed through untouched),
    - a dict with a ``"returns"`` list,
    - a dict with an ``"equity_curve"`` list (converted to simple returns),
    - a trade-backtest result object with ``returns`` or ``equity_curve``
      attributes (the sibling is imported lazily).
    """
    if isinstance(result, (list, tuple)) and all(isinstance(x, (int, float)) for x in result):
        return [float(x) for x in result]
    returns = None
    if isinstance(result, dict):
        returns = result.get("returns")
        curve = result.get("equity_curve")
    else:
        _import_sibling("trade_backtest", "trade-backtest")
        returns = getattr(result, "returns", None)
        curve = getattr(result, "equity_curve", None)
    if returns is not None:
        return [float(x) for x in returns]
    if curve is not None:
        curve = [float(x) for x in curve]
        return [curve[i] / curve[i - 1] - 1.0 for i in range(1, len(curve))]
    raise ValueError("could not find 'returns' or 'equity_curve' in backtest result")


def gate_research_idea(idea: dict, **validate_kwargs) -> dict:
    """Run a trade-agents research idea through the overfitting desk.

    ``idea`` is a plain dict with at least ``"returns"`` (list of floats);
    ``"trial_sharpes"`` may carry the in-sample Sharpes of every strategy the
    desk tried, and ``"id"`` is echoed back. trade-agents itself is optional:
    if installed it is imported (lazy availability probe) so richer idea
    objects keep working; the plain-data path always works.
    """
    from .gates import validate
    try:
        _import_sibling("trade_agents", "trade-agents")
    except RuntimeError:
        pass  # plain-data path needs no sibling
    verdict = validate(idea["returns"], trial_sharpes=idea.get("trial_sharpes"),
                       **validate_kwargs)
    verdict["idea_id"] = idea.get("id")
    return verdict


def promotion_payload(verdict: dict) -> dict | None:
    """Shape a PASS verdict into a trade-paper promotion payload.

    Returns None for FAIL verdicts — failed strategies are never promoted.
    The payload is plain data; trade-paper consumes it without importing this
    package.
    """
    if verdict.get("verdict") != "PASS":
        return None
    return {
        "source": "trade-overfit",
        "verdict": "PASS",
        "dsr": verdict["evidence"]["dsr"],
        "median_oos_sharpe": verdict["evidence"]["median_oos_sharpe"],
        "max_drawdown": verdict["evidence"]["max_drawdown"],
        "n_gates_passed": verdict["n_gates_passed"],
        "n_gates": verdict["n_gates"],
    }
