"""Agents tab: leaderboards, Elo curves, Brier calibration, debates.

Runs ``engine.run_agent_activity_job`` (shared web engine when installed,
local fallback otherwise) through the background ``Job`` infrastructure.

Parity note: the web flagship renders in-cell Elo sparklines; tkinter has
no in-cell SVG, so desktop shows a numeric rating per agent plus one
matplotlib-style line chart per *selected* agent (simplified parity —
see docs/PARITY.md).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import charts
from .. import helpers as H
from ..context import AppContext
from ..workers import Job

CW, CH = 880, 260


def _sub(notebook: ttk.Notebook, title: str) -> ttk.Frame:
    tab = ttk.Frame(notebook, padding=6)
    notebook.add(tab, text=title)
    return tab


def build(parent: tk.Widget, ctx: AppContext) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=8)
    eng = ctx.engine

    row = ttk.Frame(frame)
    row.pack(fill="x", pady=(0, 6))
    lim_var = H.entry_row(row, "Limit:", "50", width=6)
    run_btn = ttk.Button(row, text="Load agent activity")
    run_btn.pack(side="left", padx=8)
    summary_var = tk.StringVar(value="")
    ttk.Label(row, textvariable=summary_var,
              font=("TkDefaultFont", 10, "bold")).pack(side="left", padx=12)

    note = ttk.Notebook(frame)
    note.pack(fill="both", expand=True)

    # -- leaderboards -----------------------------------------------------
    lb_tab = _sub(note, "Leaderboards")
    lb_trees: dict[str, ttk.Treeview] = {}
    for key, title in [("researcher", "Researchers"),
                       ("risk_desk", "Risk desk"), ("pm", "Portfolio managers")]:
        ttk.Label(lb_tab, text=title,
                  font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(4, 0))
        lb_trees[key] = H.make_tree(
            lb_tab, [("Agent", 180), ("Score", 90), ("Debate weight", 110)],
            height=5)

    # -- Elo --------------------------------------------------------------
    elo_tab = _sub(note, "Elo")
    elo_row = ttk.Frame(elo_tab)
    elo_row.pack(fill="x", pady=(0, 6))
    ttk.Label(elo_row, text="Agent:").pack(side="left")
    agent_var = tk.StringVar(value="")
    agent_combo = ttk.Combobox(elo_row, textvariable=agent_var, width=30,
                               state="readonly")
    agent_combo.pack(side="left", padx=(4, 0))
    elo_note_var = tk.StringVar(
        value="Dashboard-side Elo vs a fixed 1500-rated market (approximation "
              "for sparklines; not a trade-agents engine number).")
    ttk.Label(elo_tab, textvariable=elo_note_var, wraplength=900,
              foreground="gray", justify="left").pack(anchor="w", pady=(0, 4))
    elo_canvas = tk.Canvas(elo_tab, width=CW, height=CH, background="white",
                           highlightthickness=1,
                           highlightbackground="#cccccc")
    elo_canvas.pack(fill="both", expand=True)
    elo_curves: dict = {}

    def draw_elo(_event=None) -> None:
        name = agent_var.get()
        curve = elo_curves.get(name) or []
        elo_canvas.delete("all")
        ratings = [p["rating"] for p in curve]
        pts = charts.line_points(ratings, CW, CH)
        if len(pts) < 2:
            elo_canvas.create_text(CW // 2, CH // 2, text="no Elo data",
                                   fill="gray")
            return
        elo_canvas.create_line(*[c for p in pts for c in p],
                               fill=charts.LINE_COLOR, width=2)
        elo_canvas.create_text(10, 12, anchor="w", fill="gray",
                               text=f"{name}: {ratings[-1]:.1f} "
                                    f"(n={len(ratings)} games)")

    agent_combo.bind("<<ComboboxSelected>>", draw_elo)

    # -- Brier ------------------------------------------------------------
    brier_tab = _sub(note, "Brier calibration")
    brier_canvas = tk.Canvas(brier_tab, width=CW, height=CH,
                             background="white", highlightthickness=1,
                             highlightbackground="#cccccc")
    brier_canvas.pack(fill="both", expand=True)
    ttk.Label(brier_tab, wraplength=900, justify="left", foreground="gray",
              text="Observed exceedance rate vs the risk desk's forecast "
                   "P(max drawdown > threshold), binned. The dashed diagonal "
                   "is perfect calibration.").pack(anchor="w", pady=(4, 0))

    # -- debates ----------------------------------------------------------
    deb_tab = _sub(note, "Debate timeline")
    deb_tree = H.make_tree(deb_tab, [("Idea", 140), ("Time", 170),
                                     ("Strategy", 130), ("Verdict", 70),
                                     ("Conviction", 90), ("Rounds", 60),
                                     ("Approval", 90)])

    # -- approval queue ---------------------------------------------------
    ap_tab = _sub(note, "Approval queue")
    ap_tree = H.make_tree(ap_tab, [("ID", 60), ("Strategy", 160),
                                   ("Symbols", 220), ("Score", 90),
                                   ("Created", 170)])

    def on_done(result: dict) -> None:
        lbs = result.get("leaderboards", {})
        n_total = 0
        for key, tree in lb_trees.items():
            rows = lbs.get(key, [])
            n_total += len(rows)
            H.set_tree_rows(tree, [
                (r.get("label"), f"{r.get('score', 0):.4f}",
                 f"{r.get('debate_weight', 0):.3f}") for r in rows
            ])
        elo_curves.clear()
        elo_curves.update(result.get("elo_curves", {}))
        names = sorted(elo_curves)
        agent_combo.config(values=names)
        if names:
            agent_var.set(names[0])
        draw_elo()
        charts.draw_calibration(brier_canvas, result.get("brier", {}), CW, CH)
        H.set_tree_rows(deb_tree, [
            (d.get("idea_id"), d.get("ts"), d.get("strategy"),
             d.get("verdict"), d.get("conviction"), d.get("n_rounds"),
             d.get("approval_status")) for d in result.get("debates", [])
        ])
        H.set_tree_rows(ap_tree, [
            (q.get("id"), q.get("strategy"), q.get("symbols"),
             q.get("score"), q.get("created_at"))
            for q in result.get("approval_queue", [])
        ])
        summary_var.set(
            f"{n_total} agents · {len(elo_curves)} Elo curves · "
            f"{len(result.get('debates', []))} debates · "
            f"{len(result.get('approval_queue', []))} pending approvals")
        ctx.status(f"Agent activity loaded: {result.get('message', '')[:80]}")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        summary_var.set(f"Load failed: {error.splitlines()[0]}")
        ctx.status("Agent activity failed")
        run_btn.config(state="normal")

    def run() -> None:
        try:
            limit = int(lim_var.get() or "50")
        except ValueError:
            summary_var.set("Bad input: limit must be an integer")
            return
        run_btn.config(state="disabled")
        summary_var.set("Loading…")
        ctx.submit(Job("agents", eng.run_agent_activity_job,
                       kwargs={"limit": limit},
                       on_done=on_done, on_error=on_error))

    run_btn.config(command=run)
    return frame
