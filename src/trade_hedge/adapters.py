"""Lazy sibling adapters. All imports of sibling packages happen INSIDE
functions and fail soft: with no siblings installed, every adapter raises a
clear error naming the pip package to install (or falls back to an internal
implementation, where documented). Importing this module never requires a
sibling.
"""

from __future__ import annotations


def _need(package: str, pip_name: str):
    try:
        return __import__(package)
    except ImportError as exc:
        raise RuntimeError(
            f"trade_hedge adapter needs the {pip_name!r} package "
            f"(pip install {pip_name}); original error: {exc}"
        ) from exc


def positions_from_paper(ledger_path: str | None = None,
                         db_path: str | None = None) -> list[dict]:
    """Current positions from trade-paper's ledger/audit store.

    Returns [{"symbol": str, "qty": float}]. Requires trade-paper installed.
    """
    trade_paper = _need("trade_paper", "trade-paper")
    get_positions = getattr(trade_paper, "get_positions", None)
    if get_positions is None:
        raise RuntimeError(
            "installed trade_paper has no get_positions(); "
            "pass positions explicitly instead")
    return [{"symbol": str(p["symbol"]), "qty": float(p["qty"])}
            for p in get_positions(ledger_path=ledger_path, db_path=db_path)]


def prices_from_data(symbols: list[str], provider: str = "equities") -> dict:
    """Latest prices for symbols via a trade-data-* engine.

    ``provider`` selects the engine ("equities", "crypto", "futures",
    "options"). Requires the corresponding trade-data-* package installed.
    """
    mapping = {
        "equities": ("trade_data_equities", "trade-data-equities"),
        "crypto": ("trade_data_crypto", "trade-data-crypto"),
        "futures": ("trade_data_futures", "trade-data-futures"),
        "options": ("trade_data_options", "trade-data-options"),
    }
    if provider not in mapping:
        raise ValueError(f"unknown provider {provider!r}; expected one of "
                         f"{sorted(mapping)}")
    package, pip_name = mapping[provider]
    mod = _need(package, pip_name)
    latest = getattr(mod, "latest_prices", None)
    if latest is None:
        raise RuntimeError(
            f"installed {package} has no latest_prices(); "
            "pass a prices dict explicitly instead")
    return {str(s): float(p) for s, p in latest(symbols).items()}


def vol_from_volforecast(returns: list[float]) -> float | None:
    """Annualized realized vol via trade-volforecast when installed;
    otherwise the internal close-to-close estimator. Never raises on short
    input — returns None."""
    from .hedges import trailing_realized_vol
    if len(returns) < 2:
        return None
    try:
        tv = __import__("trade_volforecast")
    except ImportError:
        return trailing_realized_vol(list(returns))
    realized = getattr(tv, "realized_vol", None)
    if realized is None:
        return trailing_realized_vol(list(returns))
    try:
        return float(realized(list(returns)))
    except Exception:
        return trailing_realized_vol(list(returns))


def betas_from_factors(symbols: list[str], lookback_days: int = 252) -> dict:
    """Market betas via trade-factors when installed; otherwise {symbol: 1.0}
    with the fallback recorded. Never raises."""
    try:
        tf = __import__("trade_factors")
    except ImportError:
        return {s: 1.0 for s in symbols}
    estimate = getattr(tf, "estimate_betas", None)
    if estimate is None:
        return {s: 1.0 for s in symbols}
    try:
        out = estimate(symbols, lookback_days=lookback_days)
        return {str(s): float(out.get(s, 1.0)) for s in symbols}
    except Exception:
        return {s: 1.0 for s in symbols}


def proposals_to_paper_payloads(proposals: list[dict],
                               run_id: str | None = None) -> list[dict]:
    """Shape hedge proposals as trade-paper approval-queue payloads (plain
    dicts). trade-paper never imports trade-hedge; the queue validates these
    on receipt, where the user is the final gate."""
    payloads = []
    for p in proposals:
        payloads.append({
            "kind": "hedge_proposal",
            "action": p.get("action"),
            "instrument": p.get("instrument"),
            "qty": p.get("qty"),
            "reason": p.get("reason"),
            "expected_delta_impact": p.get("expected_delta_impact"),
            "rule_id": p.get("rule_id"),
            "details": p.get("details", {}),
            "source": "trade-hedge",
            "run_id": run_id,
            "requires_user_approval": True,
        })
    return payloads
