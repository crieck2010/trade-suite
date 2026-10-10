"""Strategy catalog tab: browse the trade-strategies registry."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..context import AppContext
from .. import helpers as H


def render_strategy(desc: dict) -> str:
    lines = [
        f"{desc.get('name', '?')}  [{desc.get('family', '?')}]",
        "",
        desc.get("description", ""),
        "",
        "Parameters:",
    ]
    for key, value in (desc.get("parameters") or {}).items():
        lines.append(f"  {key} = {value}")
    lines += [
        "",
        f"Warmup bars: {desc.get('warmup_bars', '?')}",
        f"Demo symbols: {', '.join(desc.get('symbols') or []) or '—'}",
    ]
    return "\n".join(lines)


def build(parent: tk.Widget, ctx: AppContext) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=8)

    try:
        strategies = ctx.engine.list_strategies()
        error = ""
    except RuntimeError as exc:
        strategies, error = [], str(exc)

    paned = ttk.PanedWindow(frame, orient="horizontal")
    paned.pack(fill="both", expand=True)

    left = ttk.Frame(paned, padding=(0, 0, 8, 0))
    ttk.Label(left, text=f"Strategies ({len(strategies)})").pack(anchor="w")
    listbox = tk.Listbox(left, width=36, exportselection=False)
    listbox.pack(fill="both", expand=True)
    for s in strategies:
        listbox.insert("end", f"{s['name']}  [{s['family']}]")
    paned.add(left, weight=1)

    right = ttk.Frame(paned)
    detail = H.scroll_text(right, height=24)
    paned.add(right, weight=2)

    by_index = {i: s for i, s in enumerate(strategies)}

    def show(_event=None):
        sel = listbox.curselection()
        if not sel:
            return
        detail.delete("1.0", "end")
        detail.insert("1.0", render_strategy(by_index[sel[0]]))

    listbox.bind("<<ListboxSelect>>", show)
    if strategies:
        listbox.selection_set(0)
        show()
    elif error:
        detail.insert("1.0", f"Strategy engine unavailable:\n{error}\n\n"
                             "Install the trade-strategies package to browse "
                             "the catalog.")
    return frame
