"""Canvas charts: pure scaling math (testable, no tkinter) + thin renderers.

Layout helpers are pure functions (no canvas, no tkinter) so they can be
unit-tested headlessly; the ``draw_*`` renderers are thin translations of
those layouts onto a duck-typed canvas.
"""

from __future__ import annotations


def line_points(values: list[float], width: int, height: int, pad: int = 8) -> list[tuple[float, float]]:
    """Map ``values`` to canvas (x, y) points.  Empty input -> []."""
    if not values or width <= 2 * pad or height <= 2 * pad:
        return []
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    return [
        (
            pad + i * (width - 2 * pad) / max(n - 1, 1),
            height - pad - (v - lo) / span * (height - 2 * pad),
        )
        for i, v in enumerate(values)
    ]


def candle_layout(
    bars: list[dict], width: int, height: int, pad: int = 8
) -> list[dict]:
    """Compute candle geometry for ``bars`` (dicts with o/h/l/c keys).

    Returns one dict per bar: ``x``, ``body`` (x0, y0, x1, y1), ``wick``
    (x, y_high, y_low) and ``up`` bool.  Empty input -> [].
    """
    if not bars or width <= 2 * pad or height <= 2 * pad:
        return []
    lo = min(b["low"] for b in bars)
    hi = max(b["high"] for b in bars)
    span = (hi - lo) or 1.0

    def y(price: float) -> float:
        return height - pad - (price - lo) / span * (height - 2 * pad)

    slot = (width - 2 * pad) / len(bars)
    body_w = max(1.0, slot * 0.6)
    out = []
    for i, b in enumerate(bars):
        cx = pad + slot * (i + 0.5)
        up = b["close"] >= b["open"]
        out.append(
            {
                "x": cx,
                "body": (cx - body_w / 2, y(max(b["open"], b["close"])),
                         cx + body_w / 2, y(min(b["open"], b["close"]))),
                "wick": (cx, y(b["high"]), y(b["low"])),
                "up": up,
            }
        )
    return out


# --- canvas renderers (duck-typed canvas; only used with a real tk.Canvas) ---

UP_COLOR = "#2e7d32"
DOWN_COLOR = "#c62828"
LINE_COLOR = "#1565c0"
GRID_COLOR = "#e0e0e0"


def draw_equity_curve(canvas, curve: list[dict], width: int, height: int) -> None:
    """Render ``curve`` (list of {equity}) as a line chart on ``canvas``."""
    canvas.delete("all")
    values = [float(p["equity"]) for p in curve]
    pts = line_points(values, width, height)
    if len(pts) < 2:
        canvas.create_text(width // 2, height // 2, text="not enough data",
                           fill="gray")
        return
    flat = [c for p in pts for c in p]
    canvas.create_line(*flat, fill=LINE_COLOR, width=2)
    first, last = values[0], values[-1]
    canvas.create_text(10, 12, anchor="w", fill="gray",
                       text=f"${first:,.0f} → ${last:,.0f}")


