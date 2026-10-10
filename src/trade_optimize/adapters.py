"""Interop adapters: plain-data bridges to sibling suite modules.

Sibling imports are lazy (inside functions) so trade-optimize stays
importable and testable on its own.  Everything crossing a boundary is
JSON-safe plain data.
"""

from __future__ import annotations

from . import analytics
from .estimates import mean_returns, shrink_covariance
from .optimize import optimize


# ------------------------------------------------------------------ inputs

def dicts_to_matrix(rows: list[dict[str, float]]) -> tuple[list[str], list[list[float]]]:
    """[{symbol: return}] → (symbols, T×N matrix).  Symbols sorted for determinism."""
    if not rows:
        raise ValueError("no rows")
    symbols = sorted({k for r in rows for k in r})
    matrix = [[r.get(s, 0.0) for s in symbols] for r in rows]
    return symbols, matrix


def returns_from_dict_bars(bars: list, symbols: list[str],
                           price_key: str = "close") -> tuple[list[str], list[list[float]]]:
    """Simple returns from duck-typed bars (dicts or objects with .close).

    Accepts the dict-bar shapes trade-data-*/trade-backtest produce without
    importing them.  Bars must be oldest-first per symbol; pass one flat
    list containing every symbol's bars.
    """
    def price(b):
        return b[price_key] if isinstance(b, dict) else getattr(b, price_key)

    def sym(b):
        return b["symbol"] if isinstance(b, dict) else getattr(b, "symbol")

    by_sym: dict[str, list[float]] = {}
    for b in bars:
        by_sym.setdefault(sym(b), []).append(float(price(b)))
    rows: list[dict[str, float]] = []
    for s in symbols:
        closes = by_sym.get(s, [])
        rets = [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes))]
        for i, r in enumerate(rets):
            while len(rows) <= i:
                rows.append({})
            rows[i][s] = r
    return dicts_to_matrix(rows)


# --------------------------------------------------------------- trade-agents

def to_agent_allocation(symbols: list[str], returns: list[list[float]],
                        method: str = "max_sharpe", risk_free: float = 0.0,
                        max_weight: float = 1.0,
                        shrink_delta: float = 0.2) -> dict:
    """Allocator for the trade-agents portfolio manager.

    A smarter sibling to inverse-vol weighting: estimate (shrinkage)
    covariance, optimize, and return weights plus the stats the PM needs
    to rank and size the allocation.
    """
    mu = mean_returns(returns)
    sigma = shrink_covariance(returns, delta=shrink_delta)
    w = optimize(sigma, mu, method=method, risk_free=risk_free,
                 max_weight=max_weight)
    weights = dict(zip(symbols, w))
    return {
        "source": "trade-optimize",
        "method": method,
        "symbols": symbols,
        "weights": weights,
        "stats": analytics.portfolio_stats(w, mu, sigma, risk_free),
        "risk_contributions": [
            {"symbol": s, "risk_share": rc["risk_share"]}
            for s, rc in zip(symbols, analytics.risk_contributions(w, sigma))
        ],
    }


# ------------------------------------------------------------- trade-backtest

def to_backtest_weights(symbols: list[str], returns: list[list[float]],
                        method: str = "max_sharpe", **kw) -> dict:
    """Weight schedule for trade-backtest: one static allocation block.

    Returns {"weights": {symbol: w}, "stats": {...}, "method": ...} — the
    caller stamps it onto rebalance dates in the backtest's own schedule
    format.
    """
    alloc = to_agent_allocation(symbols, returns, method=method, **kw)
    return {"weights": alloc["weights"], "stats": alloc["stats"],
            "method": alloc["method"], "source": "trade-optimize"}


# ---------------------------------------------------------------- trade-paper

def to_paper_orders(current_qty: dict[str, float],
                    target_weights: dict[str, float],
                    prices: dict[str, float], capital: float) -> list[dict]:
    """Order intents for trade-paper's approval queue (lazy import)."""
    from .rebalance import trades_to_target
    return trades_to_target(current_qty, target_weights, prices, capital)


# ----------------------------------------------------------------- trade-risk

def portfolio_vol_for_risk(weights: list[float],
                           sigma: list[list[float]],
                           periods_per_year: int = 252) -> dict:
    """Annualized portfolio volatility for trade-risk limit checks."""
    import math
    from .linalg import dot, mat_vec
    vol = math.sqrt(max(dot(weights, mat_vec(sigma, weights)), 0.0))
    return {"volatility_ann": vol * math.sqrt(periods_per_year),
            "variance_per_period": vol * vol,
            "source": "trade-optimize"}
