"""Market Data tab: fetch bars and render a candlestick chart."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import charts
from ..context import AppContext
from ..workers import Job
from .. import helpers as H

SHOW_LAST = 120


def summarize(bars: list[dict]) -> str:
    closes = [b["close"] for b in bars]
    first, last = closes[0], closes[-1]
    hi = max(b["high"] for b in bars)
    lo = min(b["low"] for b in bars)
    return (f"{bars[0]['symbol']}: {len(bars)} bars  |  "
            f"${first:,.2f} → ${last:,.2f} ({(last / first - 1):+.1%})  |  "
            f"range ${lo:,.2f} – ${hi:,.2f}  |  "
            f"avg volume {sum(b['volume'] for b in bars) / len(bars):,.0f}")


def build(parent: tk.Widget, ctx: AppContext) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=8)

    controls = ttk.Frame(frame)
    controls.pack(fill="x", pady=(0, 8))
    sym_var = H.entry_row(controls, "Symbol:", "SPY", width=12)
    src_var = tk.StringVar(value="demo")
    src_row = ttk.Frame(controls)
    src_row.pack(side="left", padx=4)
    ttk.Label(src_row, text="Source:").pack(side="left")
    src_combo = ttk.Combobox(src_row, textvariable=src_var, width=24,
                             state="readonly")
    src_combo.pack(side="left", padx=(2, 0))
    days_var = H.entry_row(controls, "Days:", "250", width=6)
    fetch_btn = ttk.Button(controls, text="Fetch")
    fetch_btn.pack(side="left", padx=8)

    def _refresh_sources():
        labels = {s["id"]: f"{s['label']}" for s in ctx.data.sources()}
        src_combo.config(values=list(labels.values()))
        ids = list(labels)
        if src_var.get() not in ids:
            src_var.set("demo")
        # map label back to id on fetch via reverse lookup
        _refresh_sources.id_by_label = {v: k for k, v in labels.items()}

    _refresh_sources.id_by_label = {}
    _refresh_sources()

    stats_var = tk.StringVar(value="Fetch bars to render the chart.")
    ttk.Label(frame, textvariable=stats_var, font=("TkDefaultFont", 10, "bold"),
              wraplength=900, justify="left").pack(fill="x", pady=(0, 4))

    chart = tk.Canvas(frame, height=300, bg="white", highlightthickness=1,
                      highlightbackground="#cccccc")
    chart.pack(fill="both", expand=True, pady=(0, 8))
    last_bars: list = []

    def _redraw(_event=None):
        if last_bars:
            charts.draw_candles(chart, last_bars[-SHOW_LAST:],
                                chart.winfo_width(), chart.winfo_height())

    chart.bind("<Configure>", _redraw)

    ttk.Label(frame, text="Recent bars").pack(anchor="w")
    bars_tree = H.make_tree(frame, [("Date", 110), ("Open", 90), ("High", 90),
                                    ("Low", 90), ("Close", 90), ("Volume", 110)],
                            height=6)

    def on_done(bars: list[dict]) -> None:
        stats_var.set(summarize(bars))
        last_bars.clear()
        last_bars.extend(bars)
        _redraw()
        H.set_tree_rows(bars_tree, [
            (b["timestamp"][:10], f"{b['open']:.2f}", f"{b['high']:.2f}",
             f"{b['low']:.2f}", f"{b['close']:.2f}", f"{b['volume']:,.0f}")
            for b in bars[-30:]
        ])
        ctx.status(f"Loaded {len(bars)} bars for {bars[0]['symbol']}")
        fetch_btn.config(state="normal")

    def on_error(error: str) -> None:
        stats_var.set(f"Fetch failed: {error.splitlines()[0]}")
        ctx.status("Data fetch failed")
        fetch_btn.config(state="normal")

    def fetch() -> None:
        try:
            symbol = (sym_var.get() or "").strip().upper()
            if not symbol:
                raise ValueError("symbol is required")
            days = int(days_var.get())
        except ValueError as exc:
            stats_var.set(f"Bad input: {exc}")
            return
        label = src_combo.get()
        source = _refresh_sources.id_by_label.get(label, "demo")
        fetch_btn.config(state="disabled")
        stats_var.set(f"Fetching {symbol}…")
        ctx.submit(Job("data", ctx.data.get_bars, args=(symbol,),
                       kwargs={"source": source, "days": days},
                       on_done=on_done, on_error=on_error))

    fetch_btn.config(command=fetch)
    return frame
