"""Research-lab jobs: one thin job per quant engine.

Each job talks to its engine of record directly (lazy import — a missing
engine raises a ``RuntimeError`` naming the ``pip install`` fix), takes
plain data in, and returns plain JSON-serializable data out.  The
``trade-suite`` meta-package delegates to these jobs, and both dashboards'
Research Lab tabs render their results, so a scripted run and a dashboard
run of the same job agree exactly.
"""

from __future__ import annotations

import math


def _require(dist: str, package: str):
    """Import ``package`` or raise a helpful error naming the install."""
    try:
        return __import__(package, fromlist=["*"])
    except ImportError as exc:
        raise RuntimeError(
            f"{dist} is not installed; install it with "
            f"`pip install git+https://github.com/crieck2010/{dist}.git`"
        ) from exc


def _clean_symbols(symbols: list[str]) -> list[str]:
    out = [s.strip().upper() for s in symbols if s and s.strip()]
    if not out:
        raise ValueError("at least one symbol is required")
    return out


def _closes_by_symbol(bars_by_symbol: dict[str, list]) -> dict[str, list[float]]:
    """``{symbol: closes}`` truncated to the common length, oldest-first."""
    closes = {}
    for s, bs in bars_by_symbol.items():
        key = (s or "").strip().upper()
        if not key:
            continue
        closes[key] = [float(b["close"] if isinstance(b, dict) else b.close)
                       for b in bs]
    if not closes:
        raise ValueError("at least one symbol with bars is required")
    m = min(len(c) for c in closes.values())
    return {s: c[-m:] for s, c in closes.items()}


# ---------------------------------------------------------------------------
# Pairs
# ---------------------------------------------------------------------------

def run_pairs_job(
    symbols: list[str],
    bars_by_symbol: dict[str, list],
    lookback: int = 252,
    max_pairs: int = 10,
) -> dict:
    """Screen a symbol universe for cointegrated pairs (trade-pairs)."""
    tp = _require("trade-pairs", "trade_pairs")
    closes = _closes_by_symbol(bars_by_symbol)
    syms = _clean_symbols(symbols)
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


# ---------------------------------------------------------------------------
# Order book
# ---------------------------------------------------------------------------

def run_orderbook_job(
    symbol: str = "DEMO",
    side: str = "buy",
    quantity: float = 100.0,
    order_type: str = "market",
    n_levels: int = 5,
    level_qty: float = 50.0,
) -> dict:
    """Simulate executing an order against a seeded book (trade-orderbook)."""
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")
    if order_type not in ("market", "limit"):
        raise ValueError("order_type must be 'market' or 'limit'")
    tob = _require("trade-orderbook", "trade_orderbook")
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


# ---------------------------------------------------------------------------
# Optimize
# ---------------------------------------------------------------------------

def run_optimize_job(
    symbols: list[str],
    bars_by_symbol: dict[str, list],
    method: str = "max_sharpe",
    max_weight: float = 1.0,
) -> dict:
    """Optimize a long-only portfolio (trade-optimize)."""
    topt = _require("trade-optimize", "trade_optimize")
    syms = _clean_symbols(symbols)
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


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------

def _corr_matrix(returns: list[list[float]]) -> list[list[float]]:
    """Sample correlation of per-asset return columns (t×n rows in)."""
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
    """Simulated portfolio VaR/CVaR over correlated GBM paths."""
    tmc = _require("trade-montecarlo", "trade_montecarlo")
    syms = _clean_symbols(symbols)
    closes = _closes_by_symbol({s: bars_by_symbol[s] for s in syms
                                if s in bars_by_symbol})
    syms = sorted(closes)
    R = [[closes[s][i] / closes[s][i - 1] - 1.0 for s in syms]
         for i in range(1, len(closes[syms[0]]))]
    t = len(R)
    mu = [sum(R[k][i] for k in range(t)) / t for i in range(len(syms))]
    sigma = [math.sqrt(sum((R[k][i] - mu[i]) ** 2 for k in range(t)) / (t - 1))
             for i in range(len(syms))]
    corr = _corr_matrix(R)
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


# ---------------------------------------------------------------------------
# Vol surface
# ---------------------------------------------------------------------------

def run_vol_surface_job(
    symbol: str = "SPY",
    spot: float | None = None,
    risk_free: float = 0.03,
) -> dict:
    """Fit an SVI volatility surface (trade-volsurface, demo quotes)."""
    tvs = _require("trade-volsurface", "trade_volsurface")
    try:
        from trade_volsurface.cli import demo_quotes
    except ImportError as exc:
        raise RuntimeError(
            "trade-volsurface is installed but its demo quotes are not "
            "importable"
        ) from exc
    quotes = demo_quotes()
    s0 = spot if spot is not None else 100.0
    # demo quotes are (T, log-moneyness k, iv); convert to strikes like the
    # engine's own CLI does before handing rows to the public adapter.
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


# ---------------------------------------------------------------------------
# Factors
# ---------------------------------------------------------------------------

def _month_end_closes(bars: list) -> list[tuple[str, float]]:
    """``[(yyyymm, last_close)]`` from oldest-first dict bars."""
    out: dict[str, float] = {}
    for b in bars:
        ts = b["timestamp"] if isinstance(b, dict) else b.timestamp
        out[str(ts)[:7].replace("-", "")] = float(
            b["close"] if isinstance(b, dict) else b.close)
    return sorted(out.items())


