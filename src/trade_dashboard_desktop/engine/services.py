"""Local stdlib-only service implementations.

These mirror :mod:`trade_dashboard_web.engine` one-for-one (same function
names and signatures) so the desktop behaves identically whether or not the
web dashboard package is installed.  When ``trade_dashboard_web`` *is*
installed, :mod:`trade_dashboard_desktop.engine` binds these names to the
web engine instead, keeping a single source of truth in a meta-install.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

def bar_to_dict(bar) -> dict:
    """Normalize a dict-like or engine ``Bar`` to a plain dict."""
    if isinstance(bar, dict):
        ts = bar.get("timestamp")
        return {
            "symbol": bar.get("symbol", ""),
            "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "open": float(bar.get("open", 0.0)),
            "high": float(bar.get("high", 0.0)),
            "low": float(bar.get("low", 0.0)),
            "close": float(bar.get("close", 0.0)),
            "volume": float(bar.get("volume", 0.0)),
        }
    ts = getattr(bar, "timestamp", None)
    return {
        "symbol": getattr(bar, "symbol", "") or "",
        "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "volume": float(getattr(bar, "volume", 0.0) or 0.0),
    }


def synth_bars(symbol: str, n: int = 250, start: float = 100.0, seed: int = 7) -> list[dict]:
    """Deterministic demo bars with three regimes (up / chop / down)."""
    rng = random.Random(seed + abs(hash(symbol)) % 997)
    bars, price = [], start
    t = datetime(2024, 1, 2, tzinfo=timezone.utc)
    for i in range(n):
        drift = 0.003 if i < n * 0.4 else (-0.001 if i < n * 0.7 else -0.003)
        o = price
        c = o * (1 + drift + rng.uniform(-0.02, 0.02))
        bars.append(
            {
                "symbol": symbol,
                "timestamp": t.isoformat(),
                "open": o,
                "high": max(o, c) * 1.005,
                "low": min(o, c) * 0.995,
                "close": c,
                "volume": 2_000_000.0,
            }
        )
        price, t = c, t + timedelta(days=1)
    return bars


class DataService:
    """Fetch bars from the configured sources (``demo`` always works)."""

    SOURCES = ("demo", "equities")

    def sources(self) -> list[dict]:
        out = [{"id": "demo", "label": "Demo (synthetic, offline)", "available": True}]
        try:
            import trade_data_equities  # noqa: F401

            available, note = True, "Delayed data via trade-data-equities (yfinance)"
        except ImportError:
            available, note = False, "Install trade-data-equities for real data"
        out.append(
            {"id": "equities", "label": "Equities (delayed)",
             "available": available, "note": note}
        )
        return out

    def get_bars(self, symbol: str, source: str = "demo", days: int = 365) -> list[dict]:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        if source == "demo":
            return synth_bars(symbol, n=max(60, min(days, 750)))
        if source == "equities":
            return self._equities_bars(symbol, days)
        raise ValueError(f"unknown source {source!r}; choose from demo, equities")

    def _equities_bars(self, symbol: str, days: int) -> list[dict]:
        try:
            from trade_data_equities import EquitiesDataClient, Timeframe
            from trade_data_equities.providers.yfinance import YFinanceProvider
        except ImportError as exc:
            raise RuntimeError(
                "the equities source needs the trade-data-equities package "
                "(and yfinance) installed"
            ) from exc
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=max(30, days))
        client = EquitiesDataClient(YFinanceProvider())
        bars = client.get_bars(symbol, Timeframe.DAILY, start, end, use_cache=True)
        out = [bar_to_dict(b) for b in bars]
        for b in out:
            b["symbol"] = symbol
        if not out:
            raise RuntimeError(f"no bars returned for {symbol}")
        return out


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Backtesting
# ---------------------------------------------------------------------------

def run_backtest_job(
    strategy_name: str,
    symbols: list[str],
    params: dict | None,
    bars: list,
    initial_cash: float = 100_000.0,
) -> dict:
    """Backtest ``strategy_name`` over ``bars``; return plain-data results."""
    try:
        from trade_strategies import get_strategy
        from trade_strategies.adapters import run_backtest
    except ImportError as exc:
        raise RuntimeError(
            "backtests need the trade-strategies and trade-backtest packages installed"
        ) from exc

    if not symbols:
        raise ValueError("at least one symbol is required")
    strategy = get_strategy(strategy_name)(list(symbols), **(params or {}))
    result = run_backtest(strategy, bars, initial_cash=initial_cash)

    curve = [
        {"timestamp": _iso(p.timestamp), "equity": p.equity, "cash": p.cash}
        for p in result.equity_curve
    ]
    trades = [
        {
            "symbol": t.symbol,
            "entry_time": _iso(t.entry_time),
            "exit_time": _iso(t.exit_time),
            "quantity": t.quantity,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "pnl": t.pnl,
            "return_pct": t.return_pct,
        }
        for t in result.trades
    ]
    return {
        "strategy": strategy_name,
        "symbols": list(symbols),
        "params": params or {},
        "initial_cash": initial_cash,
        "final_equity": result.final_equity,
        "metrics": {k: float(v) for k, v in result.metrics.items()},
        "equity_curve": curve,
        "trades": trades,
    }


def _iso(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


# ---------------------------------------------------------------------------
# Agent desk
# ---------------------------------------------------------------------------

def run_desk_job(
    symbols: list[str], bars_by_symbol: dict[str, list], equity: float = 100_000.0
) -> dict:
    """Run ``trade_agents.default_desk`` over the given bars; plain-data report."""
    try:
        from trade_agents import DictBarsProvider, default_desk
    except ImportError as exc:
        raise RuntimeError(
            "the desk needs the trade-agents package (and its siblings) installed"
        ) from exc

    symbols = [s.strip().upper() for s in symbols if s and s.strip()]
    if not symbols:
        raise ValueError("at least one symbol is required")
    provider = DictBarsProvider({s: bars_by_symbol.get(s, []) for s in symbols})
    desk = default_desk()
    for scout in desk.researchers:
        universe = getattr(scout, "universe", None)
        if universe:
            overlap = [s for s in universe if s in provider.symbols()]
            scout.universe = tuple(overlap) if overlap else tuple(symbols)
    report = desk.run(provider, equity=equity)
    return report.to_dict()


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

def describe_limits() -> list[dict]:
    try:
        from trade_risk.registry import describe_limits
    except ImportError as exc:
        raise RuntimeError("risk tools need the trade-risk package installed") from exc
    return describe_limits()


def evaluate_orders_job(
    orders: list[dict],
    limits: list[list] | None = None,
    equity: float = 100_000.0,
) -> dict:
    """Evaluate ``orders`` against a ``[[name, params], ...]`` limit stack."""
    try:
        from trade_agents.risk_agent import RiskManagerAgent
    except ImportError as exc:
        raise RuntimeError(
            "risk evaluation needs the trade-agents and trade-risk packages installed"
        ) from exc

    limits_cfg = [(name, params or {}) for name, params in limits] if limits else None
    agent = RiskManagerAgent(limits=limits_cfg)
    approved, vetoes = agent.review(orders, equity=equity)
    return {
        "approved": [{k: v for k, v in o.items() if k != "idea"} for o in approved],
        "vetoed": [v.to_dict() for v in vetoes],
    }


# ---------------------------------------------------------------------------
# Paper trading (trade-paper, lazy)
# ---------------------------------------------------------------------------

def paper_available() -> tuple[bool, str]:
    try:
        import trade_paper  # noqa: F401
        return True, ""
    except ImportError:
        return False, ("trade-paper is not installed; "
                       "pip install git+https://github.com/crieck2010/trade-paper.git")


def _paper_require():
    ok, hint = paper_available()
    if not ok:
        raise RuntimeError(hint)
    from trade_paper.brokers import make_broker
    from trade_paper.config import PaperConfig
    from trade_paper.ledger import Ledger
    return make_broker, PaperConfig, Ledger


def _paper_load(config_path: str):
    make_broker, PaperConfig, Ledger = _paper_require()
    cfg = PaperConfig.load(config_path or "paper-config.json")
    return cfg, make_broker(cfg), Ledger(cfg.db_path)


def paper_status(config_path: str = "") -> dict:
    cfg, broker, ledger = _paper_load(config_path)
    try:
        acct = broker.get_account()
        positions = broker.get_positions()
        return {
            "available": True, "broker": broker.name,
            "paper_only": True,
            "equity": round(acct.equity, 2), "cash": round(acct.cash, 2),
            "buying_power": round(acct.buying_power, 2),
            "market_open": broker.is_market_open(),
            "positions": [{"symbol": p.symbol, "qty": p.quantity,
                           "avg_entry": round(p.avg_entry_price, 4),
                           "market": round(p.market_price, 4),
                           "unrealized": round(p.unrealized_pnl, 2),
                           "asset_class": p.asset_class.value}
                          for p in positions],
            "pending_approvals": len(ledger.list_approvals(status="pending")),
            "active_strategies": len(ledger.active_strategies()),
            "recent_orders": [
                {"id": o["client_order_id"], "symbol": o["symbol"],
                 "side": o["side"], "qty": o["quantity"],
                 "strategy": o["strategy"], "state": o["state"]}
                for o in ledger.list_orders(limit=25)
            ],
        }
    finally:
        ledger.close()


def paper_approvals(config_path: str = "", status: str = "pending") -> dict:
    _, _, ledger = _paper_load(config_path)
    try:
        rows = ledger.list_approvals(status=status or None)
        return {"available": True, "approvals": [
            {"id": r["id"], "strategy": r["strategy"], "symbols": r["symbols"],
             "status": r["status"], "decided_by": r["decided_by"],
             "reason": r["reason"], "created_at": r["created_at"],
             "score": (r["metrics"].get("score")),
             "metrics": r["metrics"].get("metrics", {})}
            for r in rows]}
    finally:
        ledger.close()


def paper_approve(config_path: str, approval_id: int, reason: str = "") -> dict:
    _, _, ledger = _paper_load(config_path)
    try:
        ledger.decide_approval(approval_id, True, decided_by="user", reason=reason)
        return {"available": True, "approved": approval_id}
    finally:
        ledger.close()


def paper_fidelity(config_path: str = "") -> dict:
    _paper_require()
    from trade_paper import fidelity as fmod
    from trade_paper.config import PaperConfig
    from trade_paper.ledger import Ledger
    cfg = PaperConfig.load(config_path or "paper-config.json")
    ledger = Ledger(cfg.db_path)
    try:
        out = fmod.report(ledger, cfg.assumed_slippage_bps)
        out["available"] = True
        return out
    finally:
        ledger.close()


# ---------------------------------------------------------------------------
# Research lab (mirrors trade_dashboard_web.engine.research_service one-for-one)
# ---------------------------------------------------------------------------

def _research_require(dist: str, package: str):
    try:
        return __import__(package, fromlist=["*"])
    except ImportError as exc:
        raise RuntimeError(
            f"{dist} is not installed; install it with "
            f"`pip install git+https://github.com/crieck2010/{dist}.git`"
        ) from exc


def _clean_research_symbols(symbols: list[str]) -> list[str]:
    out = [s.strip().upper() for s in symbols if s and s.strip()]
    if not out:
        raise ValueError("at least one symbol is required")
    return out


def _closes_by_symbol(bars_by_symbol: dict[str, list]) -> dict[str, list[float]]:
    closes = {}
    for s, bs in bars_by_symbol.items():
        key = (s or "").strip().upper()
        if not key:
            continue
        closes[key] = [float(b["close"]) for b in bs]
    if not closes:
        raise ValueError("at least one symbol with bars is required")
    m = min(len(c) for c in closes.values())
    return {s: c[-m:] for s, c in closes.items()}


def run_pairs_job(
    symbols: list[str],
    bars_by_symbol: dict[str, list],
    lookback: int = 252,
    max_pairs: int = 10,
) -> dict:
    tp = _research_require("trade-pairs", "trade_pairs")
    closes = _closes_by_symbol(bars_by_symbol)
    syms = _clean_research_symbols(symbols)
    missing = [s for s in syms if s not in closes]
    if missing:
        raise ValueError(f"no bars for {', '.join(missing)}")
    prices = {s: closes[s] for s in syms}
    lb = min(lookback, min(len(c) for c in prices.values()))
    if lb < 30:
        raise ValueError(f"need >= 30 bars per symbol, have {lb}")
    cands = tp.find_pairs(prices, lookback=lb, max_pairs=max_pairs)
    return {
        "source": "trade-pairs",
        "symbols": syms,
        "lookback": lb,
        "n_cointegrated": sum(1 for c in cands if c.cointegrated),
        "pairs": [c.to_dict() for c in cands],
    }


def run_orderbook_job(
    symbol: str = "DEMO",
    side: str = "buy",
    quantity: float = 100.0,
    order_type: str = "market",
    n_levels: int = 5,
    level_qty: float = 50.0,
) -> dict:
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")
    if order_type not in ("market", "limit"):
        raise ValueError("order_type must be 'market' or 'limit'")
    tob = _research_require("trade-orderbook", "trade_orderbook")
    book = tob.OrderBook()
    mid, tick = 100.0, 0.01
    oid = 0
    for lvl in range(1, n_levels + 1):
        for s, px in (("bid", mid - lvl * tick), ("ask", mid + lvl * tick)):
            oid += 1
            book.add(tob.Order(order_id=f"seed-{oid}", side=s,
                               quantity=level_qty, price=round(px, 4)))
    probe = tob.Order(
        order_id="probe", side="bid" if side == "buy" else "ask",
        quantity=quantity, price=None if order_type == "market" else mid,
        order_type=order_type)
    fills = tob.fills_for_paper_order(book, probe)
    filled = sum(f["quantity"] for f in fills)
    avg = (sum(f["quantity"] * f["price"] for f in fills) / filled
           if filled else 0.0)
    signed = 1.0 if side == "buy" else -1.0
    return {
        "source": "trade-orderbook",
        "symbol": (symbol or "DEMO").strip().upper(),
        "side": side,
        "quantity": quantity,
        "order_type": order_type,
        "midprice": mid,
        "filled_qty": filled,
        "fill_ratio": filled / quantity if quantity else 0.0,
        "avg_fill_price": round(avg, 4),
        "slippage_bps": round((avg / mid - 1.0) * 10_000 * signed, 2),
        "n_fills": len(fills),
        "book_features": tob.to_agent_features(
            book, levels=n_levels, symbol=(symbol or "DEMO").strip().upper()),
    }


def run_optimize_job(
    symbols: list[str],
    bars_by_symbol: dict[str, list],
    method: str = "max_sharpe",
    max_weight: float = 1.0,
) -> dict:
    import math

    topt = _research_require("trade-optimize", "trade_optimize")
    syms = _clean_research_symbols(symbols)
    closes = _closes_by_symbol({s: bars_by_symbol[s] for s in syms
                                if s in bars_by_symbol})
    if set(closes) != set(syms):
        raise ValueError("no bars for "
                         + ", ".join(s for s in syms if s not in closes))
    syms = sorted(closes)
    flat = [{"symbol": s, "close": c} for s in syms for c in closes[s]]
    names, R = topt.returns_from_dict_bars(flat, syms)
    mu = topt.estimates.shrink_mean(R)
    sigma = topt.estimates.shrink_covariance(R)
    if method == "max_sharpe":
        w = topt.max_sharpe(sigma, mu, max_weight=max_weight)
    elif method == "min_variance":
        w = topt.min_variance(sigma, max_weight=max_weight)
    elif method == "risk_parity":
        w = topt.risk_parity(sigma, max_weight=max_weight)
    elif method == "equal_weight":
        w = topt.equal_weight(len(names))
    else:
        raise ValueError(f"unknown method {method!r}")

    def stats(w_: list[float]) -> dict:
        er = sum(x * m for x, m in zip(w_, mu))
        var = sum(x * sum(s * y for s, y in zip(row, w_))
                  for x, row in zip(w_, sigma))
        vol = math.sqrt(max(var, 0.0))
        return {"expected_return": er, "volatility": vol,
                "sharpe": er / vol if vol > 0 else 0.0}

    port = stats(w)
    frontier = [{"expected_return": p["expected_return"],
                 "volatility": p["volatility"], "sharpe": p["sharpe"]}
                for p in topt.efficient_frontier(sigma, mu,
                                                 max_weight=max_weight,
                                                 n_points=20)]
    return {
        "source": "trade-optimize",
        "symbols": names,
        "method": method,
        "weights": {s: round(x, 4) for s, x in zip(names, w)},
        **{k: round(v, 6) for k, v in port.items()},
        "frontier": frontier,
    }


def _research_corr_matrix(returns: list[list[float]]) -> list[list[float]]:
    import math

    t = len(returns)
    cols = [list(c) for c in zip(*returns)]
    means = [sum(c) / t for c in cols]
    stds = []
    for i, c in enumerate(cols):
        var = sum((x - means[i]) ** 2 for x in c) / (t - 1)
        stds.append(math.sqrt(max(var, 0.0)))
    n = len(cols)
    out = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if stds[i] > 0 and stds[j] > 0:
                cov = sum((returns[k][i] - means[i]) * (returns[k][j] - means[j])
                          for k in range(t)) / (t - 1)
                out[i][j] = max(-1.0, min(1.0, cov / (stds[i] * stds[j])))
            out[i][i] = 1.0
    return out


def run_montecarlo_job(
    symbols: list[str],
    bars_by_symbol: dict[str, list],
    weights: list[float] | None = None,
    equity: float = 100_000.0,
    n_paths: int = 5_000,
    n_steps: int = 252,
    seed: int = 7,
    alpha: float = 0.95,
) -> dict:
    import math

    tmc = _research_require("trade-montecarlo", "trade_montecarlo")
    syms = _clean_research_symbols(symbols)
    closes = _closes_by_symbol({s: bars_by_symbol[s] for s in syms
                                if s in bars_by_symbol})
    syms = sorted(closes)
    R = [[closes[s][i] / closes[s][i - 1] - 1.0 for s in syms]
         for i in range(1, len(closes[syms[0]]))]
    t = len(R)
    mu = [sum(R[k][i] for k in range(t)) / t for i in range(len(syms))]
    sigma = [math.sqrt(sum((R[k][i] - mu[i]) ** 2 for k in range(t)) / (t - 1))
             for i in range(len(syms))]
    corr = _research_corr_matrix(R)
    s0 = [closes[s][-1] for s in syms]
    w = list(weights) if weights else [1.0 / len(syms)] * len(syms)
    if len(w) != len(syms):
        raise ValueError("weights length must match symbols")
    result = tmc.portfolio_var(w, s0, mu, sigma, corr, capital=equity,
                               n_paths=n_paths, n_steps=n_steps, T=1.0,
                               seed=seed, alpha=alpha)
    return {
        "source": "trade-montecarlo",
        "symbols": syms,
        "n_paths": n_paths,
        "n_steps": n_steps,
        "seed": seed,
        "equity": equity,
        **result,
    }


def run_vol_surface_job(
    symbol: str = "SPY",
    spot: float | None = None,
    risk_free: float = 0.03,
) -> dict:
    import math

    tvs = _research_require("trade-volsurface", "trade_volsurface")
    try:
        from trade_volsurface.cli import demo_quotes
    except ImportError as exc:
        raise RuntimeError(
            "trade-volsurface is installed but its demo quotes are not "
            "importable"
        ) from exc
    quotes = demo_quotes()
    s0 = spot if spot is not None else 100.0
    rows = [{"T": q["T"], "K": s0 * math.exp(risk_free * q["T"] + q["k"]),
             "iv": q["iv"]} for q in quotes]
    surface = tvs.from_option_chain(rows, s0=s0, r=risk_free)
    fits = tvs.fit_svi_surface(surface)
    return {
        "source": "trade-volsurface",
        "symbol": (symbol or "SPY").strip().upper(),
        "spot": s0,
        "risk_free": risk_free,
        "n_quotes": len(quotes),
        "expiries": sorted({q["T"] for q in quotes}),
        "svi_fits": {str(k): {p: round(v, 6) for p, v in f.to_dict().items()}
                     for k, f in fits.items()},
        "agent_surface": tvs.to_agent_surface(surface),
    }


def _month_end_closes(bars: list) -> list[tuple[str, float]]:
    out: dict[str, float] = {}
    for b in bars:
        out[str(b["timestamp"])[:7].replace("-", "")] = float(b["close"])
    return sorted(out.items())


def run_factor_analysis_job(
    symbols: list[str],
    bars_by_symbol: dict[str, list],
    model: str = "ff5",
    n_months: int = 60,
) -> dict:
    tf = _research_require("trade-factors", "trade_factors")
    syms = _clean_research_symbols(symbols)
    factors = tf.demo_factors(n=120, seed=7)
    monthly: dict[str, list[float]] = {}
    for s in syms:
        if s not in bars_by_symbol:
            raise ValueError(f"no bars for {s}")
        me = _month_end_closes(bars_by_symbol[s])
        rets = [me[i][1] / me[i - 1][1] - 1.0 for i in range(1, len(me))]
        if len(rets) < 24:
            raise ValueError(f"need >= 24 monthly returns for {s}, "
                             f"have {len(rets)} (fetch more bars)")
        monthly[s] = rets
    k = min(n_months, min(len(r) for r in monthly.values()),
            len(factors.dates))
    fdata = tf.FactorData(
        factors.dates[-k:],
        {name: col[-k:] for name, col in factors.factors.items()})
    assets = {s: fdata.excess(monthly[s][-k:]) for s in syms}
    results = tf.panel_regressions(assets, fdata, model=model)
    grs = tf.grs_test(results, fdata, model=model)
    report = tf.to_agent_factor_report(results, grs)
    return {"source": "trade-factors", "model": model, "n_months": k,
            **report}


def run_sentiment_price_job(
    symbol: str,
    bars: list | None = None,
    sentiment_rows: list[dict] | None = None,
    days: int = 180,
    seed: int = 7,
) -> dict:
    tsvp = _research_require("trade-sentiment-vs-price",
                             "trade_sentiment_vs_price")
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("a symbol is required")
    if sentiment_rows is not None:
        if not bars:
            raise ValueError("sentiment_rows need matching price bars")
        sent = tsvp.from_sentiment_scan(sentiment_rows)
        prices = tsvp.prices_from_dict_bars(
            [{"date": str(b["timestamp"])[:10], "close": b["close"]}
             for b in bars])
    else:
        sent, prices = tsvp.demo_data(n_days=days, symbol=symbol, seed=seed)
    return tsvp.to_agent_report(symbol, sent, prices)


def run_correlation_job(
    symbols: list[str],
    bars_by_symbol: dict[str, list],
    method: str = "pearson",
    shrinkage: str = "ledoit_wolf",
    lookback: int = 252,
) -> dict:
    """Correlation/EDA report over a symbol universe (trade-eda).

    Mirrors the web dashboard's canonical job one-for-one: same
    signature, same plain-data result.  Full bar dicts are passed through
    (volume/timestamp feed the data-quality section); series are truncated
    to the common length, oldest-first.
    """
    if method not in ("pearson", "spearman"):
        raise ValueError("method must be 'pearson' or 'spearman'")
    te = _research_require("trade-eda", "trade_eda")
    norm: dict[str, list] = {}
    for s, bs in bars_by_symbol.items():
        key = (s or "").strip().upper()
        if key:
            norm[key] = list(bs)
    syms = _clean_research_symbols(symbols)
    missing = [s for s in syms if s not in norm]
    if missing:
        raise ValueError("no bars for " + ", ".join(missing))
    if len(syms) < 2:
        raise ValueError("need at least two symbols")
    m = min(len(norm[s]) for s in syms)
    lb = min(lookback, m)
    if lb < 30:
        raise ValueError(f"need >= 30 bars per symbol, have {lb}")
    bars = {s: norm[s][-lb:] for s in syms}
    return te.analyze(bars, method=method, shrinkage=shrinkage)


def run_breadth_job(
    preset: str = "standard",
    seed: int = 7,
    n_days: int = 600,
    thrust_window: int = 10,
) -> dict:
    """Market-breadth regime snapshot over a seeded demo universe.

    Mirrors the web dashboard's canonical ``run_breadth_job`` one-for-one:
    same signature, same validation, same plain-data result.  ``universe`` /
    ``weights`` come from :func:`trade_breadth.demo_universe`; the snapshot
    is computed with :func:`trade_breadth.snapshot` (which raises
    ValueError for an unknown preset).  Demo data — illustrative, not real.
    """
    tb = _research_require("trade-breadth", "trade_breadth")
    seed = int(seed)
    n_days = int(n_days)
    thrust_window = int(thrust_window)
    if n_days < 60:
        raise ValueError(f"need >= 60 days, have {n_days}")
    if n_days > 5000:
        raise ValueError(f"n_days capped at 5000, have {n_days}")
    if thrust_window < 1:
        raise ValueError("thrust_window must be >= 1")
    universe, weights = tb.demo_universe(seed=seed, n_days=n_days)
    # the engine raises ValueError for an unknown preset
    snapshot = tb.snapshot(universe, weights=weights, preset=preset,
                           thrust_window=thrust_window)
    return {
        "source": "trade-breadth",
        "preset": preset,
        "seed": seed,
        "n_days": n_days,
        "n_symbols": snapshot["universe"]["n_symbols"],
        "snapshot": snapshot,
    }


def run_macro_job(
    preset: str = "standard",
    seed: int = 42,
    days: int = 600,
) -> dict:
    """Copper/gold macro regime snapshot over a seeded demo series.

    Mirrors the web dashboard's canonical ``run_macro_job`` one-for-one:
    same signature, same validation, same plain-data result.  The series
    come from :func:`trade_macro.demo_series` and are marked
    ``source="synthetic"`` provenance.  Demo data — illustrative, not real.
    """
    tm = _research_require("trade-macro", "trade_macro")
    seed = int(seed)
    days = int(days)
    if days < 250:
        raise ValueError(f"need >= 250 days for the 200DMA, have {days}")
    if days > 5000:
        raise ValueError(f"days capped at 5000, have {days}")
    series = tm.demo_series(seed=seed, days=days)
    # the engine raises ValueError for an unknown preset
    snapshot = tm.snapshot(series["copper"], series["gold"], preset=preset,
                           source="synthetic")
    return {
        "source": "trade-macro",
        "preset": preset,
        "seed": seed,
        "days": days,
        "snapshot": snapshot,
    }


def run_stream_demo_job(
    symbols: tuple = ("AAA", "BBB", "CCC"),
    seed: int = 7,
    n_ticks: int = 600,
) -> dict:
    """End-to-end demo of the trade-stream pipeline (feed -> bus -> cache).

    Mirrors the web dashboard's canonical ``run_stream_demo_job`` one-for-one:
    same signature, same validation, same plain-data result.  Wraps
    :func:`trade_stream.run_demo`; the returned dict is additionally verified
    JSON-serializable here.  Simulated ticks only — no network.
    """
    ts = _research_require("trade-stream", "trade_stream")
    syms = tuple((s or "").strip().upper() for s in (symbols or ()))
    syms = tuple(s for s in syms if s)
    if not syms:
        raise ValueError("at least one symbol is required")
    seed = int(seed)
    n_ticks = int(n_ticks)
    if n_ticks < 1:
        raise ValueError("n_ticks must be >= 1")
    if n_ticks > 10_000:
        raise ValueError("n_ticks capped at 10_000 for the dashboard demo")
    result = ts.run_demo(symbols=syms, seed=seed, n_ticks=n_ticks)
    out = {"source": "trade-stream", "demo": True, **result}
    try:
        import json

        json.dumps(out)
    except TypeError as exc:
        raise RuntimeError(
            "trade-stream returned a non-JSON-serializable demo result"
        ) from exc
    return out


def run_reconcile_demo_job() -> dict:
    """Paper-ledger vs broker reconcile demo via the Robinhood MCP mock.

    Mirrors the web dashboard's canonical ``run_reconcile_demo_job``
    one-for-one: same signature, same plain-data result.  Positions flow
    from ``MockMCPTransport.demo()`` through ``RobinhoodMCPBroker`` into
    ``broker_position_map``; the paper side is the deliberate-drift map
    ``{"AAPL": 10.0, "TSLA": 4.5, "NVDA": 2.0}`` (mirrors trade-paper's own
    ``robinhood --demo reconcile``), so ``clean`` is False by design.
    Read-only demo — no orders, no real account access.
    """
    _research_require("trade-paper", "trade_paper")
    from trade_paper import robinhood_mcp as rh

    transport = rh.MockMCPTransport.demo()
    broker = rh.RobinhoodMCPBroker(transport=transport)
    accounts = broker.get_accounts()
    account_id = (accounts[0].get("account_id") or "") if accounts else ""
    broker_positions = rh.broker_position_map(
        broker.get_positions(account_id) if account_id else [])
    paper_positions = {"AAPL": 10.0, "TSLA": 4.5, "NVDA": 2.0}  # deliberate drift
    result = rh.reconcile(paper_positions, broker_positions)
    return {
        "source": "trade-paper",
        "demo": True,
        "account_id": account_id,
        "paper_positions": paper_positions,
        "broker_positions": broker_positions,
        "reconcile": result,
    }


# ---------------------------------------------------------------------------
# Terminal wave (mirrors trade_dashboard_web.engine.terminal_service one-for-one)
# ---------------------------------------------------------------------------
# Local stdlib fallbacks for the five canonical terminal jobs.  When the
# ``trade-dashboard-web`` package is installed these names are bound to the
# web engine instead (see ``engine/__init__.py``); the fallbacks below are
# only used in a standalone install and produce identical results for
# identical inputs (same seeds, same algorithms, same demo datasets).
#
# Degraded behavior vs the shared web engine: none in demo/bare mode — the
# web terminal_service is itself stdlib-only for every demo path.  The
# differences only appear on the *real* data paths:
# - run_trades_job / run_performance_job / run_risk_monitor_job: identical
#   everywhere (read-only SQLite + stdlib math); the only requirement is a
#   real ledger file, same as the web job.
# - run_agent_activity_job: identical; both need the track-record JSONL and
#   the ``trade-agents`` engine for leaderboards.
# - run_network_job: identical for ``source="demo"`` and the stdlib
#   correlation fallback; on the real ``source="yfinance"`` path the
#   correlation matrix comes from this package's own ``run_correlation_job``
#   (needs ``trade-eda``) instead of the web engine's research_service, so
#   if trade-eda is missing the fallback keeps the stdlib Pearson/Spearman
#   where the web job would attempt the engine first.  MST, clusters, and
#   the seeded layout are always computed identically.

_TDEMO_SEED = 7

_TOPEN_STATES = {"submitted", "accepted", "pending", "working", "partial",
                 "partially_filled", "open"}

_TROLL_WINDOW = 63  # ~one quarter of daily bars

_TMST_CUT = 1.0  # distance cut for single-linkage clusters
_TFR_ITERATIONS = 300  # fixed: determinism given the seed
_TDEMO_UNIVERSE = ["SPY", "QQQ", "DIA", "IWM", "XLK", "XLF", "XLE", "XLV",
                   "XLI", "XLU", "XLP", "XLY"]


def _trequire(dist: str, package: str):
    try:
        return __import__(package, fromlist=["*"])
    except ImportError as exc:
        raise RuntimeError(
            f"{dist} is not installed; install it with "
            f"`pip install git+https://github.com/crieck2010/{dist}.git`"
        ) from exc


def _tparse_ts(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _tround(x, nd=4):
    if x is None:
        return None
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return round(float(x), nd)


def _tjsonable(value):
    if isinstance(value, dict):
        return {str(k): _tjsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_tjsonable(v) for v in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _tresolve_ledger_path(ledger_path=None):
    if ledger_path:
        p = Path(ledger_path).expanduser()
        return str(p) if p.exists() else None
    env = os.environ.get("TRADE_PAPER_LEDGER")
    if env and Path(env).expanduser().exists():
        return str(Path(env).expanduser())
    for cand in (Path("trade-paper.db"), Path.home() / "trade-paper.db"):
        if cand.exists():
            return str(cand)
    return None


def _topen_ro(path: str) -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def _ttables(db: sqlite3.Connection) -> set:
    return {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _tresolve_track_record_path(track_record_path=None):
    if track_record_path:
        p = Path(track_record_path).expanduser()
        return str(p) if p.exists() else None
    env = os.environ.get("TRADE_AGENTS_TRACK_RECORD")
    if env and Path(env).expanduser().exists():
        return str(Path(env).expanduser())
    cand = Path("trade-agents-track-record.jsonl")
    return str(cand) if cand.exists() else None


def _tread_jsonl(path: str):
    events, bad = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    return events, bad


def _tsnapshot_input(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    p = Path(str(value)).expanduser()
    if not p.exists():
        raise ValueError(f"snapshot file not found: {value}")
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"snapshot file must hold a JSON object: {value}")
    return data


# -- 1. Trades blotter -------------------------------------------------------

def _tfifo_match(fills: list) -> tuple:
    lots: dict = {}
    realized: dict = {}
    net: dict = {}
    for fl in sorted(fills, key=lambda r: str(r.get("filled_at") or "")):
        sym = str(fl.get("symbol") or "").upper()
        side = str(fl.get("side") or "").lower()
        qty = float(fl.get("quantity") or 0.0)
        px = float(fl.get("price") or 0.0)
        oid = str(fl.get("client_order_id") or "")
        if qty <= 0:
            continue
        book = lots.setdefault(sym, [])
        if side == "buy":
            book.append([qty, px, oid])
            net[sym] = net.get(sym, 0.0) + qty
        elif side == "sell":
            need = qty
            pnl = 0.0
            while need > 1e-12 and book:
                lot_qty, lot_px, _ = book[0]
                take = min(need, lot_qty)
                pnl += take * (px - lot_px)
                book[0][0] = lot_qty - take
                need -= take
                if book[0][0] <= 1e-12:
                    book.pop(0)
            realized[oid] = realized.get(oid, 0.0) + pnl
            net[sym] = net.get(sym, 0.0) - qty
    return realized, net


def _tdemo_trades() -> list:
    rng = random.Random(_TDEMO_SEED)
    syms = ["SPY", "QQQ", "AAPL", "MSFT", "TSLA", "NVDA"]
    strategies = ["sma_crossover", "mean_reversion", "breakout"]
    rows = []
    base = datetime(2026, 7, 1, 14, 30, tzinfo=timezone.utc)
    for i in range(12):
        sym = syms[i % len(syms)]
        side = "buy" if i % 2 == 0 else "sell"
        qty = 10 * (1 + i % 5)
        px = round(100 + rng.uniform(-20, 60), 2)
        pnl = round(rng.uniform(-250, 400), 2)
        outcome = "win" if pnl > 0 else ("loss" if pnl < 0 else "unknown")
        rows.append({
            "id": f"demo-order-{i + 1:03d}", "symbol": sym, "side": side,
            "qty": float(qty), "filled_qty": float(qty),
            "avg_fill_price": px, "commission": round(qty * 0.01, 2),
            "strategy": strategies[i % len(strategies)], "agent": None,
            "state": "filled",
            "created_at": (base + timedelta(days=i * 6)).isoformat(),
            "filled_at": (base + timedelta(days=i * 6, hours=1)).isoformat(),
            "realized_pnl": pnl, "outcome": outcome, "demo": True,
        })
    return rows


def _tapply_trade_filters(rows: list, filters: dict) -> list:
    def keep(r: dict) -> bool:
        df, dt = filters.get("date_from"), filters.get("date_to")
        if df and str(r.get("created_at") or "")[:10] < str(df)[:10]:
            return False
        if dt and str(r.get("created_at") or "")[:10] > str(dt)[:10]:
            return False
        sym = filters.get("symbol")
        if sym and str(r.get("symbol") or "").upper() != str(sym).upper():
            return False
        side = filters.get("side")
        if side and str(r.get("side") or "").lower() != str(side).lower():
            return False
        strat = filters.get("strategy")
        if strat and str(strat).lower() not in str(r.get("strategy") or "").lower():
            return False
        ag = filters.get("agent")
        if ag:
            hay = (str(r.get("strategy") or "") + " "
                   + str(r.get("id") or "")).lower()
            if str(ag).lower() not in hay:
                return False
        oc = filters.get("outcome")
        if oc and str(r.get("outcome") or "").lower() != str(oc).lower():
            return False
        return True
    return [r for r in rows if keep(r)]


def run_trades_job(
    ledger_path=None,
    date_from=None,
    date_to=None,
    symbol=None,
    side=None,
    strategy=None,
    agent=None,
    outcome=None,
    limit=500,
) -> dict:
    """Trade blotter over the trade-paper audit ledger (read-only).

    Joins ``orders`` with ``fills``; realized P&L per order comes from FIFO
    lot matching of fills per symbol, attributed to the closing (sell)
    fill's order.  Outcome is ``win``/``loss`` when the attributed P&L is
    nonzero, ``open`` when fills remain part of an open net position (or
    the order is still working), else ``unknown``.

    The paper ledger has **no per-order agent column**: the ``agent``
    filter is a case-insensitive substring match over ``strategy`` and the
    client order id (documented approximation).

    With no ledger found, returns a deterministic in-memory DEMO dataset
    (``demo: True``, every row flagged) — never presented as real.
    """
    path = _tresolve_ledger_path(ledger_path)
    filters = {"date_from": date_from, "date_to": date_to, "symbol": symbol,
               "side": side, "strategy": strategy, "agent": agent,
               "outcome": outcome, "limit": limit}
    if path is None:
        rows = _tdemo_trades()
        rows = _tapply_trade_filters(rows, filters)
        return {"trades": rows[: max(int(limit or 0), 0)], "count": len(rows),
                "filters": filters, "demo": True, "ledger_path": None,
                "message": ("DEMO — no paper ledger found (looked for "
                            "TRADE_PAPER_LEDGER, ./trade-paper.db, "
                            "~/trade-paper.db). Synthetic rows for plumbing "
                            "tests only; not real trades.")}
    db = _topen_ro(path)
    try:
        have = _ttables(db)
        for t in ("orders", "fills"):
            if t not in have:
                raise ValueError(f"ledger {path} has no {t!r} table")
        orders = [dict(r) for r in db.execute("SELECT * FROM orders")]
        fills = [dict(r) for r in db.execute("SELECT * FROM fills")]
    finally:
        db.close()
    realized, net_qty = _tfifo_match(fills)
    fills_by_order: dict = {}
    for fl in fills:
        fills_by_order.setdefault(str(fl.get("client_order_id") or ""),
                                  []).append(fl)
    rows = []
    for o in orders:
        oid = str(o.get("client_order_id") or "")
        of = fills_by_order.get(oid, [])
        fqty = sum(float(f.get("quantity") or 0.0) for f in of)
        notional = sum(float(f.get("quantity") or 0.0)
                       * float(f.get("price") or 0.0) for f in of)
        comm = sum(float(f.get("commission") or 0.0) for f in of)
        pnl = realized.get(oid, 0.0)
        sym = str(o.get("symbol") or "").upper()
        if pnl > 1e-12:
            oc = "win"
        elif pnl < -1e-12:
            oc = "loss"
        elif fqty > 0 and abs(net_qty.get(sym, 0.0)) > 1e-12:
            oc = "open"
        elif str(o.get("state") or "").lower() in _TOPEN_STATES:
            oc = "open"
        else:
            oc = "unknown"
        filled_at = max((str(f.get("filled_at") or "") for f in of),
                        default=None) or None
        rows.append({
            "id": oid, "symbol": sym,
            "side": str(o.get("side") or "").lower(),
            "qty": _tround(o.get("quantity"), 4),
            "filled_qty": _tround(fqty, 4),
            "avg_fill_price": _tround(notional / fqty, 4) if fqty > 0 else None,
            "commission": _tround(comm, 2),
            "strategy": o.get("strategy"),
            "agent": None,
            "state": o.get("state"),
            "created_at": o.get("created_at"),
            "filled_at": filled_at,
            "realized_pnl": _tround(pnl, 2),
            "outcome": oc,
            "demo": False,
        })
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    rows = _tapply_trade_filters(rows, filters)
    return {"trades": _tjsonable(rows[: max(int(limit or 0), 0)]),
            "count": len(rows), "filters": filters, "demo": False,
            "ledger_path": path,
            "message": (f"{len(orders)} orders, {len(fills)} fills read "
                        f"read-only from {path}")}


def trades_to_csv(result: dict) -> str:
    """Render a ``run_trades_job`` result as CSV (for the export route)."""
    buf = io.StringIO()
    cols = ["id", "symbol", "side", "qty", "filled_qty", "avg_fill_price",
            "commission", "strategy", "state", "created_at", "filled_at",
            "realized_pnl", "outcome", "demo"]
    w = csv.writer(buf)
    w.writerow(cols)
    for r in result.get("trades", []):
        w.writerow([r.get(c) for c in cols])
    return buf.getvalue()


# -- 2. Performance analytics --------------------------------------------------

def _tdemo_equity(n: int = 252, seed: int = _TDEMO_SEED) -> list:
    rng = random.Random(seed)
    eq, out = 100_000.0, []
    t = datetime(2025, 1, 2, tzinfo=timezone.utc)
    for i in range(n):
        eq *= 1.0 + 0.0004 + rng.gauss(0, 0.008)
        out.append(((t + timedelta(days=i)).isoformat(), eq))
    return out


def _tnormalize_equity(raw) -> list:
    pts: list = []
    for e in raw or []:
        if isinstance(e, (list, tuple)) and len(e) == 2:
            ts, val = e
        elif isinstance(e, dict):
            ts = (e.get("timestamp") or e.get("ts") or e.get("date")
                  or e.get("at"))
            val = e.get("equity", e.get("value", e.get("eq")))
        else:
            ts = getattr(e, "timestamp", None)
            val = getattr(e, "equity", getattr(e, "value", None))
        if ts is None or val is None:
            continue
        ts_s = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        try:
            pts.append((ts_s, float(val)))
        except (TypeError, ValueError):
            continue
    pts.sort(key=lambda p: p[0])
    return pts


def _tnormalize_trade_pnls(raw) -> list:
    pnls = []
    for t in raw or []:
        if isinstance(t, dict):
            v = t.get("pnl", t.get("realized_pnl", t.get("profit")))
        else:
            v = getattr(t, "pnl", getattr(t, "realized_pnl", None))
        try:
            pnls.append(float(v))
        except (TypeError, ValueError):
            continue
    return pnls


def _trunning_peak(eq: list) -> list:
    out, peak = [], 0.0
    for v in eq:
        peak = max(peak, v)
        out.append(peak)
    return out


def _tperformance_from_equity(points: list, trade_pnls: list,
                              risk_free: float = 0.0) -> dict:
    n = len(points)
    eq = [p[1] for p in points]
    rets = [eq[i] / eq[i - 1] - 1.0 for i in range(1, n)] if n > 1 else []
    peak, dd = eq[0] if eq else 0.0, []
    for v in eq:
        peak = max(peak, v)
        dd.append(-(peak - v) / peak if peak > 0 else 0.0)
    max_dd = max((peak_i - v) / peak_i
                 for peak_i, v in zip(_trunning_peak(eq), eq)
                 ) if eq else 0.0
    months: dict = {}
    for i, r in enumerate(rets):
        dt = _tparse_ts(points[i + 1][0])
        if dt is None:
            continue
        months.setdefault((dt.year, dt.month), []).append(r)
    years = sorted({y for y, _ in months})
    monthly = []
    for y in years:
        row = []
        for m in range(1, 13):
            rs = months.get((y, m))
            row.append(_tround(math.prod(1.0 + x for x in rs) - 1.0, 6)
                       if rs else None)
        monthly.append(row)
    r_sharpe: list = [None] * n
    r_vol: list = [None] * n
    for i in range(_TROLL_WINDOW, n):
        w = [r - risk_free / 252.0 for r in rets[i - _TROLL_WINDOW:i]]
        mu = sum(w) / len(w)
        var = sum((x - mu) ** 2 for x in w) / (len(w) - 1)
        sd = math.sqrt(var)
        vol = sd * math.sqrt(252.0)
        r_vol[i] = _tround(vol, 6)
        r_sharpe[i] = _tround(mu / sd * math.sqrt(252.0), 4) if sd > 0 else None
    hist = {"bins": [], "counts": []}
    if len(rets) >= 2:
        lo, hi = min(rets), max(rets)
        span = (hi - lo) or 1e-9
        nb = 25
        edges = [lo + span * k / nb for k in range(nb + 1)]
        counts = [0] * nb
        for r in rets:
            k = min(int((r - lo) / span * nb), nb - 1)
            counts[k] += 1
        hist = {"bins": [_tround(e, 6) for e in edges], "counts": counts}
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    cagr = None
    if n > 1 and eq[0] > 0:
        d0, d1 = _tparse_ts(points[0][0]), _tparse_ts(points[-1][0])
        yrs = ((d1 - d0).total_seconds() / 86400.0 / 365.25
               if d0 and d1 else n / 252.0)
        if yrs > 0:
            cagr = (eq[-1] / eq[0]) ** (1.0 / yrs) - 1.0
    summary = {
        "win_rate": _tround(len(wins) / len(trade_pnls), 4) if trade_pnls else None,
        "profit_factor": _tround(gp / gl, 4) if gl > 0 else None,
        "expectancy": _tround(sum(trade_pnls) / len(trade_pnls), 4)
        if trade_pnls else None,
        "max_drawdown": _tround(max_dd, 6),
        "cagr": _tround(cagr, 6),
        "n_trades": len(trade_pnls),
        "start": points[0][0] if points else None,
        "end": points[-1][0] if points else None,
    }
    return {
        "equity": [[ts, _tround(v, 2)] for ts, v in points],
        "drawdown": [_tround(d, 6) for d in dd],
        "monthly": monthly,
        "years": years,
        "rolling_sharpe": r_sharpe,
        "rolling_vol": r_vol,
        "histogram": hist,
        "summary": summary,
    }


def _tfills_realized_series(db: sqlite3.Connection) -> list:
    fills = [dict(r) for r in db.execute(
        "SELECT * FROM fills ORDER BY filled_at")]
    if not fills:
        return []
    lots: dict = {}
    cum, pts = 0.0, []
    for fl in fills:
        sym = str(fl.get("symbol") or "").upper()
        side = str(fl.get("side") or "").lower()
        qty = float(fl.get("quantity") or 0.0)
        px = float(fl.get("price") or 0.0)
        book = lots.setdefault(sym, [])
        if side == "buy":
            book.append([qty, px])
        elif side == "sell":
            need = qty
            while need > 1e-12 and book:
                take = min(need, book[0][0])
                cum += take * (px - book[0][1])
                book[0][0] -= take
                need -= take
                if book[0][0] <= 1e-12:
                    book.pop(0)
        pts.append((str(fl.get("filled_at") or ""), cum))
    return pts


def run_performance_job(
    source="paper",
    ledger_path=None,
    backtest=None,
    backtest_path=None,
    risk_free=0.0,
) -> dict:
    """Performance analytics over paper equity or a backtest result.

    ``source="paper"``: equity from the ledger's ``equity_snapshots``
    table; when the ledger has no snapshots, falls back to a
    *reconstructed* relative curve (cumulative FIFO realized P&L rebased
    at 0 — documented in the payload as ``equity_source``; it is a shape
    proxy, not true equity).

    ``source="backtest"``: accepts a trade-backtest result *dict* or a
    path to its JSON output.  See the web canonical docstring for the
    accepted schema (lenient superset).
    """
    if source not in ("paper", "backtest"):
        raise ValueError("source must be 'paper' or 'backtest'")
    demo = False
    equity_source = "equity_snapshots"
    message = ""
    trade_pnls: list = []
    if source == "paper":
        path = _tresolve_ledger_path(ledger_path)
        if path is None:
            points = _tdemo_equity()
            trade_pnls = [r["realized_pnl"] for r in _tdemo_trades()]
            demo, equity_source = True, "demo"
            message = "DEMO — no paper ledger found; seeded synthetic equity."
        else:
            db = _topen_ro(path)
            try:
                have = _ttables(db)
                snaps = []
                if "equity_snapshots" in have:
                    snaps = [dict(r) for r in db.execute(
                        "SELECT at, equity FROM equity_snapshots ORDER BY at")]
                if snaps:
                    points = _tnormalize_equity(
                        [{"timestamp": s["at"], "equity": s["equity"]}
                         for s in snaps])
                    message = (f"{len(snaps)} equity snapshots read read-only "
                               f"from {path}")
                else:
                    points = _tfills_realized_series(db)
                    equity_source = "fills_reconstructed"
                    message = ("no equity_snapshots in ledger; equity is a "
                               "RECONSTRUCTED relative curve (cumulative FIFO "
                               "realized P&L rebased at 0) — shape proxy only")
                if "fills" in have:
                    fills = [dict(r) for r in db.execute("SELECT * FROM fills")]
                    realized, _ = _tfifo_match(fills)
                    trade_pnls = [p for p in realized.values() if p != 0.0]
            finally:
                db.close()
            if not points:
                points = _tdemo_equity()
                trade_pnls = [r["realized_pnl"] for r in _tdemo_trades()]
                demo, equity_source = True, "demo"
                message = ("ledger has no equity_snapshots and no fills; "
                           "DEMO synthetic equity shown instead")
    else:
        data = backtest
        if data is None and backtest_path:
            with open(Path(backtest_path).expanduser(), encoding="utf-8") as f:
                data = json.load(f)
        if data is None:
            raise ValueError("source='backtest' needs backtest or backtest_path")
        if isinstance(data, dict) and "equity" not in data and "equity_curve" in data:
            data = {**data, "equity": data["equity_curve"]}
        points = _tnormalize_equity((data.get("equity") if isinstance(data, dict)
                                    else getattr(data, "equity_curve", [])))
        trade_pnls = _tnormalize_trade_pnls(
            (data.get("trades") if isinstance(data, dict)
             else getattr(data, "trades", [])))
        equity_source = "backtest"
        message = (f"backtest result: {len(points)} equity points, "
                   f"{len(trade_pnls)} trades")
    if not points:
        raise ValueError("no equity points available")
    out = _tperformance_from_equity(points, trade_pnls, risk_free=float(risk_free))
    out.update({"source": source, "equity_source": equity_source,
                "risk_free": float(risk_free), "demo": demo, "message": message})
    return _tjsonable(out)


# -- 3. Agent activity --------------------------------------------------------

_TELO_K = 32.0
_TELO_BASE = 1500.0


def _telo_expect(rating: float, opp: float = _TELO_BASE) -> float:
    return 1.0 / (1.0 + 10.0 ** ((opp - rating) / 400.0))


def _telo_curves(events: list) -> dict:
    """Dashboard-side Elo ratings per agent over time.

    Each ``outcome`` / ``pm_outcome`` event is treated as a match against a
    fixed 1500-rated "market": score 1/0.5/0 by the sign of the event's mean
    return, ``E = 1/(1+10^((1500-R)/400))``, ``R += 32*(S-E)``.  This is a
    dashboard approximation for sparklines — *not* a trade-agents engine
    number (trade-agents scores agents with decayed Sharpe / Brier /
    penalized-Sharpe formulas in ``track_record.py``).
    """
    proposals = {e.get("idea_id"): e.get("agent")
                 for e in events if e.get("type") == "proposal"}
    games: list = []
    for e in events:
        t = e.get("type")
        if t == "outcome":
            agent = proposals.get(e.get("idea_id"))
            rets = e.get("returns") or []
            mu = sum(rets) / len(rets) if rets else 0.0
            score = 1.0 if mu > 0 else (0.0 if mu < 0 else 0.5)
            if agent:
                games.append((str(e.get("ts") or ""), agent, score))
        elif t == "pm_outcome":
            agent = e.get("agent")
            rets = e.get("returns") or []
            mu = sum(rets) / len(rets) if rets else 0.0
            score = 1.0 if mu > 0 else (0.0 if mu < 0 else 0.5)
            if agent:
                games.append((str(e.get("ts") or ""), agent, score))
    games.sort(key=lambda g: g[0])
    ratings: dict = {}
    curves: dict = {}
    for ts, agent, score in games:
        r = ratings.get(agent, _TELO_BASE)
        r = r + _TELO_K * (score - _telo_expect(r))
        ratings[agent] = r
        curves.setdefault(agent, []).append(
            {"ts": ts, "rating": round(r, 1)})
    return curves


def _tbrier_calibration(events: list, n_bins: int = 10) -> dict:
    """Brier calibration of risk-desk drawdown forecasts.

    Each ``risk_forecast`` (``p_exceed`` = P(max DD > threshold)) paired
    with the later ``outcome`` for the same idea: ``o = 1`` if the
    realized max drawdown exceeded the threshold else 0.  Binned by
    forecast probability; observed = mean ``o`` per bin.
    """
    outcomes = {e.get("idea_id"): e for e in events
                if e.get("type") == "outcome"}
    pairs = []
    for e in events:
        if e.get("type") != "risk_forecast":
            continue
        out = outcomes.get(e.get("idea_id"))
        if out is None:
            continue
        fc = e.get("forecast") or {}
        try:
            p = max(0.0, min(1.0, float(fc.get("p_exceed", 0.5))))
            thr = float(fc.get("dd_threshold", 0.10))
        except (TypeError, ValueError):
            continue
        rets = [float(r) for r in (out.get("returns") or [])]
        peak, worst, eq = 1.0, 0.0, 1.0
        for r in rets:
            eq *= 1.0 + r
            peak = max(peak, eq)
            worst = max(worst, (peak - eq) / peak if peak > 0 else 0.0)
        pairs.append((p, 1.0 if worst > thr else 0.0))
    bins = [(i + 0.5) / n_bins for i in range(n_bins)]
    sums = [0.0] * n_bins
    counts = [0] * n_bins
    for p, o in pairs:
        k = min(int(p * n_bins), n_bins - 1)
        sums[k] += o
        counts[k] += 1
    return {"bins": bins,
            "observed": [round(sums[i] / counts[i], 4) if counts[i] else None
                         for i in range(n_bins)],
            "n": counts}


def _tdebates_from_approvals(approvals_ledger_path, limit):
    """Debate timeline from the paper ledger's approvals table.

    trade-agents' ``adapters`` stash the debate synthesis (bull/bear
    pressure, conviction, rounds) into ``approvals.metrics`` JSON under
    ``chain.debate`` when an idea is submitted for approval — that is the
    durable debate record the dashboard reads.
    """
    path = _tresolve_ledger_path(approvals_ledger_path)
    if path is None:
        return [], "no paper ledger found — debate timeline unavailable"
    db = _topen_ro(path)
    try:
        if "approvals" not in _ttables(db):
            return [], f"ledger {path} has no approvals table"
        rows = [dict(r) for r in db.execute(
            "SELECT discovery_key, strategy, symbols, metrics, status, "
            "created_at FROM approvals ORDER BY created_at DESC")]
    finally:
        db.close()
    debates = []
    for r in rows:
        try:
            metrics = json.loads(r.get("metrics") or "{}")
        except json.JSONDecodeError:
            continue
        debate = ((metrics.get("chain") or {}).get("debate")) or {}
        if not debate:
            continue
        net = debate.get("net_pressure", 0.0) or 0.0
        verdict = "bull" if net > 0 else ("bear" if net < 0 else "even")
        debates.append({
            "idea_id": r.get("discovery_key"),
            "ts": r.get("created_at"),
            "strategy": r.get("strategy"),
            "symbols": r.get("symbols"),
            "challengers": ["bull", "bear"],
            "verdict": verdict,
            "conviction": debate.get("conviction"),
            "net_pressure": debate.get("net_pressure"),
            "n_rounds": debate.get("n_rounds"),
            "approval_status": r.get("status"),
        })
    return debates[: max(int(limit or 0), 0)], (
        f"{len(debates)} debated ideas read read-only from {path}")


def _tapproval_queue(approvals_ledger_path, limit):
    path = _tresolve_ledger_path(approvals_ledger_path)
    if path is None:
        return [], "no paper ledger found — approval queue unavailable"
    db = _topen_ro(path)
    try:
        if "approvals" not in _ttables(db):
            return [], f"ledger {path} has no approvals table"
        rows = [dict(r) for r in db.execute(
            "SELECT id, strategy, symbols, metrics, created_at FROM approvals "
            "WHERE status='pending' ORDER BY created_at DESC")]
    finally:
        db.close()
    queue = []
    for r in rows[: max(int(limit or 0), 0)]:
        try:
            metrics = json.loads(r.get("metrics") or "{}")
        except json.JSONDecodeError:
            metrics = {}
        queue.append({
            "id": r.get("id"), "strategy": r.get("strategy"),
            "symbols": r.get("symbols"),
            "score": (metrics.get("score")
                      if isinstance(metrics, dict) else None),
            "created_at": r.get("created_at"),
        })
    return queue, f"{len(rows)} pending approvals read read-only from {path}"


def run_agent_activity_job(
    track_record_path=None,
    approvals_ledger_path=None,
    limit=50,
) -> dict:
    """Agent activity: leaderboards, Elo curves, Brier calibration, debates.

    Reads the trade-agents v0.2.0 track-record JSONL
    (``proposal`` / ``verdict`` / ``outcome`` / ``risk_forecast`` /
    ``pm_outcome`` events) and scores agents with the engine's own pure
    functions from ``trade_agents.track_record``
    (``score_all``/``debate_weights`` — lazy import).  Debates come from
    the paper ledger's ``approvals`` table (debate synthesis stored under
    ``metrics.chain.debate``); the approval queue is the ledger's pending
    approvals.  Missing files yield graceful empties with an explanatory
    ``message`` — never an error.
    """
    limit = max(int(limit or 0), 0)
    notes: list = []
    path = _tresolve_track_record_path(track_record_path)
    events: list = []
    if path is None:
        notes.append("no track-record JSONL found (TRADE_AGENTS_TRACK_RECORD "
                     "or ./trade-agents-track-record.jsonl)")
    else:
        events, bad = _tread_jsonl(path)
        notes.append(f"{len(events)} track-record events from {path}"
                     + (f" ({bad} malformed lines skipped)" if bad else ""))
    leaderboards = {"researcher": [], "risk_desk": [], "pm": []}
    if events:
        try:
            tr = _trequire("trade-agents", "trade_agents.track_record")
        except RuntimeError as exc:
            notes.append(f"leaderboards unavailable: {exc}")
            tr = None
        if tr is not None:
            scored = tr.score_all(events)
            role_key = {"researcher": "researcher", "risk": "risk_desk",
                        "pm": "pm"}
            buckets: dict = {"researcher": [], "risk_desk": [],
                             "pm": []}
            for label, s in scored.items():
                key = role_key.get(s.get("role"))
                if key:
                    buckets[key].append({**s, "label": label})
            for key, rows in buckets.items():
                weights = tr.debate_weights(
                    {r["label"]: r["score"] for r in rows})
                rows.sort(key=lambda r: r["score"], reverse=True)
                for r in rows[:limit]:
                    r["debate_weight"] = weights.get(r["label"], 0.0)
                    leaderboards[key].append(_tjsonable(r))
            notes.append("leaderboards scored with trade-agents track_record "
                         "engine functions")
    elo_curves = _telo_curves(events) if events else {}
    brier = _tbrier_calibration(events) if events else {
        "bins": [], "observed": [], "n": []}
    debates, dmsg = _tdebates_from_approvals(approvals_ledger_path, limit)
    notes.append(dmsg)
    queue, qmsg = _tapproval_queue(approvals_ledger_path, limit)
    notes.append(qmsg)
    return {
        "leaderboards": leaderboards,
        "elo_curves": elo_curves,
        "brier": brier,
        "debates": debates,
        "approval_queue": queue,
        "track_record_path": path,
        "message": "; ".join(notes),
    }


# -- 4. Correlation network (MST) ------------------------------------------------

def _tpearson(xs: list, ys: list) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    den = math.sqrt(sum(a * a for a in dx) * sum(b * b for b in dy))
    if den <= 0:
        return 0.0
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(dx, dy)) / den))


def _tranks(xs: list) -> list:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def _tcorrelation_matrix(returns: list, method: str) -> list:
    cols = [list(c) for c in zip(*returns)]
    if method == "spearman":
        cols = [_tranks(c) for c in cols]
    n = len(cols)
    out = [[0.0] * n for _ in range(n)]
    for i in range(n):
        out[i][i] = 1.0
        for j in range(i + 1, n):
            r = _tpearson(cols[i], cols[j])
            out[i][j] = out[j][i] = r
    return out


def _tcorr_distance(rho: float) -> float:
    rho = max(-1.0, min(1.0, rho))
    return math.sqrt(max(0.0, 2.0 * (1.0 - rho)))


def _tkruskal_mst(n: int, dist: list) -> list:
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    edges = sorted(((dist[i][j], i, j) for i in range(n)
                    for j in range(i + 1, n)))
    mst = []
    for _, i, j in edges:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj
            mst.append((i, j))
            if len(mst) == n - 1:
                break
    return mst


def _tsingle_linkage_clusters(n: int, mst: list, dist: list,
                              cut: float) -> list:
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i, j in mst:
        if dist[i][j] <= cut:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj
    comp = {}
    labels = []
    for i in range(n):
        r = find(i)
        comp.setdefault(r, len(comp))
        labels.append(comp[r])
    return labels


def _tfruchterman_reingold(n: int, edges: list, seed: int,
                           iterations: int = _TFR_ITERATIONS) -> list:
    """Seeded Fruchterman-Reingold layout, pure Python.

    Fixed iteration count and a ``random.Random(seed)`` start make the
    layout bit-deterministic for a given seed.  Coordinates are normalized
    to [-100, 100].
    """
    rng = random.Random(seed)
    pos = [(rng.uniform(-1, 1), rng.uniform(-1, 1)) for _ in range(n)]
    area, k = 4.0, math.sqrt(4.0 / max(n, 1))
    temp = 1.0
    adj = [[] for _ in range(n)]
    for i, j in edges:
        adj[i].append(j)
        adj[j].append(i)

    def fr(d: float) -> float:
        return k * k / max(d, 1e-9)

    def fa(d: float) -> float:
        return d * d / k

    for _ in range(iterations):
        disp = [[0.0, 0.0] for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                dx = pos[i][0] - pos[j][0]
                dy = pos[i][1] - pos[j][1]
                d = math.hypot(dx, dy) or 1e-9
                f = fr(d) / d
                disp[i][0] += dx * f
                disp[i][1] += dy * f
                disp[j][0] -= dx * f
                disp[j][1] -= dy * f
        for i, j in edges:
            dx = pos[i][0] - pos[j][0]
            dy = pos[i][1] - pos[j][1]
            d = math.hypot(dx, dy) or 1e-9
            f = fa(d) / d
            disp[i][0] -= dx * f
            disp[i][1] -= dy * f
            disp[j][0] += dx * f
            disp[j][1] += dy * f
        for i in range(n):
            d = math.hypot(disp[i][0], disp[i][1]) or 1e-9
            step = min(d, temp)
            pos[i] = (pos[i][0] + disp[i][0] / d * step,
                      pos[i][1] + disp[i][1] / d * step)
            pos[i] = (max(-2.0, min(2.0, pos[i][0])),
                      max(-2.0, min(2.0, pos[i][1])))
        temp *= 0.96
    return [(x * 50.0, y * 50.0) for x, y in pos]


def _tdemo_network_series(symbols: list, n: int, seed: int) -> dict:
    rng = random.Random(seed)
    n_blocks = max(1, (len(symbols) + 2) // 3)
    factors = [[rng.gauss(0, 0.012) for _ in range(n)]
               for _ in range(n_blocks)]
    out = {}
    for i, s in enumerate(symbols):
        f = factors[i % n_blocks]
        px, series = 100.0, []
        for t in range(n):
            px *= 1.0 + 0.0003 + 0.7 * f[t] + rng.gauss(0, 0.006)
            series.append(px)
        out[s] = series
    return out


def _tfetch_network_bars(symbols: list, source: str, days: int) -> dict:
    if source == "demo":
        return _tdemo_network_series(symbols, max(days, 60), _TDEMO_SEED)
    if source == "yfinance":
        _trequire("trade-data-equities", "trade_data_equities")
        from trade_data_equities.providers.yfinance import YFinanceProvider
        from trade_data_equities import EquitiesDataClient
        client = EquitiesDataClient(YFinanceProvider())
        out = {}
        for s in symbols:
            bars = client.get_daily_bars(s, days=days)
            closes = [float(b["close"] if isinstance(b, dict) else b.close)
                      for b in bars]
            if len(closes) >= 30:
                out[s] = closes
        missing = [s for s in symbols if s not in out]
        if missing:
            raise ValueError(f"no usable bars for {', '.join(missing)}")
        return out
    raise ValueError("source must be 'yfinance' or 'demo'")


def _toverlay_extract(name: str, value):
    snap = _tsnapshot_input(value)
    if snap is None:
        return None
    if name == "regime":
        h = snap.get("hysteresis") or {}
        return {"source": "trade-regime",
                "schema_version": snap.get("schema_version"),
                "conviction": snap.get("conviction"),
                "composite_raw": snap.get("composite_raw"),
                "exposure_scale": snap.get("exposure_scale"),
                "hysteresis_state": h.get("state"),
                "hysteresis_reason": h.get("reason"),
                "missing": snap.get("missing", [])}
    if name == "breadth":
        return {"source": "trade-breadth",
                "schema_version": snap.get("schema_version"),
                "regime": snap.get("regime"),
                "regime_score": snap.get("regime_score"),
                "fragility": snap.get("fragility")}
    if name == "macro":
        return {"source": "trade-macro",
                "schema_version": snap.get("schema_version"),
                "regime": snap.get("regime"),
                "z_score": snap.get("z_score"),
                "ratio_vs_200dma": snap.get("ratio_vs_200dma")}
    return None


def run_network_job(
    symbols=None,
    source="yfinance",
    days=252,
    method="pearson",
    seed=7,
    breadth=None,
    macro=None,
    regime=None,
) -> dict:
    """Correlation-network job: correlation -> MST -> clusters -> layout.

    Pipeline (all stdlib, deterministic given ``seed``): daily returns per
    symbol (common length, >= 30 obs); sample correlation (Pearson, or
    Spearman = Pearson on ranks); distance ``d = sqrt(2(1-ρ))``; minimum
    spanning tree via Kruskal; clusters = single-linkage via the MST,
    cutting edges longer than 1.0 (ρ < 0.5 — arbitrary documented choice);
    seeded Fruchterman-Reingold layout (300 fixed iterations).

    Node size driver: annualized realized volatility.  ``breadth`` /
    ``macro`` / ``regime`` accept snapshot dicts (or JSON paths) conforming
    to their ``schema_version`` contracts.
    """
    if method not in ("pearson", "spearman"):
        raise ValueError("method must be 'pearson' or 'spearman'")
    days = int(days)
    if days < 30:
        raise ValueError("need >= 30 days")
    seed = int(seed)
    syms = [str(s).strip().upper() for s in (symbols or []) if str(s).strip()]
    demo = not syms
    if demo:
        syms = list(_TDEMO_UNIVERSE)
        series = _tdemo_network_series(syms, days, seed)
    else:
        if len(syms) < 3:
            raise ValueError("need at least 3 symbols for a network")
        if len(set(syms)) != len(syms):
            raise ValueError("duplicate symbols")
        series = _tfetch_network_bars(syms, source, days)
        syms = sorted(series)
    m = min(len(c) for c in series.values())
    closes = {s: series[s][-m:] for s in syms}
    rets = [[closes[s][i] / closes[s][i - 1] - 1.0 for s in syms]
            for i in range(1, m)]
    # Correlation matrix: reuse this package's canonical run_correlation_job
    # (trade-eda) on the real path — it raises RuntimeError when the engine
    # is missing, in which case the stdlib path above stands.  Demo/bare
    # mode keeps the built-in Pearson/Spearman.  The MST, clusters, and
    # layout are always computed here.
    corr_source = "stdlib"
    n_obs = len(rets)
    corr = _tcorrelation_matrix(rets, method)
    if not demo:
        try:
            bar_dicts = {s: [{"close": c} for c in closes[s]] for s in syms}
            rep = run_correlation_job(list(syms), bar_dicts, method=method,
                                      lookback=days)
            rep_syms = list(rep["symbols"])
            order = [rep_syms.index(s) for s in syms]
            mat = rep["correlation"]["matrix"]
            corr = [[float(mat[i][j]) for j in order] for i in order]
            corr_source = "trade-eda"
            n_obs = int(rep["n_obs"])
        except (RuntimeError, ValueError):
            pass  # engine missing or bars too short: stdlib path above
    n = len(syms)
    dist = [[_tcorr_distance(corr[i][j]) for j in range(n)] for i in range(n)]
    mst = _tkruskal_mst(n, dist)
    clusters = _tsingle_linkage_clusters(n, mst, dist, _TMST_CUT)
    vols = []
    for j in range(n):
        col = [rets[i][j] for i in range(len(rets))]
        mu = sum(col) / len(col)
        var = sum((x - mu) ** 2 for x in col) / max(len(col) - 1, 1)
        vols.append(math.sqrt(max(var, 0.0)) * math.sqrt(252.0))
    layout = _tfruchterman_reingold(n, mst, seed)
    nodes = [{"id": i, "symbol": s, "x": _tround(x, 2), "y": _tround(y, 2),
              "vol": _tround(v, 4), "cluster": c}
             for i, (s, (x, y), v, c)
             in enumerate(zip(syms, layout, vols, clusters))]
    edges = [{"a": i, "b": j, "weight": _tround(corr[i][j], 4),
              "distance": _tround(dist[i][j], 4)} for i, j in mst]
    comp: dict = {}
    for i, c in enumerate(clusters):
        comp.setdefault(c, []).append(syms[i])
    cluster_list = [{"id": c, "members": sorted(m)} for c, m in
                    sorted(comp.items())]
    return _tjsonable({
        "nodes": nodes,
        "edges": edges,
        "symbols": syms,
        "correlation": [[_tround(v, 4) for v in row] for row in corr],
        "clusters": cluster_list,
        "regime": _toverlay_extract("regime", regime),
        "breadth": _toverlay_extract("breadth", breadth),
        "macro": _toverlay_extract("macro", macro),
        "params": {"source": source, "days": days, "method": method,
                   "seed": seed, "n_obs": n_obs,
                   "correlation_source": corr_source,
                   "mst_cut_distance": _TMST_CUT,
                   "mst_cut_note": ("single-linkage cut at d=1.0 "
                                    "(rho>=0.5 kept); arbitrary choice, "
                                    "shown so clusters are not mistaken "
                                    "for discovered structure"),
                   "layout": (f"seeded Fruchterman-Reingold, "
                              f"{_TFR_ITERATIONS} iterations, deterministic "
                              f"given seed"),
                   "demo": demo},
    })


# -- 5. Risk monitor ----------------------------------------------------------

def _tdemo_risk_positions():
    rng = random.Random(_TDEMO_SEED)
    syms = ["SPY", "QQQ", "AAPL", "MSFT", "TSLA"]
    positions = []
    for i, s in enumerate(syms):
        qty = (i + 1) * 10 * (1 if i % 2 == 0 else -1)
        px = round(100 + rng.uniform(-30, 80), 2)
        positions.append({"symbol": s, "qty": float(qty), "price": px})
    return positions, 100_000.0


def _tledg_positions(db: sqlite3.Connection):
    """Net positions from fills; mark = last fill price per symbol.

    The ledger carries no live price feed, so the latest fill price is the
    mark (documented approximation — stale the moment the book trades).
    Equity = latest equity_snapshot when present, else None (fractions
    then come back null rather than fabricated).
    """
    fills = [dict(r) for r in db.execute(
        "SELECT symbol, side, quantity, price, filled_at FROM fills "
        "ORDER BY filled_at")]
    qty: dict = {}
    mark: dict = {}
    for fl in fills:
        sym = str(fl.get("symbol") or "").upper()
        q = float(fl.get("quantity") or 0.0)
        if str(fl.get("side") or "").lower() == "buy":
            qty[sym] = qty.get(sym, 0.0) + q
        else:
            qty[sym] = qty.get(sym, 0.0) - q
        mark[sym] = float(fl.get("price") or 0.0)
    positions = [{"symbol": s, "qty": q, "price": mark[s]}
                 for s, q in sorted(qty.items()) if abs(q) > 1e-12]
    equity = None
    if "equity_snapshots" in _ttables(db):
        row = db.execute("SELECT equity FROM equity_snapshots "
                         "ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            equity = float(row[0])
    return positions, equity


def _texposures(positions: list, equity) -> dict:
    """Net/gross exposure, beta-adjusted delta, Herfindahl.

    Beta approximation, stated honestly: the paper ledger carries no beta
    model, so β = 1.0 is assumed for every name and the beta-adjusted net
    delta equals the raw net delta.  It is reported as a separate field so
    a real beta feed can replace the assumption without a signature change.
    """
    per = []
    for p in positions:
        v = p["qty"] * p["price"]
        per.append({"symbol": p["symbol"], "qty": _tround(p["qty"], 4),
                    "price": _tround(p["price"], 4),
                    "value": _tround(v, 2), "beta": 1.0,
                    "beta_adj_value": _tround(v * 1.0, 2)})
    net = sum(p["qty"] * p["price"] for p in positions)
    gross = sum(abs(p["qty"] * p["price"]) for p in positions)
    weights = ([abs(p["qty"] * p["price"]) / gross for p in positions]
               if gross > 0 else [])
    herfindahl = sum(w * w for w in weights)
    ordered = sorted(zip([p["symbol"] for p in positions], weights),
                     key=lambda kv: kv[1], reverse=True)
    top = ordered[0] if ordered else (None, 0.0)

    def frac(x):
        return _tround(x / equity, 6) if equity else None

    return {
        "n_positions": len(per),
        "per_symbol": per,
        "net_delta_dollars": _tround(net, 2),
        "net_delta_dollars_beta_adj": _tround(net, 2),
        "beta_assumption": ("beta=1.0 for every name (ledger carries no beta "
                            "model); beta-adjusted delta equals net delta"),
        "gross_dollars": _tround(gross, 2),
        "net_frac": frac(net),
        "gross_frac": frac(gross),
        "herfindahl": _tround(herfindahl, 6),
        "largest_position": {"symbol": top[0],
                             "weight": _tround(top[1], 4)},
        "equity": _tround(equity, 2) if equity else None,
    }


def _tvol_regime(db, vol_days: int) -> dict:
    """Trailing 21-day annualized realized-vol timeline (equity based)."""
    if db is None or "equity_snapshots" not in _ttables(db):
        return {"as_of": [], "vol": [], "window": 21,
                "note": "no equity_snapshots — vol-regime unavailable"}
    rows = [dict(r) for r in db.execute(
        "SELECT at, equity FROM equity_snapshots ORDER BY at")]
    rows = rows[-max(vol_days + 21, 2):]
    if len(rows) < 23:
        return {"as_of": [], "vol": [], "window": 21,
                "note": f"only {len(rows)} snapshots (< 23 needed)"}
    eq = [float(r["equity"]) for r in rows]
    rets = [math.log(eq[i] / eq[i - 1]) for i in range(1, len(eq))
            if eq[i - 1] > 0 and eq[i] > 0]
    as_of, vols = [], []
    for i in range(21, len(rets) + 1):
        w = rets[i - 21:i]
        mu = sum(w) / len(w)
        var = sum((x - mu) ** 2 for x in w) / (len(w) - 1)
        vols.append(_tround(math.sqrt(var) * math.sqrt(252.0), 6))
        as_of.append(str(rows[i]["at"]))
    tail = max(vol_days, 1)
    return {"as_of": as_of[-tail:], "vol": vols[-tail:], "window": 21,
            "annualized": True,
            "note": "trailing 21d realized vol of equity, annualized"}


def _tvolforecast_block(value):
    """Optional trade-volforecast overlay.

    Accepts the ``to_agent_vol_report`` shape (``realized_vol_21d`` plus
    ``garch``/``har``/``ewma`` forecast lists), leniently.
    """
    snap = _tsnapshot_input(value)
    if snap is None:
        return None
    block = {"source": snap.get("source", "trade-volforecast"),
             "realized_vol_21d": snap.get("realized_vol_21d")}
    for k in ("garch", "har", "ewma"):
        v = snap.get(k)
        if isinstance(v, list):
            block[k] = [_tround(x, 6) if isinstance(x, (int, float)) else x
                        for x in v]
        elif isinstance(v, dict):
            block[k] = _tjsonable(v)
    return block


def _tkill_switch(hedge_state_path) -> dict:
    """Kill-switch status from a persisted trade-hedge LoopState.

    ``trade-hedge`` persists its ``LoopState`` via ``state_to_json``
    between scheduled runs; the conventional location is env
    ``TRADE_HEDGE_STATE`` else ``./trade-hedge-state.json``.  Absent ->
    ``"unknown"`` (never assumed safe, never assumed halted).
    """
    path = hedge_state_path
    if not path:
        env = os.environ.get("TRADE_HEDGE_STATE")
        path = env if env else "trade-hedge-state.json"
    p = Path(str(path)).expanduser()
    if not p.exists():
        return {"status": "unknown", "state_path": None,
                "note": ("no trade-hedge state file found "
                         "(TRADE_HEDGE_STATE or ./trade-hedge-state.json)")}
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "unknown", "state_path": str(p),
                "note": f"unreadable state file: {exc}"}
    halts = int(state.get("consecutive_halts", 0) or 0)
    return {"status": "halted" if halts > 0 else "active",
            "consecutive_halts": halts,
            "cycles_run": state.get("cycles_run"),
            "last_cycle_ts": state.get("last_cycle_ts"),
            "state_path": str(p)}


def _tregime_gauge(value):
    snap = _tsnapshot_input(value)
    if snap is None:
        return None
    h = snap.get("hysteresis") or {}
    return {"source": "trade-regime",
            "schema_version": snap.get("schema_version"),
            "conviction": snap.get("conviction"),
            "composite_raw": snap.get("composite_raw"),
            "exposure_scale": snap.get("exposure_scale"),
            "hysteresis_state": h.get("state"),
            "hysteresis_reason": h.get("reason"),
            "prior_conviction": h.get("prior_conviction")}


def run_risk_monitor_job(
    ledger_path=None,
    hedge_state_path=None,
    regime=None,
    vol_days=63,
) -> dict:
    """Risk monitor: exposures, vol regime, kill-switch, conviction gauge.

    Exposures come from ledger fills (net positions, mark = last fill
    price — documented approximation); beta-adjusted delta assumes β=1.0
    per name (the ledger carries no beta model — stated in the payload).
    The vol-regime timeline is trailing 21-day annualized realized vol of
    the equity snapshots; an optional trade-volforecast snapshot adds its
    forecast block (supplied via the ``TRADE_VOLFORECAST_SNAPSHOT`` env var
    — a path to, or inline JSON of, a ``to_agent_vol_report`` dict — since
    the canonical signature carries no volforecast parameter).  Kill-switch
    status reads a persisted trade-hedge ``LoopState`` (``halted`` when
    ``consecutive_halts > 0``), else ``"unknown"``.  The regime block
    carries the arbiter's conviction plus its hysteresis held/updated
    state and reason.
    """
    vol_days = max(int(vol_days or 0), 1)
    path = _tresolve_ledger_path(ledger_path)
    notes: list = []
    demo = False
    if path is None:
        positions, equity = _tdemo_risk_positions()
        vol = {"as_of": [], "vol": [], "window": 21,
               "note": "demo mode — no ledger, no vol timeline"}
        demo = True
        notes.append("DEMO — no paper ledger found; synthetic book shown")
        db = None
    else:
        db = _topen_ro(path)
        try:
            if "fills" not in _ttables(db):
                raise ValueError(f"ledger {path} has no fills table")
            positions, equity = _tledg_positions(db)
            vol = _tvol_regime(db, vol_days)
            notes.append(f"{len(positions)} net positions read read-only "
                         f"from {path}")
        finally:
            db.close()
    exposures = _texposures(positions, equity)
    kill = _tkill_switch(hedge_state_path)
    notes.append(f"kill-switch: {kill['status']}")
    gauge = _tregime_gauge(regime)
    if gauge is None:
        notes.append("no regime snapshot supplied — conviction gauge empty")
    vol_env = os.environ.get("TRADE_VOLFORECAST_SNAPSHOT")
    vol_block = None
    if vol_env:
        try:
            vol_block = _tvolforecast_block(
                json.loads(vol_env) if vol_env.lstrip().startswith("{")
                else vol_env)
        except (ValueError, json.JSONDecodeError) as exc:
            notes.append(f"volforecast snapshot unreadable: {exc}")
    return _tjsonable({
        "exposures": exposures,
        "vol_regime": vol,
        "volforecast": vol_block,
        "kill_switch": kill,
        "regime": gauge,
        "demo": demo,
        "ledger_path": path,
        "message": "; ".join(notes),
    })
