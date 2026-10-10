"""Performance tab: equity/drawdown, monthly heatmap, rolling stats.

Runs ``engine.run_performance_job`` (shared web engine when installed,
local fallback otherwise) through the background ``Job`` infrastructure
and renders the plain-data analytics with the pure-math helpers in
``ui/charts.py``.  Sub-tabs: Summary, Equity & Drawdown, Monthly,
Rolling, Histogram.  A DEMO banner marks seeded synthetic equity.
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


def _canvas(parent: tk.Widget) -> tk.Canvas:
    c = tk.Canvas(parent, width=CW, height=CH, background="white",
                  highlightthickness=1, highlightbackground="#cccccc")
    c.pack(fill="both", expand=True, padx=4, pady=4)
    return c


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
    src_var = tk.StringVar(value="paper")
    f = ttk.Frame(row)
    f.pack(side="left", padx=4)
    ttk.Label(f, text="Source:").pack(side="left")
    ttk.Combobox(f, textvariable=src_var, values=["paper", "backtest"],
                 width=10, state="readonly").pack(side="left", padx=(2, 0))
    bt_var = H.entry_row(row, "Backtest JSON path:", "", width=34)
    rf_var = H.entry_row(row, "Risk-free:", "0.0", width=6)
    run_btn = ttk.Button(row, text="Analyze")
    run_btn.pack(side="left", padx=8)
    summary_var = tk.StringVar(value="")
    ttk.Label(row, textvariable=summary_var,
              font=("TkDefaultFont", 10, "bold")).pack(side="left", padx=12)

    # -- sub-tabs ---------------------------------------------------------
    note = ttk.Notebook(frame)
    note.pack(fill="both", expand=True)

    sum_tab = _sub(note, "Summary")
    sum_vars: dict[str, tk.StringVar] = {}
    cards = ttk.Frame(sum_tab)
    cards.pack(fill="x", pady=8)
    for i, (key, label) in enumerate([
        ("win_rate", "Win rate"), ("profit_factor", "Profit factor"),
        ("expectancy", "Expectancy $"), ("max_drawdown", "Max drawdown"),
        ("cagr", "CAGR"), ("n_trades", "Trades"),
    ]):
        v = tk.StringVar(value="—")
        sum_vars[key] = v
        box = ttk.Frame(cards, relief="groove", borderwidth=1, padding=8)
        box.grid(row=0, column=i, padx=6, sticky="ew")
        cards.columnconfigure(i, weight=1)
        ttk.Label(box, text=label, foreground="gray").pack()
        ttk.Label(box, textvariable=v,
                  font=("TkDefaultFont", 12, "bold")).pack()
    src_line = tk.StringVar(value="")
    ttk.Label(sum_tab, textvariable=src_line, wraplength=900,
              foreground="gray", justify="left").pack(anchor="w", pady=8)

    eq_tab = _sub(note, "Equity & Drawdown")
    eq_canvas = _canvas(eq_tab)
    dd_canvas = _canvas(eq_tab)

    mon_tab = _sub(note, "Monthly")
    mon_canvas = _canvas(mon_tab)

    roll_tab = _sub(note, "Rolling")
    sharpe_canvas = _canvas(roll_tab)
    vol_canvas = _canvas(roll_tab)

    hist_tab = _sub(note, "Histogram")
    hist_canvas = _canvas(hist_tab)

    def _fmt(v, pct=False):
        if v is None:
            return "n/a"
        if isinstance(v, float):
            return f"{v:.2%}" if pct else f"{v:.4f}"
        return str(v)

    def on_done(result: dict) -> None:
        s = result.get("summary", {})
        sum_vars["win_rate"].set(_fmt(s.get("win_rate"), pct=True))
        sum_vars["profit_factor"].set(_fmt(s.get("profit_factor")))
        sum_vars["expectancy"].set(_fmt(s.get("expectancy")))
        sum_vars["max_drawdown"].set(_fmt(s.get("max_drawdown"), pct=True))
        sum_vars["cagr"].set(_fmt(s.get("cagr"), pct=True))
        sum_vars["n_trades"].set(str(s.get("n_trades", "—")))
        src_line.set(
            f"equity_source={result.get('equity_source')} · "
            f"{s.get('start', '')} → {s.get('end', '')} · "
            f"{result.get('message', '')}")
        banner_var.set("DEMO — seeded synthetic equity; not real results."
                       if result.get("demo") else "")
        equity = [(ts, float(v)) for ts, v in result.get("equity", [])]
        charts.draw_equity_curve(eq_canvas,
                                 [{"equity": v} for _, v in equity], CW, CH)
        charts.draw_underwater(dd_canvas, [v for _, v in equity], CW, CH)
        charts.draw_heatmap(mon_canvas, result.get("years", []),
                            result.get("monthly", []), CW, CH)
        rsh = [(i, v) for i, v in enumerate(result.get("rolling_sharpe", []))
               if v is not None]
        if len(rsh) >= 2:
            pts = charts.line_points([v for _, v in rsh], CW, CH)
            sharpe_canvas.delete("all")
            sharpe_canvas.create_line(*[c for p in pts for c in p],
                                      fill=charts.LINE_COLOR, width=2)
            sharpe_canvas.create_text(10, 12, anchor="w", fill="gray",
                                      text="rolling 63d Sharpe (ann.)")
        else:
            sharpe_canvas.delete("all")
            sharpe_canvas.create_text(CW // 2, CH // 2, text="no rolling data",
                                      fill="gray")
        rvol = [(i, v) for i, v in enumerate(result.get("rolling_vol", []))
                if v is not None]
        if len(rvol) >= 2:
            pts = charts.line_points([v for _, v in rvol], CW, CH)
            vol_canvas.delete("all")
            vol_canvas.create_line(*[c for p in pts for c in p],
                                   fill=charts.UP_COLOR, width=2)
            vol_canvas.create_text(10, 12, anchor="w", fill="gray",
                                   text="rolling 63d vol (ann.)")
        else:
            vol_canvas.delete("all")
            vol_canvas.create_text(CW // 2, CH // 2, text="no rolling data",
                                   fill="gray")
        charts.draw_histogram(hist_canvas, result.get("histogram", {}), CW, CH)
        summary_var.set(
            f"{len(equity)} equity points · max DD "
            f"{_fmt(s.get('max_drawdown'), pct=True)}")
        ctx.status("Performance analysis done")
        run_btn.config(state="normal")

    def on_error(error: str) -> None:
        summary_var.set(f"Analysis failed: {error.splitlines()[0]}")
        ctx.status("Performance analysis failed")
        run_btn.config(state="normal")

    def run() -> None:
        try:
            risk_free = float(rf_var.get() or "0.0")
        except ValueError:
            summary_var.set("Bad input: risk-free must be numeric")
            return
        run_btn.config(state="disabled")
        summary_var.set("Analyzing…")
        src = src_var.get()
        kwargs = {"source": src, "risk_free": risk_free}
        if src == "backtest":
            path = bt_var.get().strip()
            if not path:
                summary_var.set("Bad input: backtest needs a JSON path")
                run_btn.config(state="normal")
                return
            kwargs["backtest_path"] = path
        ctx.submit(Job("performance", eng.run_performance_job, kwargs=kwargs,
                       on_done=on_done, on_error=on_error))

    run_btn.config(command=run)
    return frame
