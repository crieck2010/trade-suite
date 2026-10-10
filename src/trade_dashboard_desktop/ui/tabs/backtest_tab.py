"""Backtest Lab tab: run a strategy, see the equity curve, metrics, trades."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import charts
from ..context import AppContext
from ..workers import Job
from .. import helpers as H


def _load_strategies(ctx: AppContext) -> tuple[list[dict], str]:
    try:
        return ctx.engine.list_strategies(), ""
    except RuntimeError as exc:
        return [], str(exc)


def build(parent: tk.Widget, ctx: AppContext) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=8)
    eng = ctx.engine

    # -- controls ---------------------------------------------------------
    controls = ttk.Frame(frame)
    controls.pack(fill="x", pady=(0, 8))

    strategies, strat_error = _load_strategies(ctx)
    names = [s["name"] for s in strategies]
    by_name = {s["name"]: s for s in strategies}

    ttk.Label(controls, text="Strategy:").pack(side="left")
    strat_var = tk.StringVar(value=names[0] if names else "")
    strat_box = ttk.Combobox(controls, textvariable=strat_var, values=names,
                             width=28, state="readonly" if names else "disabled")
    strat_box.pack(side="left", padx=(2, 4))

    sym_var = H.entry_row(controls, "Symbols:", "SPY", width=14)
    src_var = tk.StringVar(value="demo")
    src_row = ttk.Frame(controls)
    src_row.pack(side="left", padx=4)
    ttk.Label(src_row, text="Source:").pack(side="left")
    ttk.Combobox(src_row, textvariable=src_var, values=["demo", "equities"],
                 width=10, state="readonly").pack(side="left", padx=(2, 0))
    days_var = H.entry_row(controls, "Days:", "250", width=6)
    cash_var = H.entry_row(controls, "Cash $:", "100000", width=10)

    params_frame = ttk.Frame(frame)
    params_frame.pack(fill="x", pady=(0, 8))
    ttk.Label(params_frame, text="Params (k=v, k=v):").pack(side="left")
    params_var = tk.StringVar(value="entry=20, exit=10")
    ttk.Entry(params_frame, textvariable=params_var, width=50).pack(
        side="left", padx=(4, 8))
    run_btn = ttk.Button(params_frame, text="Run backtest")
    run_btn.pack(side="left")
    hint = ttk.Label(params_frame, text="", foreground="gray")
    hint.pack(side="left", padx=8)

    def _on_strategy_change(_event=None):
        desc = by_name.get(strat_var.get(), {})
        params = desc.get("parameters", {})
        hint.config(text="defaults: " + ", ".join(f"{k}={v}" for k, v in params.items()))
        if params and not params_var.get().strip():
            params_var.set(", ".join(f"{k}={v}" for k, v in params.items()))

    strat_box.bind("<<ComboboxSelected>>", _on_strategy_change)
    _on_strategy_change()

    # -- results ----------------------------------------------------------
    metrics_var = tk.StringVar(value="Pick a strategy and press Run backtest.")
    ttk.Label(frame, textvariable=metrics_var, font=("TkDefaultFont", 10, "bold"),
              wraplength=900, justify="left").pack(fill="x", pady=(0, 4))

    chart = tk.Canvas(frame, height=240, bg="white", highlightthickness=1,
                      highlightbackground="#cccccc")
    chart.pack(fill="x", pady=(0, 8))
    last_curve: list = []

    def _redraw(_event=None):
        if last_curve:
            charts.draw_equity_curve(chart, last_curve, chart.winfo_width(),
                                     chart.winfo_height())

    chart.bind("<Configure>", _redraw)

    ttk.Label(frame, text="Trades").pack(anchor="w")
    trades = H.make_tree(frame, [("Symbol", 80), ("Entry", 120), ("Exit", 120),
                                 ("Qty", 70), ("Entry $", 90), ("Exit $", 90),
                                 ("P&L $", 90), ("Return %", 80)], height=8)

    if strat_error:
        metrics_var.set(f"Strategy engine unavailable: {strat_error}")

    # -- job wiring -------------------------------------------------------
    def on_done(result: dict) -> None:
        m = result["metrics"]
        metrics_var.set(
            f"{result['strategy']} on {', '.join(result['symbols'])}  |  "
            f"final equity ${result['final_equity']:,.2f}  |  "
            f"total return {m.get('total_return', 0):+.1%}  |  "
            f"Sharpe {m.get('sharpe_ratio', 0):.2f}  |  "
            f"max DD {m.get('max_drawdown', 0):.1%}  |  "
            f"{len(result['trades'])} round-trip trades"
        )
        last_curve.clear()
        last_curve.extend(result["equity_curve"])
        _redraw()
        H.set_tree_rows(trades, [
            (t["symbol"], t["entry_time"][:10], (t["exit_time"] or "")[:10],
             t["quantity"], f"{t['entry_price']:.2f}", f"{t['exit_price']:.2f}",
             f"{t['pnl']:.2f}", f"{t['return_pct']:.2%}")
            for t in result["trades"]
        ])
        ctx.status(f"Backtest done: {result['strategy']} "
                   f"final ${result['final_equity']:,.0f}")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        metrics_var.set(f"Backtest failed: {error.splitlines()[0]}")
        ctx.status("Backtest failed")
        run_btn.config(state="normal")

    def run() -> None:
        if not strat_var.get():
            metrics_var.set("No strategy available (install trade-strategies).")
            return
        try:
            symbols = H.parse_symbols(sym_var.get())
            if not symbols:
                raise ValueError("enter at least one symbol")
            days = int(days_var.get())
            cash = float(cash_var.get())
        except ValueError as exc:
            metrics_var.set(f"Bad input: {exc}")
            return
        run_btn.config(state="disabled")
        metrics_var.set("Running backtest…")
        ctx.status("Backtest running in background…")

        def target():
            bars = ctx.data.get_bars(symbols[0], source=src_var.get(), days=days)
            return eng.run_backtest_job(
                strat_var.get(), symbols, H.parse_params(params_var.get()),
                bars, initial_cash=cash)

        ctx.submit(Job("backtest", target, on_done=on_done, on_error=on_error))

    run_btn.config(command=run)
    return frame
