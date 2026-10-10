"""Live tab: poll a local DEMO stream session and show latest prices.

THREADING CONTRACT — read before touching this file:

* One background (daemon) thread runs ``trade_stream.StreamSession`` with
  ``source="demo"`` and pumps ticks onto a ``trade_stream.MessageBus``.
* A ``trade_stream.LatestPriceCache`` subscribed to that bus is the ONLY
  channel between the stream thread and the UI.  The cache is thread-safe:
  the stream thread only writes to it (through bus callbacks), the UI only
  reads it via ``cache.as_dict()``.
* The tkinter widgets are updated ONLY from the tkinter main thread, via a
  ``frame.after(2000, ...)`` polling callback.  NEVER touch a tkinter widget
  (not even a ``StringVar``) from the stream thread — tkinter is not
  thread-safe.
* The demo feed is finite: ``FeedExhausted`` ends the session's run loop.
  The background thread then creates a FRESH ``StreamSession`` and restarts
  it ("restart the finite demo feed on exhaustion").  The feed is seeded, so
  each loop replays the same ticks — this is a DEMO, not live data.
* Teardown: the stream thread is daemon (it dies with the process).  When
  the tab frame is destroyed, the stop event is set and the bus is closed so
  the thread exits promptly instead of lingering.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import ttk

from .. import helpers as H
from ..context import AppContext

POLL_MS = 2000
DEMO_SYMBOLS = ("AAA", "BBB", "CCC")
HINT = ("trade-stream is not installed; "
        "pip install git+https://github.com/crieck2010/trade-stream.git")


def _pump(stop: threading.Event, ts, bus, symbols: tuple[str, ...],
          stats: dict, lock: threading.Lock) -> None:
    """Background thread: run a fresh demo session until stopped.

    Every ``StreamSession.run()`` consumes one finite seeded demo feed and
    returns when ``FeedExhausted`` ends the loop; we then restart with a new
    session.  Nothing here touches tkinter.
    """
    while not stop.is_set():
        session = ts.StreamSession(source="demo", symbols=list(symbols),
                                   bus=bus)
        try:
            session.run()
        finally:
            with lock:
                stats["restarts"] += 1
                stats["ticks"] += session.published
        if stop.wait(0.5):
            break


def build(parent: tk.Widget, ctx: AppContext) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=8)
    try:
        import trade_stream as ts
    except ImportError:
        ttk.Label(frame, text="Live stream unavailable",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        ttk.Label(frame, text=HINT, wraplength=900).pack(anchor="w", pady=4)
        return frame

    bus = ts.MessageBus()
    cache = ts.LatestPriceCache(bus)
    stop = threading.Event()
    stats = {"restarts": 0, "ticks": 0}
    lock = threading.Lock()

    header = ttk.Frame(frame)
    header.pack(fill="x", pady=(0, 6))
    ttk.Label(header, text="DEMO STREAM — simulated feed",
              font=("TkDefaultFont", 11, "bold")).pack(side="left")
    status_var = tk.StringVar(value="starting demo feed…")
    ttk.Label(header, textvariable=status_var, foreground="gray").pack(
        side="left", padx=12)

    tree = H.make_tree(frame, [("Symbol", 100), ("Last price", 120),
                               ("Updated", 120)])

    thread = threading.Thread(target=_pump, name="live-demo-stream",
                              args=(stop, ts, bus, DEMO_SYMBOLS, stats, lock),
                              daemon=True)
    thread.start()

    alive = {"ok": True}

    def poll() -> None:
        if not alive["ok"]:
            return
        rows = [(s, f"{d['price']:.4f}",
                 time.strftime("%H:%M:%S", time.localtime(d["ts"])))
                for s, d in sorted(cache.as_dict().items())]
        H.set_tree_rows(tree, rows)
        with lock:
            restarts, ticks = stats["restarts"], stats["ticks"]
        status_var.set(f"{ticks} ticks · {restarts} feed restarts · "
                       f"polling every {POLL_MS // 1000}s")
        frame.after(POLL_MS, poll)

    def on_destroy(event) -> None:
        if event.widget is frame:
            alive["ok"] = False
            stop.set()
            try:
                bus.close()
            except Exception:
                pass

    frame.bind("<Destroy>", on_destroy)
    poll()
    return frame
