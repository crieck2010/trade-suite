"""Paper tab: monitor the ``trade-paper`` engine (paper trading only)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import helpers as H
from ..context import AppContext
from ..workers import Job


def _money(value) -> str:
    return f"${float(value):,.2f}"


def build(parent: tk.Widget, ctx: AppContext) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=8)
    eng = ctx.engine

    # -- top controls -----------------------------------------------------
    top = ttk.Frame(frame)
    top.pack(fill="x", pady=(0, 6))
    cfg_var = H.entry_row(top, "Config", default="paper-config.json", width=40)
    refresh_btn = ttk.Button(top, text="Refresh")
    refresh_btn.pack(side="left", padx=6)
    status_var = tk.StringVar(value="press Refresh to load paper state")
    ttk.Label(top, textvariable=status_var, foreground="gray").pack(side="left", padx=8)

    # -- account ----------------------------------------------------------
    acct_box = ttk.LabelFrame(frame, text="Account (paper only)", padding=6)
    acct_box.pack(fill="x", pady=(0, 6))
    acct_var = tk.StringVar(value="—")
    ttk.Label(acct_box, textvariable=acct_var).pack(anchor="w")

    body = ttk.PanedWindow(frame, orient="horizontal")
    body.pack(fill="both", expand=True)

    # -- positions --------------------------------------------------------
    left = ttk.LabelFrame(body, text="Positions", padding=6)
    pos_tree = H.make_tree(left, [("symbol", 70), ("qty", 70),
                                  ("entry", 80), ("mark", 80), ("uPnL", 80)])
    pos_tree.pack(fill="both", expand=True)
    body.add(left, weight=1)

    # -- approvals --------------------------------------------------------
    mid = ttk.LabelFrame(body, text="Approvals (you decide)", padding=6)
    appr_tree = H.make_tree(mid, [("id", 40), ("strategy", 130),
                                  ("symbols", 90), ("score", 60)])
    appr_tree.pack(fill="both", expand=True)
    appr_btn = ttk.Button(mid, text="Approve selected")
    appr_btn.pack(anchor="e", pady=4)
    body.add(mid, weight=1)

    # -- fidelity ---------------------------------------------------------
    right = ttk.LabelFrame(body, text="Fidelity (backtest vs paper)", padding=6)
    fid_tree = H.make_tree(right, [("strategy", 130), ("fills", 50),
                                   ("avg bps", 70), ("gap bps", 70)])
    fid_tree.pack(fill="both", expand=True)
    fid_var = tk.StringVar(value="—")
    ttk.Label(right, textvariable=fid_var, foreground="gray").pack(anchor="w")
    body.add(right, weight=1)

    # -- reconcile (demo) -------------------------------------------------
    rec_box = ttk.LabelFrame(frame, text="Broker reconcile (DEMO)", padding=6)
    rec_box.pack(fill="x", pady=(6, 0))
    rec_row = ttk.Frame(rec_box)
    rec_row.pack(fill="x")
    rec_btn = ttk.Button(rec_row, text="Run reconcile (DEMO)")
    rec_btn.pack(side="left")
    rec_var = tk.StringVar(
        value="compares the paper ledger against the Robinhood MCP mock "
              "(deliberate drift) — no real account access")
    ttk.Label(rec_row, textvariable=rec_var, foreground="gray").pack(
        side="left", padx=8)
    rec_tree = H.make_tree(rec_box, [("symbol", 70), ("verdict", 130),
                                     ("paper", 70), ("broker", 70),
                                     ("diff", 70)])
    rec_tree.pack(fill="x", pady=(4, 0))

    approval_ids: list[int] = []

    # -- jobs -------------------------------------------------------------
    def on_error(exc: Exception) -> None:
        status_var.set(f"Paper error: {exc}")
        ctx.status(f"Paper refresh failed: {exc}")
        refresh_btn.config(state="normal")

    def on_done(result: dict) -> None:
        s, appr, fid = result["status"], result["approvals"], result["fidelity"]
        acct_var.set(
            f"equity {_money(s['equity'])} · cash {_money(s['cash'])} · "
            f"buying power {_money(s['buying_power'])} · broker {s['broker']} · "
            f"{'market OPEN' if s['market_open'] else 'market closed'} · "
            f"{s['active_strategies']} active strategies · "
            f"{s['pending_approvals']} awaiting approval")
        H.set_tree_rows(pos_tree, [
            (p["symbol"], f"{p['qty']:.4f}", f"{p['avg_entry']:.2f}",
             f"{p['market']:.2f}", f"{p['unrealized']:.2f}")
            for p in s["positions"]])
        approval_ids.clear()
        rows = []
        for r in appr["approvals"]:
            approval_ids.append(r["id"])
            rows.append((r["id"], r["strategy"], r["symbols"],
                         f"{(r['score'] or 0):.2f}"))
        H.set_tree_rows(appr_tree, rows)
        H.set_tree_rows(fid_tree, [
            (name, d["fills"],
             "n/a" if d["avg_realized_slippage_bps"] is None else f"{d['avg_realized_slippage_bps']:.1f}",
             "n/a" if d["slippage_gap_bps"] is None else f"{d['slippage_gap_bps']:.1f}")
            for name, d in fid["strategies"].items()])
        fid_var.set(f"backtest assumption: {fid['assumed_slippage_bps']} bps · "
                    f"{fid['total_fills']} fills")
        status_var.set("loaded")
        ctx.status("Paper state loaded")
        refresh_btn.config(state="normal")

    def refresh() -> None:
        cfg = cfg_var.get().strip()
        refresh_btn.config(state="disabled")
        status_var.set("Loading paper state…")

        def target():
            return {"status": eng.paper_status(cfg),
                    "approvals": eng.paper_approvals(cfg, status="pending"),
                    "fidelity": eng.paper_fidelity(cfg)}

        ctx.submit(Job("paper-refresh", target, on_done=on_done, on_error=on_error))

    refresh_btn.config(command=refresh)

    def reconcile_demo() -> None:
        rec_btn.config(state="disabled")
        rec_var.set("Reconciling paper ledger vs broker mock…")

        def target():
            return eng.run_reconcile_demo_job()

        def done(result: dict) -> None:
            rec = result["reconcile"]
            rows = [(s, "matched", result["paper_positions"][s],
                     result["broker_positions"][s], "—")
                    for s in rec["matched"]]
            rows += [(d["symbol"], "missing from broker", d["paper"], "—",
                      "—") for d in rec["missing_from_broker"]]
            rows += [(d["symbol"], "missing from ledger", "—", d["broker"],
                      "—") for d in rec["missing_from_ledger"]]
            rows += [(d["symbol"], "qty mismatch", d["paper"], d["broker"],
                      f"{d['diff']:+g}")
                     for d in rec["quantity_mismatches"]]
            H.set_tree_rows(rec_tree, rows)
            rec_var.set("clean ✓" if rec["clean"]
                        else "drift detected (deliberate, demo mock)")
            ctx.status("Broker reconcile (demo) done")
            rec_btn.config(state="normal")

        def err(exc: Exception) -> None:
            rec_var.set(f"Reconcile failed: {exc}")
            rec_btn.config(state="normal")

        ctx.submit(Job("paper-reconcile-demo", target, on_done=done,
                       on_error=err))

    rec_btn.config(command=reconcile_demo)

    def approve_selected() -> None:
        sel = appr_tree.selection()
        if not sel:
            status_var.set("select an approval row first")
            return
        aid = approval_ids[appr_tree.index(sel[0])]
        appr_btn.config(state="disabled")

        def target():
            return eng.paper_approve(cfg_var.get().strip(), aid,
                                     reason="approved from desktop dashboard")

        def done(_result):
            appr_btn.config(state="normal")
            status_var.set(f"approved #{aid}")
            refresh()

        def err(exc: Exception):
            appr_btn.config(state="normal")
            on_error(exc)

        ctx.submit(Job("paper-approve", target, on_done=done, on_error=err))

    appr_btn.config(command=approve_selected)
    return frame
