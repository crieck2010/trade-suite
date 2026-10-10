"""Small widget helpers shared by the tabs."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def clear_tree(tree: ttk.Treeview) -> None:
    tree.delete(*tree.get_children())


def set_tree_rows(tree: ttk.Treeview, rows: list[tuple]) -> None:
    clear_tree(tree)
    for row in rows:
        tree.insert("", "end", values=[_fmt(v) for v in row])


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:,.4g}"
    if value is None:
        return ""
    return str(value)


def make_tree(parent, columns: list[tuple[str, int]], height: int = 10) -> ttk.Treeview:
    """Treeview with ``[(heading, width), ...]`` columns inside a scrollbar frame."""
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns],
                        show="headings", height=height)
    for name, width in columns:
        tree.heading(name, text=name)
        tree.column(name, width=width, anchor="w")
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)
    tree.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")
    return tree


def scroll_text(parent, height: int = 12, wrap: str = "word") -> tk.Text:
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)
    text = tk.Text(frame, height=height, wrap=wrap, font=("TkDefaultFont", 9))
    vsb = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=vsb.set)
    text.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")
    return text


def parse_symbols(text: str) -> list[str]:
    return [s.strip().upper() for s in text.replace(";", ",").split(",")
            if s.strip()]


def parse_params(text: str) -> dict:
    """Parse ``key=value, key=value`` pairs; values become int/float when numeric."""
    out: dict = {}
    for chunk in (text or "").split(","):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        key, value = key.strip(), value.strip()
        if not key:
            continue
        try:
            out[key] = int(value)
        except ValueError:
            try:
                out[key] = float(value)
            except ValueError:
                out[key] = value
    return out


def entry_row(parent, label: str, default: str = "", width: int = 18) -> tk.StringVar:
    var = tk.StringVar(value=default)
    row = ttk.Frame(parent)
    row.pack(side="left", padx=4)
    ttk.Label(row, text=label).pack(side="left")
    ttk.Entry(row, textvariable=var, width=width).pack(side="left", padx=(2, 0))
    return var