def run_factor_analysis_job(
    symbols: list[str],
    bars_by_symbol: dict[str, list],
    model: str = "ff5",
    n_months: int = 60,
) -> dict:
    """Fama-French time-series regressions + GRS test (trade-factors)."""
    tf = _require("trade-factors", "trade_factors")
    syms = _clean_symbols(symbols)
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


# ---------------------------------------------------------------------------
# Sentiment vs price
# ---------------------------------------------------------------------------

def run_sentiment_price_job(
    symbol: str,
    bars: list | None = None,
    sentiment_rows: list[dict] | None = None,
    days: int = 180,
    seed: int = 7,
) -> dict:
    """Sentiment-vs-price verdict bundle (trade-sentiment-vs-price).

    Pass ``sentiment_rows`` (archived trade-sentiment JSON rows) plus
    ``bars`` for real data; otherwise uses synthetic demo data with a
    planted 1-day sentiment lead.
    """
    tsvp = _require("trade-sentiment-vs-price", "trade_sentiment_vs_price")
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("a symbol is required")
    if sentiment_rows is not None:
        if not bars:
            raise ValueError("sentiment_rows need matching price bars")
        sent = tsvp.from_sentiment_scan(sentiment_rows)
        prices = tsvp.prices_from_dict_bars(
            [{"date": str(b["timestamp"] if isinstance(b, dict)
                          else b.timestamp)[:10],
              "close": b["close"] if isinstance(b, dict) else b.close}
             for b in bars])
    else:
        sent, prices = tsvp.demo_data(n_days=days, symbol=symbol, seed=seed)
    return tsvp.to_agent_report(symbol, sent, prices)


# ---------------------------------------------------------------------------
# Correlation / EDA
# ---------------------------------------------------------------------------

def run_correlation_job(
    symbols: list[str],
    bars_by_symbol: dict[str, list],
    method: str = "pearson",
    shrinkage: str = "ledoit_wolf",
    lookback: int = 252,
) -> dict:
    """Correlation/EDA report over a symbol universe (trade-eda).

    Full bar dicts are passed through (volume/timestamp feed the
    data-quality section); series are truncated to the common length,
    oldest-first, so ragged universes still work.
    """
    if method not in ("pearson", "spearman"):
        raise ValueError("method must be 'pearson' or 'spearman'")
    te = _require("trade-eda", "trade_eda")
    norm: dict[str, list] = {}
    for s, bs in bars_by_symbol.items():
        key = (s or "").strip().upper()
        if key:
            norm[key] = list(bs)
    syms = _clean_symbols(symbols)
    missing = [s for s in syms if s not in norm]
    if missing:
        raise ValueError(f"no bars for {', '.join(missing)}")
    if len(syms) < 2:
        raise ValueError("need at least two symbols")
    m = min(len(norm[s]) for s in syms)
    lb = min(lookback, m)
    if lb < 30:
        raise ValueError(f"need >= 30 bars per symbol, have {lb}")
    bars = {s: norm[s][-lb:] for s in syms}
    return te.analyze(bars, method=method, shrinkage=shrinkage)


# ---------------------------------------------------------------------------
# Breadth
# ---------------------------------------------------------------------------

def run_breadth_job(
    preset: str = "standard",
    seed: int = 7,
    n_days: int = 600,
    thrust_window: int = 10,
) -> dict:
    """Market-breadth regime snapshot over a seeded demo universe (trade-breadth)."""
    tb = _require("trade-breadth", "trade_breadth")
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
    # engine raises ValueError for an unknown preset
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


# ---------------------------------------------------------------------------
# Macro
# ---------------------------------------------------------------------------

def run_macro_job(
    preset: str = "standard",
    seed: int = 42,
    days: int = 600,
) -> dict:
    """Copper/gold macro regime snapshot (trade-macro, demo series)."""
    tm = _require("trade-macro", "trade_macro")
    seed = int(seed)
    days = int(days)
    if days < 250:
        raise ValueError(f"need >= 250 days for the 200DMA, have {days}")
    if days > 5000:
        raise ValueError(f"days capped at 5000, have {days}")
    series = tm.demo_series(seed=seed, days=days)
    snapshot = tm.snapshot(series["copper"], series["gold"],
                           preset=preset, source="synthetic")
    return {
        "source": "trade-macro",
        "preset": preset,
        "seed": seed,
        "days": days,
        "snapshot": snapshot,
    }


# ---------------------------------------------------------------------------
# Stream demo
# ---------------------------------------------------------------------------

def run_stream_demo_job(
    symbols: tuple = ("AAA", "BBB", "CCC"),
    seed: int = 7,
    n_ticks: int = 600,
) -> dict:
    """Bounded end-to-end streaming demo (trade-stream): demo feed -> bus."""
    ts = _require("trade-stream", "trade_stream")
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
    return {"source": "trade-stream", "demo": True, **result}


# ---------------------------------------------------------------------------
# Reconcile demo
# ---------------------------------------------------------------------------

def run_reconcile_demo_job() -> dict:
    """Paper-ledger vs broker reconcile against the read-only MCP mock (trade-paper).

    Mirrors ``trade-paper robinhood reconcile --demo``: the paper map is the
    deliberate-drift demo ledger, the broker side comes from the scripted
    in-memory MCP server (no network, no credentials).  Drift is reported,
    never corrected.
    """
    _require("trade-paper", "trade_paper")
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
