"""Network tab: STATIC parity render of the correlation MST.

Renders the node positions / edges / clusters returned by
``engine.run_network_job`` onto a canvas: nodes colored by cluster and
sized by annualized vol, edge width scaling with |correlation|.  This is
deliberately static — the topology and the seeded Fruchterman-Reingold
layout are computed by the engine; tkinter does no pan/zoom physics and
no hover tooltips.  Exploration is menu-driven instead: a cluster
listbox plus a node selector whose top correlations are shown below
(static parity — see docs/PARITY.md and the web flagship for the
interactive SVG).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import charts
from .. import helpers as H
from ..context import AppContext
from ..workers import Job

CW, CH = 760, 520


def build(parent: tk.Widget, ctx: AppContext) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=8)
    eng = ctx.engine

    static_var = tk.StringVar(
        value="Static render of the engine-computed MST layout — no pan/zoom "
              "or hover tooltips on desktop (see the web dashboard for the "
              "interactive graph).")
    ttk.Label(frame, textvariable=static_var, wraplength=1000,
              foreground="gray", justify="left").pack(anchor="w", pady=(0, 4))

    banner_var = tk.StringVar(value="")
    ttk.Label(frame, textvariable=banner_var,
              font=("TkDefaultFont", 10, "bold"),
              foreground="#8d6e00", background="#fff8e1").pack(
        fill="x", pady=(0, 6))

    # -- controls ---------------------------------------------------------
    row = ttk.Frame(frame)
    row.pack(fill="x", pady=(0, 6))
    sym_var = H.entry_row(row, "Symbols (blank = demo universe):", "", width=30)
    src_var = tk.StringVar(value="demo")
    f = ttk.Frame(row)
    f.pack(side="left", padx=4)
    ttk.Label(f, text="Source:").pack(side="left")
    ttk.Combobox(f, textvariable=src_var, values=["demo", "yfinance"],
                 width=10, state="readonly").pack(side="left", padx=(2, 0))
    meth_var = tk.StringVar(value="pearson")
    g = ttk.Frame(row)
    g.pack(side="left", padx=4)
    ttk.Label(g, text="Method:").pack(side="left")
    ttk.Combobox(g, textvariable=meth_var,
                 values=["pearson", "spearman"], width=10,
                 state="readonly").pack(side="left", padx=(2, 0))
    seed_var = H.entry_row(row, "Seed:", "7", width=6)
    run_btn = ttk.Button(row, text="Build network")
    run_btn.pack(side="left", padx=8)
    summary_var = tk.StringVar(value="")
    ttk.Label(row, textvariable=summary_var,
              font=("TkDefaultFont", 10, "bold")).pack(side="left", padx=12)

    # -- body -------------------------------------------------------------
    body = ttk.PanedWindow(frame, orient="horizontal")
    body.pack(fill="both", expand=True)

    left = ttk.Frame(body)
    canvas = tk.Canvas(left, width=CW, height=CH, background="white",
                       highlightthickness=1, highlightbackground="#cccccc")
    canvas.pack(fill="both", expand=True)
    body.add(left, weight=3)

    right = ttk.Frame(body, padding=(8, 0, 0, 0))
    ttk.Label(right, text="Clusters", font=("TkDefaultFont", 10, "bold")
              ).pack(anchor="w")
    cluster_list = tk.Listbox(right, height=8, width=40, exportselection=False)
    cluster_list.pack(fill="x", pady=(0, 8))
    ttk.Label(right, text="Node", font=("TkDefaultFont", 10, "bold")
              ).pack(anchor="w")
    node_var = tk.StringVar(value="")
    node_combo = ttk.Combobox(right, textvariable=node_var, width=34,
                              state="readonly")
    node_combo.pack(fill="x", pady=(0, 8))
    ttk.Label(right, text="Top correlations for node",
              font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
    corr_tree = H.make_tree(right, [("Symbol", 80), ("ρ", 80)], height=8)

    last: dict = {}

    def refresh_corr(_event=None) -> None:
        sym = node_var.get()
        nodes = last.get("nodes") or []
        corr = last.get("correlation") or []
        idx = next((i for i, nd in enumerate(nodes)
                    if nd.get("symbol") == sym), None)
        if idx is None:
            return
        pairs = sorted(
            ((nodes[j]["symbol"], corr[idx][j]) for j in range(len(nodes))
             if j != idx),
            key=lambda kv: -abs(kv[1]))[:10]
        H.set_tree_rows(corr_tree,
                        [(s, f"{v:.4f}") for s, v in pairs])

    node_combo.bind("<<ComboboxSelected>>", refresh_corr)

    def on_done(result: dict) -> None:
        last.clear()
        last.update(result)
        charts.draw_network(canvas, result, CW, CH)
        cluster_list.delete(0, "end")
        for cl in result.get("clusters", []):
            cluster_list.insert(
                "end",
                f"cluster {cl['id']}: {', '.join(cl['members'])}")
        nodes = result.get("nodes") or []
        names = [nd["symbol"] for nd in nodes]
        node_combo.config(values=names)
        if names:
            node_var.set(names[0])
            refresh_corr()
        params = result.get("params", {})
        banner_var.set("DEMO — seeded synthetic series; not real data."
                       if params.get("demo") else "")
        summary_var.set(
            f"{len(nodes)} nodes · {len(result.get('edges', []))} MST edges · "
            f"{len(result.get('clusters', []))} clusters · "
            f"corr via {params.get('correlation_source')} · "
            f"n_obs={params.get('n_obs')}")
        ctx.status("Network built")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        summary_var.set(f"Build failed: {error.splitlines()[0]}")
        ctx.status("Network build failed")
        run_btn.config(state="normal")

    def run() -> None:
        try:
            seed = int(seed_var.get() or "7")
        except ValueError:
            summary_var.set("Bad input: seed must be an integer")
            return
        symbols = H.parse_symbols(sym_var.get())
        run_btn.config(state="disabled")
        summary_var.set("Building network…")
        ctx.submit(Job("network", eng.run_network_job,
                       kwargs={"symbols": symbols or None,
                               "source": src_var.get(),
                               "method": meth_var.get(),
                               "seed": seed},
                       on_done=on_done, on_error=on_error))

    run_btn.config(command=run)
    return frame
