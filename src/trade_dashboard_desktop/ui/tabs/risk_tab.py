"""Risk Review tab: build a limit stack, evaluate orders against it."""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from ..context import AppContext
from ..workers import Job
from .. import helpers as H

SAMPLE_ORDERS = """[
  {"symbol": "SPY", "side": "buy", "quantity": 100, "price": 580.0},
  {"symbol": "AAPL", "side": "buy", "quantity": 500, "price": 230.0}
]"""


def build(parent: tk.Widget, ctx: AppContext) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=8)
    eng = ctx.engine

    try:
        limits = eng.describe_limits()
        limit_error = ""
    except RuntimeError as exc:
        limits, limit_error = [], str(exc)
    by_name = {d["name"]: d for d in limits}

    top = ttk.PanedWindow(frame, orient="horizontal")
    top.pack(fill="both", expand=True)

    # -- available limits -------------------------------------------------
    left = ttk.Frame(top, padding=(0, 0, 8, 0))
    ttk.Label(left, text="Available limits").pack(anchor="w")
    avail = tk.Listbox(left, width=34, height=12, exportselection=False)
    for d in limits:
        avail.insert("end", d["name"])
    avail.pack(fill="x")
    ttk.Label(left, text="Params (k=v, k=v):").pack(anchor="w", pady=(6, 0))
    params_var = tk.StringVar()
    ttk.Entry(left, textvariable=params_var, width=34).pack(fill="x")
    desc_var = tk.StringVar(value="")
    ttk.Label(left, textvariable=desc_var, wraplength=260, foreground="gray",
              justify="left").pack(anchor="w", pady=4)
    top.add(left, weight=1)

    # -- active stack -----------------------------------------------------
    mid = ttk.Frame(top, padding=(0, 0, 8, 0))
    ttk.Label(mid, text="Active limit stack (evaluated top-down)").pack(anchor="w")
    stack = tk.Listbox(mid, width=40, height=12, exportselection=False)
    stack.pack(fill="x")
    stack_items: list[tuple[str, dict]] = []
    btns = ttk.Frame(mid)
    btns.pack(fill="x", pady=6)

    def refresh_desc(_event=None):
        sel = avail.curselection()
        if not sel:
            return
        d = by_name[avail.get(sel[0])]
        params_var.set(", ".join(f"{k}={v}"
                                 for k, v in (d.get("defaults") or {}).items()))
        desc_var.set(d.get("description", ""))

    avail.bind("<<ListboxSelect>>", refresh_desc)

    def add_limit():
        sel = avail.curselection()
        if not sel:
            return
        name = avail.get(sel[0])
        params = H.parse_params(params_var.get())
        stack_items.append((name, params))
        stack.insert("end", f"{name} {params}" if params else name)

    def remove_limit():
        sel = stack.curselection()
        if sel:
            stack_items.pop(sel[0])
            stack.delete(sel[0])

    ttk.Button(btns, text="Add →", command=add_limit).pack(side="left")
    ttk.Button(btns, text="Remove", command=remove_limit).pack(side="left", padx=4)
    top.add(mid, weight=1)

    # -- orders -----------------------------------------------------------
    right = ttk.Frame(top)
    ttk.Label(right, text="Orders (JSON list)").pack(anchor="w")
    orders_text = H.scroll_text(right, height=12, wrap="none")
    orders_text.insert("1.0", SAMPLE_ORDERS)
    eq_row = ttk.Frame(right)
    eq_row.pack(fill="x", pady=6)
    eq_var = H.entry_row(eq_row, "Equity $:", "100000", width=12)
    eval_btn = ttk.Button(eq_row, text="Evaluate orders")
    eval_btn.pack(side="left", padx=8)
    top.add(right, weight=2)

    # -- results ----------------------------------------------------------
    res_note = ttk.Notebook(frame)
    res_note.pack(fill="both", expand=True, pady=(8, 0))
    approved = H.make_tree(_tab(res_note, "Approved"),
                           [("Symbol", 80), ("Side", 60), ("Qty", 80),
                            ("Price $", 90)], height=6)
    vetoed = H.make_tree(_tab(res_note, "Vetoed"),
                         [("Symbol", 80), ("Limit", 200), ("Reason", 380)], height=6)
    verdict_var = tk.StringVar(value="")
    ttk.Label(frame, textvariable=verdict_var,
              font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(4, 0))

    if limit_error:
        verdict_var.set(f"Risk engine unavailable: {limit_error}")
    if limits:
        avail.selection_set(0)
        refresh_desc()

    # -- job wiring -------------------------------------------------------
    def on_done(result: dict) -> None:
        n_ok, n_no = len(result["approved"]), len(result["vetoed"])
        verdict_var.set(f"{n_ok} approved, {n_no} vetoed")
        H.set_tree_rows(approved, [
            (o.get("symbol"), o.get("side"), o.get("quantity"),
             f"{o.get('price') or 0:.2f}") for o in result["approved"]
        ])
        H.set_tree_rows(vetoed, [
            (v["order"].get("symbol"), v.get("limit"), v.get("reason"))
            for v in result["vetoed"]
        ])
        ctx.status(f"Risk review done: {n_ok} approved, {n_no} vetoed")
        eval_btn.config(state="normal")

    def on_error(error: str) -> None:
        verdict_var.set(f"Evaluation failed: {error.splitlines()[0]}")
        ctx.status("Risk evaluation failed")
        eval_btn.config(state="normal")

    def evaluate() -> None:
        try:
            orders = json.loads(orders_text.get("1.0", "end"))
            if not isinstance(orders, list):
                raise ValueError("orders JSON must be a list")
            equity = float(eq_var.get())
        except (ValueError, json.JSONDecodeError) as exc:
            verdict_var.set(f"Bad input: {exc}")
            return
        eval_btn.config(state="disabled")
        verdict_var.set("Evaluating…")
        stack_cfg = [[name, params] for name, params in stack_items]
        ctx.submit(Job("risk", eng.evaluate_orders_job,
                       args=(orders, stack_cfg or None, equity),
                       on_done=on_done, on_error=on_error))

    eval_btn.config(command=evaluate)
    return frame


def _tab(notebook: ttk.Notebook, title: str) -> ttk.Frame:
    tab = ttk.Frame(notebook, padding=6)
    notebook.add(tab, text=title)
    return tab
