"""Agent Desk tab: run the hedge-fund research desk, review output."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..context import AppContext
from ..workers import Job
from .. import helpers as H


def build(parent: tk.Widget, ctx: AppContext) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=8)
    eng = ctx.engine

    # -- controls ---------------------------------------------------------
    controls = ttk.Frame(frame)
    controls.pack(fill="x", pady=(0, 8))
    sym_var = H.entry_row(controls, "Symbols:", "SPY, AAPL", width=24)
    eq_var = H.entry_row(controls, "Equity $:", "100000", width=10)
    src_var = tk.StringVar(value="demo")
    src_row = ttk.Frame(controls)
    src_row.pack(side="left", padx=4)
    ttk.Label(src_row, text="Source:").pack(side="left")
    ttk.Combobox(src_row, textvariable=src_var, values=["demo", "equities"],
                 width=10, state="readonly").pack(side="left", padx=(2, 0))
    days_var = H.entry_row(controls, "Days:", "250", width=6)
    run_btn = ttk.Button(controls, text="Run desk")
    run_btn.pack(side="left", padx=8)
    summary_var = tk.StringVar(value="Run the desk to generate research briefs.")
    ttk.Label(frame, textvariable=summary_var, font=("TkDefaultFont", 10, "bold"),
              wraplength=900, justify="left").pack(fill="x", pady=(0, 4))

    # -- result views -----------------------------------------------------
    inner = ttk.Notebook(frame)
    inner.pack(fill="both", expand=True)

    ideas_tree = H.make_tree(_tab(inner, "Ideas"),
                             [("Agent", 170), ("Symbol", 70), ("Dir", 60),
                              ("Strategy", 170), ("Score", 70),
                              ("Conviction", 80), ("Sharpe", 70), ("Max DD", 70)])
    alloc_tree = H.make_tree(_tab(inner, "Allocations"),
                             [("Symbol", 70), ("Dir", 60), ("Weight", 70),
                              ("Qty", 80), ("Price $", 90)])
    orders_tree = H.make_tree(_tab(inner, "Approved orders"),
                              [("Symbol", 70), ("Side", 60), ("Qty", 80),
                               ("Price $", 90), ("Type", 90)])
    vetoes_tree = H.make_tree(_tab(inner, "Vetoes"),
                              [("Symbol", 70), ("Limit", 170), ("Reason", 400)])
    notes_text = H.scroll_text(_tab(inner, "Notes"), height=14)

    # -- job wiring -------------------------------------------------------
    def on_done(report: dict) -> None:
        n_ideas = sum(len(b["ideas"]) for b in report["briefs"])
        summary_var.set(
            f"Desk report {report['as_of'][:16]}Z  |  {len(report['briefs'])} briefs, "
            f"{n_ideas} ideas, {len(report['allocations'])} allocations, "
            f"{len(report['approved_orders'])} approved, {len(report['vetoes'])} vetoed"
        )
        H.set_tree_rows(ideas_tree, [
            (b["agent"], i.get("symbol"), i.get("direction", "").upper(),
             i.get("strategy"), f"{i.get('score', 0):.2f}",
             f"{i.get('conviction', 0):.2f}",
             f"{i.get('metrics', {}).get('sharpe_ratio', 0):.2f}",
             f"{i.get('metrics', {}).get('max_drawdown', 0):.1%}")
            for b in report["briefs"] for i in b["ideas"]
        ])
        H.set_tree_rows(alloc_tree, [
            (a["idea"].get("symbol"), a["idea"].get("direction", "").upper(),
             f"{a.get('weight', 0):.1%}", a.get("quantity"),
             f"{a.get('price') or 0:.2f}")
            for a in report["allocations"]
        ])
        H.set_tree_rows(orders_tree, [
            (o.get("symbol"), o.get("side"), o.get("quantity"),
             f"{o.get('price') or 0:.2f}", o.get("order_type"))
            for o in report["approved_orders"]
        ])
        H.set_tree_rows(vetoes_tree, [
            (v["order"].get("symbol"), v.get("limit"), v.get("reason"))
            for v in report["vetoes"]
        ])
        notes_text.delete("1.0", "end")
        notes_text.insert("1.0", report.get("advisor_notes") or "(no advisor notes)")
        ctx.status(f"Desk done: {n_ideas} ideas, "
                   f"{len(report['approved_orders'])} approved")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        summary_var.set(f"Desk run failed: {error.splitlines()[0]}")
        ctx.status("Desk run failed")
        run_btn.config(state="normal")

    def run() -> None:
        try:
            symbols = H.parse_symbols(sym_var.get())
            if not symbols:
                raise ValueError("enter at least one symbol")
            equity = float(eq_var.get())
            days = int(days_var.get())
        except ValueError as exc:
            summary_var.set(f"Bad input: {exc}")
            return
        run_btn.config(state="disabled")
        summary_var.set("Desk running (researchers → portfolio manager → risk)…")
        ctx.status("Agent desk running in background…")

        def target():
            bars = {s: ctx.data.get_bars(s, source=src_var.get(), days=days)
                    for s in symbols}
            return eng.run_desk_job(symbols, bars, equity=equity)

        ctx.submit(Job("desk", target, on_done=on_done, on_error=on_error))

    run_btn.config(command=run)
    return frame


def _tab(notebook: ttk.Notebook, title: str) -> ttk.Frame:
    tab = ttk.Frame(notebook, padding=6)
    notebook.add(tab, text=title)
    return tab
