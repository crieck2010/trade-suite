"""Trades tab: filterable paper-ledger blotter + CSV export.

Runs ``engine.run_trades_job`` (shared web engine when installed, local
fallback otherwise) through the background ``Job`` infrastructure.  Export
writes ``engine.trades_to_csv`` bytes via a Save-As dialog.  When the
service reports ``demo: True`` the rows are synthetic plumbing data and a
DEMO banner is shown.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk

from .. import charts
from .. import helpers as H
from ..context import AppContext
from ..workers import Job


def build(parent: tk.Widget, ctx: AppContext) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=8)
    eng = ctx.engine

    # -- DEMO banner ------------------------------------------------------
    banner_var = tk.StringVar(value="")
    banner = ttk.Label(frame, textvariable=banner_var,
                       font=("TkDefaultFont", 10, "bold"),
                       foreground="#8d6e00", background="#fff8e1")
    banner.pack(fill="x", pady=(0, 6))

    # -- filter form ------------------------------------------------------
    row = ttk.Frame(frame)
    row.pack(fill="x", pady=(0, 6))
    df_var = H.entry_row(row, "From:", "", width=12)
    dt_var = H.entry_row(row, "To:", "", width=12)
    sym_var = H.entry_row(row, "Symbol:", "", width=10)
    side_var = tk.StringVar(value="")
    f = ttk.Frame(row)
    f.pack(side="left", padx=4)
    ttk.Label(f, text="Side:").pack(side="left")
    ttk.Combobox(f, textvariable=side_var, values=["", "buy", "sell"],
                 width=8, state="readonly").pack(side="left", padx=(2, 0))
    strat_var = H.entry_row(row, "Strategy:", "", width=14)
    agent_var = H.entry_row(row, "Agent:", "", width=12)
    oc_var = tk.StringVar(value="")
    g = ttk.Frame(row)
    g.pack(side="left", padx=4)
    ttk.Label(g, text="Outcome:").pack(side="left")
    ttk.Combobox(g, textvariable=oc_var,
                 values=["", "win", "loss", "open", "unknown"],
                 width=10, state="readonly").pack(side="left", padx=(2, 0))
    lim_var = H.entry_row(row, "Limit:", "500", width=6)

    btn_row = ttk.Frame(frame)
    btn_row.pack(fill="x", pady=(0, 6))
    run_btn = ttk.Button(btn_row, text="Run blotter")
    run_btn.pack(side="left")
    export_btn = ttk.Button(btn_row, text="Export CSV", state="disabled")
    export_btn.pack(side="left", padx=8)
    summary_var = tk.StringVar(value="")
    ttk.Label(btn_row, textvariable=summary_var,
              font=("TkDefaultFont", 10, "bold")).pack(side="left", padx=12)

    # -- blotter table ----------------------------------------------------
    tree = H.make_tree(frame, [("ID", 120), ("Symbol", 70), ("Side", 55),
                               ("Qty", 70), ("Filled", 70), ("Avg fill $", 85),
                               ("Commission", 80), ("Strategy", 140),
                               ("State", 80), ("Created", 170),
                               ("Realized P&L $", 100), ("Outcome", 80)])

    last_result: dict = {}

    def on_done(result: dict) -> None:
        last_result.clear()
        last_result.update(result)
        rows = result.get("trades", [])
        H.set_tree_rows(tree, [
            (r.get("id"), r.get("symbol"), r.get("side"), r.get("qty"),
             r.get("filled_qty"), r.get("avg_fill_price"),
             r.get("commission"), r.get("strategy"), r.get("state"),
             r.get("created_at"), r.get("realized_pnl"), r.get("outcome"))
            for r in rows
        ])
        if result.get("demo"):
            banner_var.set("DEMO — synthetic rows for plumbing tests only; "
                           "not real trades.")
        else:
            banner_var.set("")
        summary_var.set(
            f"{len(rows)} trades shown ({result.get('count', 0)} matched)")
        export_btn.config(state="normal")
        ctx.status(f"Blotter done: {result.get('count', 0)} trades")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        banner_var.set("")
        summary_var.set(f"Blotter failed: {error.splitlines()[0]}")
        ctx.status("Blotter failed")
        run_btn.config(state="normal")

    def run() -> None:
        try:
            limit = int(lim_var.get() or "500")
        except ValueError:
            summary_var.set("Bad input: limit must be an integer")
            return
        run_btn.config(state="disabled")
        summary_var.set("Loading blotter…")
        filters = {
            "date_from": df_var.get().strip() or None,
            "date_to": dt_var.get().strip() or None,
            "symbol": sym_var.get().strip() or None,
            "side": side_var.get().strip() or None,
            "strategy": strat_var.get().strip() or None,
            "agent": agent_var.get().strip() or None,
            "outcome": oc_var.get().strip() or None,
            "limit": limit,
        }
        ctx.submit(Job("trades", eng.run_trades_job, kwargs=filters,
                       on_done=on_done, on_error=on_error))

    def export() -> None:
        if not last_result:
            return
        csv_text = eng.trades_to_csv(last_result)
        path = filedialog.asksaveasfilename(
            parent=frame, title="Export trades as CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(csv_text)
        ctx.status(f"Trades exported to {path}")

    run_btn.config(command=run)
    export_btn.config(command=export)
    return frame