def draw_candles(canvas, bars: list[dict], width: int, height: int) -> None:
    """Render OHLC ``bars`` as candlesticks on ``canvas``."""
    canvas.delete("all")
    layout = candle_layout(bars, width, height)
    if not layout:
        canvas.create_text(width // 2, height // 2, text="no bars", fill="gray")
        return
    for c in layout:
        color = UP_COLOR if c["up"] else DOWN_COLOR
        x0, y0, x1, y1 = c["body"]
        wx, wy_hi, wy_lo = c["wick"]
        canvas.create_line(wx, wy_hi, wx, wy_lo, fill=color)
        canvas.create_rectangle(x0, y0, x1, max(y1, y0 + 1), fill=color,
                                outline=color)
    lo = min(b["low"] for b in bars)
    hi = max(b["high"] for b in bars)
    canvas.create_text(10, 12, anchor="w", fill="gray",
                       text=f"low ${lo:,.2f}  high ${hi:,.2f}  n={len(bars)}")


# --- terminal-wave math helpers (pure, no tkinter) --------------------------

def underwater_curve(equity: list[float]) -> list[float]:
    """Underwater drawdown series (<= 0) for an equity curve.

    For each point: ``-(peak - v)/peak`` where ``peak`` is the running
    maximum — the same definition the engine's ``drawdown`` series uses.
    Empty input -> [].
    """
    out: list[float] = []
    peak = 0.0
    for v in equity:
        peak = max(peak, v)
        out.append(-(peak - v) / peak if peak > 0 else 0.0)
    return out


def bar_layout(values: list[float], width: int, height: int,
               pad: int = 8) -> list[tuple[float, float, float, float]]:
    """Vertical bar rectangles for ``values`` (signed supported).

    Zero line is drawn inside the plot area: bars above/below it.  Empty
    input or a degenerate canvas -> [].
    """
    if not values or width <= 2 * pad or height <= 2 * pad:
        return []
    lo = min(0.0, min(values))
    hi = max(0.0, max(values))
    span = (hi - lo) or 1.0

    def y(v: float) -> float:
        return height - pad - (v - lo) / span * (height - 2 * pad)

    slot = (width - 2 * pad) / len(values)
    bw = max(1.0, slot * 0.7)
    y0 = y(0.0)
    out = []
    for i, v in enumerate(values):
        cx = pad + slot * (i + 0.5)
        yv = y(v)
        out.append((cx - bw / 2, min(y0, yv), cx + bw / 2, max(y0, yv)))
    return out


def zero_line_y(values: list[float], height: int, pad: int = 8) -> float:
    """Canvas y of the zero line used by :func:`bar_layout`."""
    if not values:
        return height - pad
    lo = min(0.0, min(values))
    span = (max(0.0, max(values)) - lo) or 1.0
    return height - pad - (0.0 - lo) / span * (height - 2 * pad)


def heatmap_layout(n_rows: int, n_cols: int, width: int, height: int,
                   pad: int = 8) -> list[dict]:
    """Grid cell rectangles for a monthly heatmap (rows=years, cols=months)."""
    if n_rows < 1 or n_cols < 1 or width <= 2 * pad or height <= 2 * pad:
        return []
    cw = (width - 2 * pad) / n_cols
    rh = (height - 2 * pad) / n_rows
    out = []
    for r in range(n_rows):
        for c in range(n_cols):
            x0, y0 = pad + c * cw, pad + r * rh
            out.append({"row": r, "col": c, "x0": x0, "y0": y0,
                        "x1": x0 + cw, "y1": y0 + rh})
    return out


def heatmap_color(value: float | None, vmin: float, vmax: float) -> str:
    """Diverging red->white->green cell color for a monthly return.

    ``None`` (no data) -> light gray.  Symmetric around zero so a loss
    and an equal gain read as equally strong.
    """
    if value is None:
        return "#e8e8e8"
    span = max(abs(vmin), abs(vmax), 1e-9)
    t = max(-1.0, min(1.0, value / span))
    if t >= 0:
        g = 255
        r = b = int(255 * (1 - t * 0.75))
    else:
        r = 255
        g = b = int(255 * (1 + t * 0.75))
    return f"#{r:02x}{g:02x}{b:02x}"


def gauge_layout(frac: float, width: int, height: int,
                 pad: int = 8) -> dict:
    """Semicircular gauge geometry for a 0..1 fraction (conviction).

    Returns center, radius, needle endpoint, and the arc bounding box.
    ``frac`` is clamped to [0, 1].  Needle sweeps 180° (left) -> 0° (right).
    """
    import math

    frac = max(0.0, min(1.0, frac))
    cx, cy = width / 2.0, height - pad - 6
    r = min(width / 2.0 - pad, height - 2 * pad - 6)
    r = max(r, 1.0)
    angle = math.pi * (1.0 - frac)  # 180° .. 0°
    return {
        "cx": cx, "cy": cy, "r": r,
        "needle": (cx + r * math.cos(angle), cy - r * math.sin(angle)),
        "bbox": (cx - r, cy - r, cx + r, cy + r),
        "frac": frac,
    }


def network_positions(nodes: list[dict], width: int, height: int,
                      pad: int = 24) -> list[dict]:
    """Map server MST layout (x, y in [-100, 100]) to canvas coordinates.

    Node radius scales with annualized vol (``vol``), normalized so the
    largest node is 16px and the smallest 5px; zero vol -> 5px.  Returns
    one dict per node: ``symbol, x, y, r, cluster, vol``.  This is a pure
    affine rescale — the topology is computed by the engine, not here.
    """
    if not nodes or width <= 2 * pad or height <= 2 * pad:
        return []
    vmax = max((float(nd.get("vol") or 0.0) for nd in nodes), default=0.0)
    out = []
    for nd in nodes:
        v = float(nd.get("vol") or 0.0)
        r = 5.0 + 11.0 * (v / vmax) if vmax > 0 else 5.0
        out.append({
            "symbol": nd.get("symbol", ""),
            "x": pad + (float(nd.get("x", 0.0)) + 100.0) / 200.0 * (width - 2 * pad),
            "y": pad + (float(nd.get("y", 0.0)) + 100.0) / 200.0 * (height - 2 * pad),
            "r": r,
            "cluster": nd.get("cluster", 0),
            "vol": v,
        })
    return out


def edge_width(weight: float, max_w: float = 6.0) -> float:
    """MST edge canvas width from |correlation|: 1px .. ``max_w`` px."""
    return 1.0 + (max_w - 1.0) * min(abs(float(weight)), 1.0)


_CLUSTER_PALETTE = ["#1565c0", "#2e7d32", "#ef6c00", "#6a1b9a", "#00838f",
                    "#c62828", "#5d4037", "#455a64"]


def cluster_color(cluster: int) -> str:
    """Deterministic cluster -> color mapping (palette cycles)."""
    return _CLUSTER_PALETTE[int(cluster) % len(_CLUSTER_PALETTE)]


def calibration_layout(brier: dict, width: int, height: int,
                       pad: int = 8) -> dict:
    """Brier calibration chart geometry: diagonal + observed points.

    Bins live in [0, 1]^2; point radius scales with bin count ``n``.
    Bins with no observations are skipped.
    """
    import math

    def xy(p: float, o: float) -> tuple[float, float]:
        return (pad + p * (width - 2 * pad),
                height - pad - o * (height - 2 * pad))

    diag = [xy(0.0, 0.0), xy(1.0, 1.0)]
    bins = brier.get("bins") or []
    obs = brier.get("observed") or []
    ns = brier.get("n") or []
    max_n = max(ns) if ns else 1
    pts = []
    for p, o, n in zip(bins, obs, ns):
        if o is None:
            continue
        x, y = xy(p, o)
        pts.append({"x": x, "y": y, "p": p, "o": o, "n": n,
                    "r": 3.0 + 5.0 * math.sqrt(n / max_n)})
    return {"diag": diag, "points": pts}


MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# --- terminal-wave canvas renderers (duck-typed canvas) -----------------------

def draw_underwater(canvas, equity: list[float], width: int, height: int) -> None:
    """Render the underwater drawdown curve (negative fractions, red fill)."""
    canvas.delete("all")
    dd = underwater_curve(equity)
    pts = line_points(dd, width, height)
    if len(pts) < 2:
        canvas.create_text(width // 2, height // 2, text="not enough data",
                           fill="gray")
        return
    flat = [c for p in pts for c in p]
    base = [pts[0][0], height - 8] + flat + [pts[-1][0], height - 8]
    canvas.create_polygon(*base, fill="#ffcdd2", outline="")
    canvas.create_line(*flat, fill=DOWN_COLOR, width=1.5)
    worst = min(dd)
    canvas.create_text(10, 12, anchor="w", fill="gray",
                       text=f"max drawdown {worst:.2%}")


def draw_histogram(canvas, hist: dict, width: int, height: int) -> None:
    """Render a return histogram (``{"bins", "counts"}``) as bars."""
    canvas.delete("all")
    counts = [float(c) for c in (hist.get("counts") or [])]
    if not counts or width <= 16 or height <= 16:
        canvas.create_text(width // 2, height // 2, text="no data",
                           fill="gray")
        return
    for x0, y0, x1, y1 in bar_layout(counts, width, height):
        canvas.create_rectangle(x0, y0, x1, max(y1, y0 + 1),
                                fill=LINE_COLOR, outline=LINE_COLOR)
    canvas.create_text(10, 12, anchor="w", fill="gray",
                       text=f"daily returns, n={sum(int(c) for c in counts)}")


def draw_bars(canvas, items: list[tuple[str, float]], width: int,
              height: int) -> None:
    """Signed horizontal-free vertical bars with a zero line.

    ``items`` are ``(label, value)``; labels are drawn under the bars.
    """
    canvas.delete("all")
    if not items or width <= 16 or height <= 16:
        canvas.create_text(width // 2, height // 2, text="no data",
                           fill="gray")
        return
    values = [v for _, v in items]
    zy = zero_line_y(values, height)
    for (label, v), (x0, y0, x1, y1) in zip(items, bar_layout(values, width, height)):
        color = UP_COLOR if v >= 0 else DOWN_COLOR
        canvas.create_rectangle(x0, y0, x1, max(y1, y0 + 1), fill=color,
                                outline=color)
        canvas.create_text((x0 + x1) / 2, height - 2, anchor="s", text=label,
                           font=("TkDefaultFont", 7), fill="gray")
    canvas.create_line(8, zy, width - 8, zy, fill="gray")


def draw_heatmap(canvas, years: list[int], monthly: list[list],
                 width: int, height: int) -> None:
    """Monthly-return heatmap: rows = years, cols = months."""
    canvas.delete("all")
    if not years or not monthly:
        canvas.create_text(width // 2, height // 2, text="no data",
                           fill="gray")
        return
    cells = heatmap_layout(len(years), 12, width, height, pad=40)
    flat_vals = [v for row in monthly for v in row if v is not None]
    vmax = max((abs(v) for v in flat_vals), default=1e-9)
    for cell in cells:
        r, c = cell["row"], cell["col"]
        v = monthly[r][c] if r < len(monthly) and c < len(monthly[r]) else None
        canvas.create_rectangle(cell["x0"] + 1, cell["y0"] + 1,
                                cell["x1"] - 1, cell["y1"] - 1,
                                fill=heatmap_color(v, -vmax, vmax), outline="")
        if v is not None and cell["x1"] - cell["x0"] > 34:
            canvas.create_text((cell["x0"] + cell["x1"]) / 2,
                               (cell["y0"] + cell["y1"]) / 2,
                               text=f"{v:.1%}", font=("TkDefaultFont", 7))
    for c, lab in enumerate(MONTH_LABELS):
        cell = cells[c]
        canvas.create_text((cell["x0"] + cell["x1"]) / 2, 6, text=lab,
                           font=("TkDefaultFont", 7), fill="gray")
    for r, y in enumerate(years):
        cell = cells[r * 12]
        canvas.create_text(20, (cell["y0"] + cell["y1"]) / 2, text=str(y),
                           font=("TkDefaultFont", 7), fill="gray")


def draw_gauge(canvas, frac: float, label: str, width: int,
               height: int) -> None:
    """Conviction gauge: semicircular dial + needle + numeric label."""
    canvas.delete("all")
    g = gauge_layout(frac, width, height)
    canvas.create_arc(*g["bbox"], start=0, extent=180, style="arc",
                      outline="gray", width=2)
    nx, ny = g["needle"]
    canvas.create_line(g["cx"], g["cy"], nx, ny, fill="#c62828", width=3)
    canvas.create_oval(g["cx"] - 4, g["cy"] - 4, g["cx"] + 4, g["cy"] + 4,
                       fill="#c62828", outline="")
    canvas.create_text(g["cx"], g["cy"] - g["r"] - 12, text=label,
                       font=("TkDefaultFont", 11, "bold"))
    canvas.create_text(12, height - 10, anchor="w", text="0", fill="gray")
    canvas.create_text(width - 12, height - 10, anchor="e", text="100",
                       fill="gray")


def draw_network(canvas, result: dict, width: int, height: int) -> None:
    """Static render of the engine-computed MST layout.

    Nodes are colored by cluster and sized by annualized vol; edge width
    scales with |correlation|.  This is a static render — no pan/zoom
    physics in tkinter (see the Network tab for the menu-driven explorer).
    """
    canvas.delete("all")
    nodes = network_positions(result.get("nodes") or [], width, height)
    if not nodes:
        canvas.create_text(width // 2, height // 2, text="no network data",
                           fill="gray")
        return
    by_id = {i: nd for i, nd in enumerate(nodes)}
    for e in result.get("edges") or []:
        a, b = by_id.get(e.get("a")), by_id.get(e.get("b"))
        if a is None or b is None:
            continue
        canvas.create_line(a["x"], a["y"], b["x"], b["y"], fill="#9e9e9e",
                           width=edge_width(e.get("weight", 0.0)))
    for nd in nodes:
        color = cluster_color(nd["cluster"])
        canvas.create_oval(nd["x"] - nd["r"], nd["y"] - nd["r"],
                           nd["x"] + nd["r"], nd["y"] + nd["r"],
                           fill=color, outline="#333333")
        canvas.create_text(nd["x"], nd["y"] + nd["r"] + 9, text=nd["symbol"],
                           font=("TkDefaultFont", 7))
    n_cl = len(result.get("clusters") or [])
    canvas.create_text(10, 12, anchor="w", fill="gray",
                       text=(f"{len(nodes)} nodes, {len(result.get('edges') or [])} "
                             f"edges, {n_cl} clusters — static layout "
                             f"(seed {result.get('params', {}).get('seed')})"))


def draw_calibration(canvas, brier: dict, width: int, height: int) -> None:
    """Brier calibration: observed exceedance rate vs forecast probability."""
    canvas.delete("all")
    lay = calibration_layout(brier, width, height)
    if not lay["points"]:
        canvas.create_text(width // 2, height // 2,
                           text="no paired forecasts", fill="gray")
        return
    x0, y0 = lay["diag"][0]
    x1, y1 = lay["diag"][1]
    canvas.create_line(x0, y0, x1, y1, fill="#9e9e9e", dash=(4, 3))
    for p in lay["points"]:
        canvas.create_oval(p["x"] - p["r"], p["y"] - p["r"],
                           p["x"] + p["r"], p["y"] + p["r"],
                           fill=LINE_COLOR, outline="")
        canvas.create_text(p["x"], p["y"] - p["r"] - 6,
                           text=f"n={p['n']}", font=("TkDefaultFont", 7),
                           fill="gray")
    canvas.create_text(width // 2, height - 4, text="forecast P(exceed)",
                       fill="gray", font=("TkDefaultFont", 8))
    canvas.create_text(8, height // 2, text="observed rate", fill="gray",
                       font=("TkDefaultFont", 8), angle=90)
