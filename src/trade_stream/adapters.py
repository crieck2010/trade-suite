"""Adapters: trade-stream -> the rest of the suite. All lazy, all fail-soft.

Nothing in this module imports a sibling at module top. Sibling engines
are imported *inside* the functions that need them, and only to forward
already-computed plain data. With no siblings installed, every adapter
still imports, constructs, and runs against the bus — the sibling call
is the only part that raises, with a helpful message naming the missing
package.

Adapters provided:

- :func:`subscribe_dashboard` — live tick/quote feed for
  ``trade-dashboard-web``'s live view. The dashboard imports this lazily
  and passes its own push callback; this engine never imports the web app.
- :func:`spike_alerts` — wires :class:`~trade_stream.alerts.MultiSpikeDetector`
  to the bus, publishes alerts on ``alerts.<symbol>``, and optionally
  forwards each alert dict to ``trade-hedge`` (defensive tilt input) and
  ``trade-risk`` (limit-review input) via their lazy entry points.
- :class:`LatestPriceCache` — last-seen price per symbol from the bus;
  the read model ``trade-paper`` (or anything else) queries instead of
  hitting the network.
"""

from __future__ import annotations

import threading

from .alerts import MultiSpikeDetector
from .bus import MessageBus


def _load_sibling(dotted: str):
    """Import a sibling engine lazily; helpful error when absent."""
    try:
        module_name, _, attr = dotted.partition(":")
        import importlib

        mod = importlib.import_module(module_name)
        return getattr(mod, attr) if attr else mod
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            f"optional sibling not available: {dotted!r} "
            f"(install the sibling package to enable this adapter): {exc}"
        ) from exc


# -- dashboard ---------------------------------------------------------
def subscribe_dashboard(bus: MessageBus, on_event, topics=("trades.*", "quotes.*", "bars.*")):
    """Subscribe a dashboard push callback to live topics.

    ``on_event(topic, msg)`` receives canonical messages. Returns the
    list of subscription handles (call ``bus.unsubscribe(h)`` to detach).
    ``trade-dashboard-web`` calls this lazily from its live-view code;
    nothing here imports the dashboard.
    """
    handles = []
    for pattern in topics:
        handles.append(bus.subscribe(pattern, on_event))
    return handles


# -- spike alerts -> hedge / risk --------------------------------------
def _forward_to_hedge(alert: dict) -> None:
    fn = _load_sibling("trade_hedge.adapters:hedge_tilt_input")
    fn(alert)


def _forward_to_risk(alert: dict) -> None:
    fn = _load_sibling("trade_risk.adapters:risk_regime_input")
    fn(alert)


def spike_alerts(
    bus: MessageBus,
    window_s: float = 300.0,
    threshold: float = 0.05,
    sink=None,
    forward_hedge: bool = False,
    forward_risk: bool = False,
):
    """Detect price spikes on the bus; publish + optionally forward them.

    Subscribes to ``trades.*``. Each alert is published to
    ``alerts.<symbol>`` on the bus, passed to ``sink(alert)`` when given,
    and forwarded to ``trade-hedge`` / ``trade-risk`` when the
    ``forward_*`` flags are set (lazy imports; helpful error when the
    sibling isn't installed). Returns ``(detector, subscription)``.
    """
    detector = MultiSpikeDetector(window_s=window_s, threshold=threshold)

    def _on_trade(topic, msg):
        alert = detector.update(msg)
        if alert is None:
            return
        bus.publish(f"alerts.{msg['symbol']}", alert)
        if sink is not None:
            sink(alert)
        if forward_hedge:
            _forward_to_hedge(alert)
        if forward_risk:
            _forward_to_risk(alert)

    sub = bus.subscribe("trades.*", _on_trade)
    return detector, sub


# -- latest-price cache -> trade-paper ---------------------------------
class LatestPriceCache:
    """Last-seen price per symbol, maintained from the bus.

    Subscribe once; query often. ``trade-paper`` uses this as its
    read model for "what is the price right now" without network calls.
    Thread-safe.
    """

    def __init__(self, bus: MessageBus, topics=("trades.*", "quotes.*")) -> None:
        self._prices: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()
        self._subs = [bus.subscribe(p, self._on_msg) for p in topics]

    def _on_msg(self, topic, msg) -> None:
        price = msg.get("price")
        if price is None and msg.get("kind") == "quote":
            bid, ask = msg.get("bid"), msg.get("ask")
            if bid is not None and ask is not None:
                price = (bid + ask) / 2.0
        if not isinstance(price, (int, float)):
            return
        symbol = str(msg.get("symbol", ""))
        ts = float(msg.get("ts", 0.0))
        with self._lock:
            prev = self._prices.get(symbol)
            if prev is None or ts >= prev[1]:
                self._prices[symbol] = (float(price), ts)

    def get(self, symbol: str) -> tuple[float, float] | None:
        """Return ``(price, ts)`` or ``None`` when never seen."""
        with self._lock:
            return self._prices.get(symbol)

    def as_dict(self) -> dict:
        with self._lock:
            return {s: {"price": p, "ts": t} for s, (p, t) in self._prices.items()}

    @property
    def symbols(self) -> list[str]:
        with self._lock:
            return sorted(self._prices)
