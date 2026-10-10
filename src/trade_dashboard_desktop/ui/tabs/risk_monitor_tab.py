"""Risk Monitor tab: exposures, vol regime, kill-switch, conviction gauge.

Runs ``engine.run_risk_monitor_job`` (shared web engine when installed,
local fallback otherwise) through the background ``Job`` infrastructure.

Exposures come from ledger fills (mark = last fill price — a documented
approximation); beta-adjusted delta assumes β=1.0 per name because the
paper ledger carries no beta model.  The vol-regime timeline is trailing
21-day annualized realized vol of the equity snapshots.  Kill-switch
status reads a persisted trade-hedge LoopState (``halted`` when
consecutive_halts > 0, else ``"unknown"`` — never assumed safe).  The
conviction gauge renders the trade-regime arbiter's conviction plus its
hysteresis held/updated state when a regime snapshot is supplied.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import charts
from .. import helpers as H
from ..context import AppContext
from ..workers import Job

CW, CH = 880, 220


def build(parent: tk.Widget, ctx: AppContext) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=8)
    eng = ctx.engine

    banner_var = tk.StringVar(value="")
    ttk.Label(frame, textvariable=banner_var,
              font=("TkDefaultFont", 10, "bold"),
              foreground="#8d6e00", background="#fff8e1").pack(
        fill="x", pady=(0, 6))

    # -- controls ---------------------------------------------------------
    row = ttk.Frame(frame)
    row.pack(fill="x", pady=(0, 6))
    vol_var = H.entry_row(row, "Vol days:", "63", width=6)
    run_btn = ttk.Button(row, text="Refresh risk monitor")
    run_btn.pack(side="left", padx=8)
    summary_var = tk.StringVar(value="")
    ttk.Label(row, textvariable=summary_var,
              font=("TkDefaultFont", 10, "bold")).pack(side="left", padx=12)

    # -- kill-switch pill + headline stats ---------------------------------
    head = ttk.Frame(frame)
    head.pack(fill="x", pady=(0, 6))
    kill_var = tk.StringVar(value="kill-switch: —")
    kill_label = tk.Label(head, textvariable=kill_var,
                          font=("TkDefaultFont", 11, "bold"),
                          background="#e0e0e0", padx=10, pady=4)
    kill_label.pack(side="left")
    herf_var = tk.StringVar(value="Herfindahl: —")
    ttk.Label(head, textvariable=herf_var,
              font=("TkDefaultFont", 11)).pack(side="left", padx=16)
    net_var = tk.StringVar(value="Net: —")
    ttk.Label(head, textvariable=net_var,
              font=("TkDefaultFont", 11)).pack(side="left", padx=16)
    gross_var = tk.StringVar(value="Gross: —")
    ttk.Label(head, textvariable=gross_var,
              font=("TkDefaultFont", 11)).pack(side="left", padx=16)

    note = ttk.Notebook(frame)
    note.pack(fill="both", expand=True)

    def _sub(title: str) -> ttk.Frame:
        tab = ttk.Frame(note, padding=6)
        note.add(tab, text=title)
        return tab

    exp_tab = _sub("Exposures")
    exp_canvas = tk.Canvas(exp_tab, width=CW, height=CH, background="white",
                           highlightthickness=1,
                           highlightbackground="#cccccc")
    exp_canvas.pack(fill="both", expand=True)
    exp_tree = H.make_tree(exp_tab, [("Symbol", 80), ("Qty", 90),
                                     ("Price $", 90), ("Value $", 110),
                                     ("β-adj $", 110)], height=5)

    vol_tab = _sub("Vol regime")
    vol_canvas = tk.Canvas(vol_tab, width=CW, height=CH, background="white",
                           highlightthickness=1,
                           highlightbackground="#cccccc")
    vol_canvas.pack(fill="both", expand=True)
    vol_note_var = tk.StringVar(value="")
    ttk.Label(vol_tab, textvariable=vol_note_var, wraplength=900,
              foreground="gray", justify="left").pack(anchor="w", pady=(4, 0))

    gauge_tab = _sub("Conviction")
    gauge_canvas = tk.Canvas(gauge_tab, width=CW, height=CH,
                             background="white", highlightthickness=1,
                             highlightbackground="#cccccc")
    gauge_canvas.pack(fill="both", expand=True)
    hyst_var = tk.StringVar(value="")
    ttk.Label(gauge_tab, textvariable=hyst_var, wraplength=900,
              foreground="gray", justify="left").pack(anchor="w", pady=(4, 0))

    def _money(v) -> str:
        return "n/a" if v is None else f"${v:,.2f}"

    def on_done(result: dict) -> None:
        exp = result.get("exposures", {})
        kill = result.get("kill_switch", {})
        status = kill.get("status", "unknown")
        kill_var.set(f"kill-switch: {status.upper()}")
        kill_label.config(background={
            "halted": "#c62828", "active": "#2e7d32",
            "unknown": "#e0e0e0"}.get(status, "#e0e0e0"),
            foreground="white" if status in ("halted", "active") else "black")
        lp = exp.get("largest_position") or {}
        herf_var.set(
            f"Herfindahl: {exp.get('herfindahl') or 'n/a'} · largest: "
            f"{lp.get('symbol') or '—'} "
            f"({(lp.get('weight') or 0):.1%})")
        net_var.set(f"Net: {_money(exp.get('net_delta_dollars'))} "
                    f"({(exp.get('net_frac') or 0):.2%})")
        gross_var.set(f"Gross: {_money(exp.get('gross_dollars'))} "
                      f"({(exp.get('gross_frac') or 0):.2%})")
        per = exp.get("per_symbol", [])
        charts.draw_bars(exp_canvas, [(p["symbol"], p["value"]) for p in per],
                         CW, CH)
        H.set_tree_rows(exp_tree, [
            (p.get("symbol"), p.get("qty"), p.get("price"), p.get("value"),
             p.get("beta_adj_value")) for p in per
        ])
        vol = result.get("vol_regime", {})
        vols = vol.get("vol") or []
        vol_canvas.delete("all")
        pts = charts.line_points([float(v) for v in vols], CW, CH)
        if len(pts) >= 2:
            vol_canvas.create_line(*[c for p in pts for c in p],
                                   fill=charts.LINE_COLOR, width=2)
            vol_canvas.create_text(10, 12, anchor="w", fill="gray",
                                   text="trailing 21d realized vol (ann.)")
        else:
            vol_canvas.create_text(CW // 2, CH // 2, text="no vol timeline",
                                   fill="gray")
        vol_note_var.set(vol.get("note", ""))
        gauge = result.get("regime")
        if gauge and gauge.get("conviction") is not None:
            frac = float(gauge["conviction"]) / 100.0
            charts.draw_gauge(gauge_canvas, frac,
                              f"conviction {gauge['conviction']:.1f}%", CW, CH)
            hyst_var.set(
                f"hysteresis: {gauge.get('hysteresis_state')} — "
                f"{gauge.get('hysteresis_reason') or ''} · "
                f"composite_raw={gauge.get('composite_raw')} · "
                f"exposure_scale={gauge.get('exposure_scale')}")
        else:
            gauge_canvas.delete("all")
            gauge_canvas.create_text(CW // 2, CH // 2,
                                     text="no regime snapshot supplied — "
                                          "conviction gauge empty",
                                     fill="gray")
            hyst_var.set("")
        banner_var.set("DEMO — synthetic book; not real positions."
                       if result.get("demo") else "")
        summary_var.set(
            f"{exp.get('n_positions', 0)} positions · {result.get('message', '')}")
        ctx.status("Risk monitor refreshed")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        summary_var.set(f"Refresh failed: {error.splitlines()[0]}")
        ctx.status("Risk monitor failed")
        run_btn.config(state="normal")

    def run() -> None:
        try:
            vol_days = int(vol_var.get() or "63")
        except ValueError:
            summary_var.set("Bad input: vol days must be an integer")
            return
        run_btn.config(state="disabled")
        summary_var.set("Refreshing…")
        ctx.submit(Job("risk-monitor", eng.run_risk_monitor_job,
                       kwargs={"vol_days": vol_days},
                       on_done=on_done, on_error=on_error))

    run_btn.config(command=run)
    return frame
