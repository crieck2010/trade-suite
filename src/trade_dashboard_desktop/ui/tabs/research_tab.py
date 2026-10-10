"""Research Lab tab: ten quant-engine panels in one inner notebook.

Each panel runs its job through the existing background-job infrastructure
(`ctx.submit(Job(...))`); the engine services (shared web implementation
when installed, local fallback otherwise) do all the work and return plain
data, which the panels render as trees, metrics, or text. No engine math
lives in this file.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import helpers as H
from ..context import AppContext
from ..workers import Job


def _tab(notebook: ttk.Notebook, title: str) -> ttk.Frame:
    tab = ttk.Frame(notebook, padding=6)
    notebook.add(tab, text=title)
    return tab


def _controls(parent: tk.Widget) -> ttk.Frame:
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=(0, 8))
    return row


def _combo(row: ttk.Frame, label: str, var: tk.StringVar,
           values: list[str], width: int = 12) -> None:
    f = ttk.Frame(row)
    f.pack(side="left", padx=4)
    ttk.Label(f, text=label + ":").pack(side="left")
    ttk.Combobox(f, textvariable=var, values=values, width=width,
                 state="readonly").pack(side="left", padx=(2, 0))


def _run_block(frame: ttk.Frame, btn_text: str, status_text: str,
               summary_text: str = ""):
    """Shared run-button + status line wiring; returns (run_btn, summary_var)."""
    summary_var = tk.StringVar(value=summary_text)
    ttk.Label(frame, textvariable=summary_var, font=("TkDefaultFont", 10, "bold"),
              wraplength=900, justify="left").pack(fill="x", pady=(0, 4))
    return summary_var


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".")
    return str(v)


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

def _pairs_panel(parent: tk.Widget, ctx: AppContext) -> None:
    eng = ctx.engine
    row = _controls(parent)
    sym_var = H.entry_row(row, "Symbols:", "SPY, QQQ, IWM, DIA", width=26)
    lb_var = H.entry_row(row, "Lookback:", "252", width=8)
    run_btn = ttk.Button(row, text="Screen pairs")
    run_btn.pack(side="left", padx=8)
    summary_var = _run_block(parent, "", "", "Screen for cointegrated pairs.")
    tree = H.make_tree(parent, [("Pair", 130), ("Verdict", 110),
                                ("ADF stat", 90), ("Beta", 90),
                                ("Half-life bars", 110)])

    def on_done(r: dict) -> None:
        summary_var.set(
            f"{r['n_cointegrated']} cointegrated of {len(r['pairs'])} "
            f"candidates (lookback {r['lookback']}, {r['source']})")
        H.set_tree_rows(tree, [
            (f"{p['symbol_a']} / {p['symbol_b']}",
             "cointegrated" if p["cointegrated"] else "not",
             _fmt(p["adf"]["stat"]), _fmt(p["hedge_ratio"]),
             _fmt(p["half_life_bars"]))
            for p in r["pairs"]])
        ctx.status(f"Pairs screen done: {r['n_cointegrated']} cointegrated")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        summary_var.set(f"Pairs screen failed: {error.splitlines()[0]}")
        run_btn.config(state="normal")

    def run() -> None:
        try:
            symbols = H.parse_symbols(sym_var.get())
            if not symbols:
                raise ValueError("enter at least one symbol")
            lookback = int(lb_var.get())
        except ValueError as exc:
            summary_var.set(f"Bad input: {exc}")
            return
        run_btn.config(state="disabled")
        summary_var.set("Screening pairs…")

        def target():
            bars = {s: ctx.data.get_bars(s, days=300) for s in symbols}
            return eng.run_pairs_job(symbols, bars, lookback=lookback,
                                     max_pairs=10)

        ctx.submit(Job("research-pairs", target, on_done=on_done,
                       on_error=on_error))

    run_btn.config(command=run)


def _orderbook_panel(parent: tk.Widget, ctx: AppContext) -> None:
    eng = ctx.engine
    row = _controls(parent)
    side_var, type_var = tk.StringVar(value="buy"), tk.StringVar(value="market")
    _combo(row, "Side", side_var, ["buy", "sell"])
    qty_var = H.entry_row(row, "Qty:", "100", width=8)
    _combo(row, "Type", type_var, ["market", "limit"])
    run_btn = ttk.Button(row, text="Simulate")
    run_btn.pack(side="left", padx=8)
    summary_var = _run_block(parent, "", "", "Seeded 5-level book @ 100.00.")
    tree = H.make_tree(parent, [("Metric", 200), ("Value", 200)])

    def on_done(r: dict) -> None:
        summary_var.set(
            f"{r['side'].upper()} {r['quantity']} {r['order_type']} — "
            f"filled {r['filled_qty']:.0f}, slippage {r['slippage_bps']:.1f} bps")
        rows = [("Filled qty", r["filled_qty"]), ("Fill ratio", r["fill_ratio"]),
                ("Avg fill price", r["avg_fill_price"]),
                ("Slippage (bps)", r["slippage_bps"]), ("Fills", r["n_fills"])]
        feats = r.get("book_features") or {}
        rows += [(f"book.{k}", _fmt(v)) for k, v in sorted(feats.items())]
        H.set_tree_rows(tree, [(k, _fmt(v)) for k, v in rows])
        ctx.status("Order-book simulation done")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        summary_var.set(f"Simulation failed: {error.splitlines()[0]}")
        run_btn.config(state="normal")

    def run() -> None:
        try:
            qty = float(qty_var.get())
        except ValueError as exc:
            summary_var.set(f"Bad input: {exc}")
            return
        run_btn.config(state="disabled")
        summary_var.set("Simulating…")

        def target():
            return eng.run_orderbook_job(side=side_var.get(), quantity=qty,
                                         order_type=type_var.get())

        ctx.submit(Job("research-orderbook", target, on_done=on_done,
                       on_error=on_error))

    run_btn.config(command=run)


def _optimize_panel(parent: tk.Widget, ctx: AppContext) -> None:
    eng = ctx.engine
    row = _controls(parent)
    sym_var = H.entry_row(row, "Symbols:", "SPY, QQQ, IWM", width=26)
    method_var = tk.StringVar(value="max_sharpe")
    _combo(row, "Method", method_var,
           ["max_sharpe", "min_variance", "risk_parity", "equal_weight"], 14)
    run_btn = ttk.Button(row, text="Optimize")
    run_btn.pack(side="left", padx=8)
    summary_var = _run_block(parent, "", "", "Long-only Markowitz.")
    tree = H.make_tree(parent, [("Symbol", 90), ("Weight", 90)])

    def on_done(r: dict) -> None:
        summary_var.set(
            f"{r['method']}: expected return {r['expected_return']:.4f}, "
            f"volatility {r['volatility']:.4f}, Sharpe {r['sharpe']:.3f}")
        H.set_tree_rows(tree, [(s, _fmt(w))
                               for s, w in sorted(r["weights"].items())])
        ctx.status(f"Optimize done: Sharpe {r['sharpe']:.3f}")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        summary_var.set(f"Optimize failed: {error.splitlines()[0]}")
        run_btn.config(state="normal")

    def run() -> None:
        symbols = H.parse_symbols(sym_var.get())
        if not symbols:
            summary_var.set("Bad input: enter at least one symbol")
            return
        run_btn.config(state="disabled")
        summary_var.set("Optimizing…")

        def target():
            bars = {s: ctx.data.get_bars(s, days=250) for s in symbols}
            return eng.run_optimize_job(symbols, bars,
                                        method=method_var.get())

        ctx.submit(Job("research-optimize", target, on_done=on_done,
                       on_error=on_error))

    run_btn.config(command=run)


def _montecarlo_panel(parent: tk.Widget, ctx: AppContext) -> None:
    eng = ctx.engine
    row = _controls(parent)
    sym_var = H.entry_row(row, "Symbols:", "SPY, QQQ", width=22)
    paths_var = H.entry_row(row, "Paths:", "2000", width=8)
    eq_var = H.entry_row(row, "Equity $:", "100000", width=10)
    run_btn = ttk.Button(row, text="Simulate")
    run_btn.pack(side="left", padx=8)
    summary_var = _run_block(parent, "", "", "Correlated-GBM VaR.")
    tree = H.make_tree(parent, [("Metric", 200), ("Value", 200)])

    def on_done(r: dict) -> None:
        summary_var.set(
            f"{r['n_paths']} paths × {r['n_steps']} steps — "
            f"VaR ${r['var']:,.0f}, CVaR ${r['cvar']:,.0f}, "
            f"P(profit) {r['prob_profit']:.1%}")
        H.set_tree_rows(tree, [
            ("VaR", f"${r['var']:,.2f}"), ("CVaR", f"${r['cvar']:,.2f}"),
            ("Mean P&L", f"${r['mean_pnl']:,.2f}"),
            ("Median P&L", f"${r['median_pnl']:,.2f}"),
            ("P(profit)", f"{r['prob_profit']:.1%}"),
            ("Paths", r["n_paths"]), ("Steps", r["n_steps"]),
            ("Seed", r["seed"])])
        ctx.status("Monte Carlo done")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        summary_var.set(f"Simulation failed: {error.splitlines()[0]}")
        run_btn.config(state="normal")

    def run() -> None:
        try:
            symbols = H.parse_symbols(sym_var.get())
            if not symbols:
                raise ValueError("enter at least one symbol")
            paths, equity = int(paths_var.get()), float(eq_var.get())
        except ValueError as exc:
            summary_var.set(f"Bad input: {exc}")
            return
        run_btn.config(state="disabled")
        summary_var.set("Simulating…")

        def target():
            bars = {s: ctx.data.get_bars(s, days=250) for s in symbols}
            return eng.run_montecarlo_job(symbols, bars, equity=equity,
                                          n_paths=paths, n_steps=252, seed=7)

        ctx.submit(Job("research-montecarlo", target, on_done=on_done,
                       on_error=on_error))

    run_btn.config(command=run)


def _volsurface_panel(parent: tk.Widget, ctx: AppContext) -> None:
    eng = ctx.engine
    row = _controls(parent)
    sym_var = H.entry_row(row, "Symbol:", "SPY", width=10)
    run_btn = ttk.Button(row, text="Fit surface")
    run_btn.pack(side="left", padx=8)
    summary_var = _run_block(parent, "", "", "SVI fits, demo quotes.")
    tree = H.make_tree(parent, [("Expiry T", 90), ("a", 90), ("b", 90),
                                ("rho", 90), ("m", 90), ("sigma", 90)])

    def on_done(r: dict) -> None:
        summary_var.set(
            f"{r['n_quotes']} quotes, {len(r['svi_fits'])} SVI fits "
            f"(spot {r['spot']}, r {r['risk_free']})")
        H.set_tree_rows(tree, [
            (T, _fmt(f["a"]), _fmt(f["b"]), _fmt(f["rho"]),
             _fmt(f["m"]), _fmt(f["sigma"]))
            for T, f in sorted(r["svi_fits"].items(),
                               key=lambda kv: float(kv[0]))])
        ctx.status("Vol surface fit done")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        summary_var.set(f"Fit failed: {error.splitlines()[0]}")
        run_btn.config(state="normal")

    def run() -> None:
        symbol = sym_var.get().strip().upper()
        if not symbol:
            summary_var.set("Bad input: enter a symbol")
            return
        run_btn.config(state="disabled")
        summary_var.set("Fitting…")

        def target():
            return eng.run_vol_surface_job(symbol=symbol)

        ctx.submit(Job("research-volsurface", target, on_done=on_done,
                       on_error=on_error))

    run_btn.config(command=run)


def _factors_panel(parent: tk.Widget, ctx: AppContext) -> None:
    eng = ctx.engine
    row = _controls(parent)
    sym_var = H.entry_row(row, "Symbols:", "SPY, QQQ", width=22)
    model_var = tk.StringVar(value="ff5")
    _combo(row, "Model", model_var, ["ff5", "ff3", "carhart"], 10)
    run_btn = ttk.Button(row, text="Analyze")
    run_btn.pack(side="left", padx=8)
    summary_var = _run_block(parent, "", "", "Fama-French regressions.")
    tree = H.make_tree(parent, [("Symbol", 90), ("Alpha", 90),
                                ("Alpha t", 90), ("Alpha p", 90),
                                ("R²", 90), ("Sig 5%", 70)])

    def on_done(r: dict) -> None:
        g = r.get("grs") or {}
        p = g.get("pvalue", 1.0)
        summary_var.set(
            f"{r['model'].upper()} · {r['n_months']} months · "
            f"GRS F={g.get('F', 0):.2f}, p={p:.4f} — "
            f"{'reject joint zero-alpha' if p < 0.05 else 'cannot reject joint zero-alpha'}")
        H.set_tree_rows(tree, [
            (s, _fmt(a["alpha"]), _fmt(a["alpha_t"]), _fmt(a["alpha_p"]),
             _fmt(a["rsquared"]), "yes" if a["alpha_p"] < 0.05 else "no")
            for s, a in sorted(r["assets"].items())])
        ctx.status("Factor analysis done")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        summary_var.set(f"Analysis failed: {error.splitlines()[0]}")
        run_btn.config(state="normal")

    def run() -> None:
        symbols = H.parse_symbols(sym_var.get())
        if not symbols:
            summary_var.set("Bad input: enter at least one symbol")
            return
        run_btn.config(state="disabled")
        summary_var.set("Running regressions…")

        def target():
            bars = {s: ctx.data.get_bars(s, days=750) for s in symbols}
            return eng.run_factor_analysis_job(symbols, bars,
                                               model=model_var.get(),
                                               n_months=60)

        ctx.submit(Job("research-factors", target, on_done=on_done,
                       on_error=on_error))

    run_btn.config(command=run)


def _sentiment_panel(parent: tk.Widget, ctx: AppContext) -> None:
    eng = ctx.engine
    row = _controls(parent)
    sym_var = H.entry_row(row, "Symbol:", "SPY", width=10)
    run_btn = ttk.Button(row, text="Analyze")
    run_btn.pack(side="left", padx=8)
    summary_var = _run_block(parent, "", "",
                             "Sentiment-vs-price, demo data (1-day lead planted).")
    text = H.scroll_text(parent, height=16)

    def on_done(r: dict) -> None:
        ll, ic, es, se = r["lead_lag"], r["ic"], r["event_study"], r["signal_eval"]
        summary_var.set(
            f"{r['symbol']} ({r['n_days']}d): {ll['verdict']} "
            f"(lag {ll['best_lag']}, r={ll['best_r']:+.3f}) · "
            f"IC={ic['ic']:+.3f} (p={ic['pvalue']:.3f})")
        lines = [
            f"Lead/lag:   {ll['verdict']} — best lag {ll['best_lag']}d, "
            f"r={ll['best_r']:+.4f}, p={ll['best_pvalue']:.2e}",
            f"IC:         {ic['ic']:+.4f} (rank {ic['rank_ic']:+.4f}), "
            f"t={ic['tstat']:+.2f}, p={ic['pvalue']:.2e}",
            f"Event study: {es['n_events']} events, mean CAR "
            f"{es['mean_car']:+.4f}, p={es['pvalue']:.3f}",
            f"Signal eval: {se['n_trades']} trades, hit rate "
            f"{se['hit_rate']:.0%}, total return {se['total_return']:+.2%}, "
            f"p={se['pvalue']:.3f}",
            f"Contemporaneous r: {r['contemporaneous_r']:+.4f}",
        ]
        text.delete("1.0", "end")
        text.insert("1.0", "\n".join(lines))
        ctx.status("Sentiment analysis done")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        summary_var.set(f"Analysis failed: {error.splitlines()[0]}")
        run_btn.config(state="normal")

    def run() -> None:
        symbol = sym_var.get().strip().upper()
        if not symbol:
            summary_var.set("Bad input: enter a symbol")
            return
        run_btn.config(state="disabled")
        summary_var.set("Analyzing…")

        def target():
            return eng.run_sentiment_price_job(symbol, days=180)

        ctx.submit(Job("research-sentiment", target, on_done=on_done,
                       on_error=on_error))

    run_btn.config(command=run)


def _correlation_panel(parent: tk.Widget, ctx: AppContext) -> None:
    eng = ctx.engine
    row = _controls(parent)
    sym_var = H.entry_row(row, "Symbols:", "SPY, QQQ, IWM, DIA", width=26)
    method_var = tk.StringVar(value="pearson")
    _combo(row, "Method", method_var, ["pearson", "spearman"], width=10)
    shrink_var = tk.StringVar(value="ledoit_wolf")
    _combo(row, "Shrinkage", shrink_var, ["ledoit_wolf", "sample"], width=12)
    lb_var = H.entry_row(row, "Lookback:", "252", width=8)
    run_btn = ttk.Button(row, text="Analyze")
    run_btn.pack(side="left", padx=8)
    summary_var = _run_block(
        parent, "", "",
        "Correlation matrix, shrunk covariance, per-asset stats, data quality.")
    text = H.scroll_text(parent, height=16)

    def on_done(r: dict) -> None:
        div = r["diversification"]
        hi = div["max_pairwise_corr"]
        summary_var.set(
            f"{len(r['symbols'])} symbols, {r['n_obs']} obs "
            f"({r['correlation']['method']}): mean r={div['mean_pairwise_corr']:+.3f}, "
            f"max {hi['a']}/{hi['b']}={hi['value']:+.3f}, "
            f"effective N={div['effective_n_equal_weight']:.1f}, "
            f"LW delta={r['covariance']['shrinkage_delta']:.3f}")
        syms = r["symbols"]
        mat = r["correlation"]["matrix"]
        lines = ["Correlation matrix:"]
        lines.append("        " + " ".join(f"{s:>8s}" for s in syms))
        for s, rowv in zip(syms, mat):
            lines.append(f"{s:>8s} " + " ".join(f"{v:>8.2f}" for v in rowv))
        lines.append("")
        lines.append("Per-asset stats (ann. vol, skew, ex. kurt, JB):")
        for s, d in r["describe"].items():
            lines.append(
                f"  {s:>6s} vol={d['vol_annualized']:.1%} skew={d['skew']:+.2f} "
                f"kurt={d['kurtosis_excess']:+.2f} JB={d['jarque_bera']:.1f}")
        lines.append("")
        dirty = {s: q for s, q in r["quality"].items() if not q["clean"]}
        if dirty:
            lines.append("Data-quality flags:")
            for s, q in dirty.items():
                flags = ", ".join(
                    f"{k}={v}" for k, v in q.items()
                    if k not in ("n_bars", "first", "last", "clean") and v)
                lines.append(f"  {s}: {flags}")
        else:
            lines.append("Data quality: all clean")
        text.delete("1.0", "end")
        text.insert("1.0", "\n".join(lines))
        ctx.status("Correlation analysis done")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        summary_var.set(f"Analysis failed: {error.splitlines()[0]}")
        run_btn.config(state="normal")

    def run() -> None:
        try:
            symbols = H.parse_symbols(sym_var.get())
            if len(symbols) < 2:
                raise ValueError("enter at least two symbols")
            lookback = int(lb_var.get())
        except ValueError as exc:
            summary_var.set(f"Bad input: {exc}")
            return
        run_btn.config(state="disabled")
        summary_var.set("Analyzing…")

        def target():
            bars = {s: ctx.data.get_bars(s, days=365) for s in symbols}
            return eng.run_correlation_job(
                symbols, bars, method=method_var.get(),
                shrinkage=shrink_var.get(), lookback=lookback)

        ctx.submit(Job("research-correlation", target, on_done=on_done,
                       on_error=on_error))

    run_btn.config(command=run)


def _breadth_panel(parent: tk.Widget, ctx: AppContext) -> None:
    eng = ctx.engine
    row = _controls(parent)
    preset_var = tk.StringVar(value="standard")
    _combo(row, "Preset", preset_var, ["standard", "strict", "loose"], 10)
    days_var = H.entry_row(row, "Days (DEMO):", "600", width=8)
    run_btn = ttk.Button(row, text="Run breadth (DEMO)")
    run_btn.pack(side="left", padx=8)
    summary_var = _run_block(
        parent, "", "",
        "Market-breadth regime snapshot, seeded demo universe (60 symbols).")
    frag_row = ttk.Frame(parent)
    frag_row.pack(fill="x", pady=(0, 6))
    ttk.Label(frag_row, text="Fragility:").pack(side="left")
    frag_bar = ttk.Progressbar(frag_row, length=240, maximum=1.0,
                               mode="determinate")
    frag_bar.pack(side="left", padx=6)
    frag_var = tk.StringVar(value="n/a")
    ttk.Label(frag_row, textvariable=frag_var).pack(side="left")
    tree = H.make_tree(parent, [("Metric", 220), ("Value", 220)])

    def on_done(r: dict) -> None:
        s = r["snapshot"]
        regime = s["regime"]
        summary_var.set(
            f"Regime {regime} (score {s['regime_score']:+.2f}, {s['date']}, "
            f"{r['n_symbols']} symbols, preset {r['preset']})")
        frag_bar.config(value=s["fragility"])
        frag_var.set(f"{s['fragility']:.2%}")
        ind = s["indicators"]
        rows = [
            ("Advancers / decliners",
             f"{ind['advancers']} / {ind['decliners']}"),
            ("A/D ratio", _fmt(ind["ad_ratio"])),
            ("A/D line", _fmt(ind["ad_line"])),
            ("% above 50dma", _fmt(ind["pct_above_50dma"])),
            ("McClellan oscillator", _fmt(ind["mcclellan_oscillator"])),
            ("McClellan summation", _fmt(ind["mcclellan_summation"])),
            ("EW/CW index ratio", _fmt(ind["ew_cw_ratio"])),
            ("Up/down volume ratio", _fmt(ind["up_down_volume_ratio"])),
        ]
        for t in s.get("thrusts_recent", []):
            rows.append((f"Thrust {t['date']} ({t['type']})",
                         f"magnitude {t['magnitude']:+.1f}, "
                         f"{t['pct_above_50dma']:.1f}% above 50dma"))
        if not s.get("thrusts_recent"):
            rows.append(("Thrusts (window)", "none fired"))
        for w in s.get("warnings", []):
            rows.append(("Warning", w))
        H.set_tree_rows(tree, [(k, _fmt(v)) for k, v in rows])
        ctx.status(f"Breadth snapshot done: {regime}")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        summary_var.set(f"Breadth failed: {error.splitlines()[0]}")
        run_btn.config(state="normal")

    def run() -> None:
        try:
            days = int(days_var.get())
            if days <= 0:
                raise ValueError("days must be positive")
        except ValueError as exc:
            summary_var.set(f"Bad input: {exc}")
            return
        run_btn.config(state="disabled")
        summary_var.set("Computing breadth snapshot…")

        def target():
            return eng.run_breadth_job(preset=preset_var.get(), seed=7,
                                       n_days=days)

        ctx.submit(Job("research-breadth", target, on_done=on_done,
                       on_error=on_error))

    run_btn.config(command=run)


def _macro_panel(parent: tk.Widget, ctx: AppContext) -> None:
    eng = ctx.engine
    row = _controls(parent)
    preset_var = tk.StringVar(value="standard")
    _combo(row, "Preset", preset_var, ["sensitive", "standard", "calm"], 10)
    days_var = H.entry_row(row, "Days (DEMO):", "600", width=8)
    run_btn = ttk.Button(row, text="Run macro (DEMO)")
    run_btn.pack(side="left", padx=8)
    summary_var = _run_block(
        parent, "", "",
        "Copper/gold macro regime snapshot, seeded demo series.")
    tree = H.make_tree(parent, [("Metric", 220), ("Value", 220)])

    def on_done(r: dict) -> None:
        s = r["snapshot"]
        regime = s["regime"]
        alert = s["transition_alert"]
        summary_var.set(
            f"Regime {regime} · z-score {s['z_score']:+.2f} "
            f"({'TRANSITION ALERT' if alert else 'no transition'}, {s['date']})")
        rows = [
            ("Indicator", s["indicator"]),
            ("Copper/gold ratio", _fmt(s["ratio"])),
            ("Ratio vs 200DMA", _fmt(s["ratio_vs_200dma"])),
            ("21d ROC", _fmt(s["roc_21d"])),
            ("Z-score", _fmt(s["z_score"])),
            ("Transition alert", "YES" if alert else "no"),
            ("Transition", s["transition"] or "none"),
        ]
        H.set_tree_rows(tree, [(k, _fmt(v)) for k, v in rows])
        ctx.status(f"Macro snapshot done: {regime}")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        summary_var.set(f"Macro failed: {error.splitlines()[0]}")
        run_btn.config(state="normal")

    def run() -> None:
        try:
            days = int(days_var.get())
            if days <= 0:
                raise ValueError("days must be positive")
        except ValueError as exc:
            summary_var.set(f"Bad input: {exc}")
            return
        run_btn.config(state="disabled")
        summary_var.set("Computing macro snapshot…")

        def target():
            return eng.run_macro_job(preset=preset_var.get(), seed=42,
                                     days=days)

        ctx.submit(Job("research-macro", target, on_done=on_done,
                       on_error=on_error))

    run_btn.config(command=run)


def build(parent: tk.Widget, ctx: AppContext) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=8)
    inner = ttk.Notebook(frame)
    inner.pack(fill="both", expand=True)
    _pairs_panel(_tab(inner, "Pairs"), ctx)
    _orderbook_panel(_tab(inner, "Order book"), ctx)
    _optimize_panel(_tab(inner, "Optimize"), ctx)
    _montecarlo_panel(_tab(inner, "Monte Carlo"), ctx)
    _volsurface_panel(_tab(inner, "Vol surface"), ctx)
    _factors_panel(_tab(inner, "Factors"), ctx)
    _sentiment_panel(_tab(inner, "Sentiment"), ctx)
    _correlation_panel(_tab(inner, "Correlations"), ctx)
    _breadth_panel(_tab(inner, "Breadth"), ctx)
    _macro_panel(_tab(inner, "Macro"), ctx)
    return frame
