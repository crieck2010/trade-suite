"""Seeded simulated multi-symbol feed with a planted spike event.

The demo feed emits canonical ``trade`` messages (see
:mod:`trade_stream.normalizer`) from a deterministic random walk, so
tests, examples, and CI never need the network.

The planted arc: symbols random-walk quietly, then ``AAA`` spikes ~+12%
over roughly two minutes mid-feed (ticks 200-320), then the walk resumes.
:func:`run_demo` wires the feed through a :class:`MessageBus` with spike
alerts, bar resampling, and a price cache, and returns a summary — the
spike alert firing is the demo's "it works" check.
"""

from __future__ import annotations

import random
import time

from .alerts import MultiSpikeDetector
from .bars import resample
from .bus import MessageBus
from .normalizer import SCHEMA_VERSION

DEMO_SYMBOLS = ("AAA", "BBB", "CCC")
BASE_TS = 1_700_000_000.0  # fixed epoch so the demo is fully deterministic

# Planted spike: AAA ticks in this tick-index range get an extra drift.
SPIKE_TICK_LO = 200
SPIKE_TICK_HI = 320
SPIKE_SYMBOL = "AAA"
SPIKE_DRIFT = 0.0035  # per AAA-tick multiplicative drift during the window


def demo_feed(symbols: tuple[str, ...] = DEMO_SYMBOLS, seed: int = 7,
              n_ticks: int = 600, start_ts: float = BASE_TS):
    """Yield canonical trade messages. Deterministic given ``seed``."""
    rng = random.Random(seed)
    symbols = tuple(symbols)
    prices = {s: 100.0 * (1.0 + 0.5 * i) for i, s in enumerate(symbols)}
    ts = start_ts
    for i in range(n_ticks):
        sym = symbols[i % len(symbols)]
        prices[sym] *= 1.0 + rng.gauss(0.0, 0.0015)
        if SPIKE_TICK_LO <= i <= SPIKE_TICK_HI and sym == SPIKE_SYMBOL:
            prices[sym] *= 1.0 + SPIKE_DRIFT
        price = round(prices[sym], 4)
        ts += 0.3 + rng.random() * 0.4
        yield {
            "kind": "trade",
            "symbol": sym,
            "price": price,
            "size": round(rng.uniform(0.1, 5.0), 4),
            "bid": round(price * 0.9999, 4),
            "ask": round(price * 1.0001, 4),
            "ts": round(ts, 3),
            "source": "demo",
            "schema_version": SCHEMA_VERSION,
        }


def _wait_received(sub, expected: int, timeout: float = 10.0) -> None:
    """Block until a subscription has dispatched ``expected`` messages."""
    deadline = time.time() + timeout
    while sub.stats()["received"] < expected:
        if time.time() > deadline:
            raise TimeoutError(
                f"bus drain timed out: {sub.stats()['received']}/{expected}"
            )
        time.sleep(0.01)


def run_demo(symbols: tuple[str, ...] = DEMO_SYMBOLS, seed: int = 7,
             n_ticks: int = 600, spike_window_s: float = 300.0,
             spike_threshold: float = 0.05, bar_tf_s: int = 60) -> dict:
    """End-to-end demo: feed -> bus -> alerts + bars + cache. Returns summary."""
    from .adapters import LatestPriceCache  # local: keep demo import-light

    bus = MessageBus()
    collected: list[dict] = []
    collector_sub = bus.subscribe(
        "trades.*", lambda topic, msg: collected.append(msg))
    detector = MultiSpikeDetector(window_s=spike_window_s, threshold=spike_threshold)
    alerts: list[dict] = []
    cache = LatestPriceCache(bus)

    def _on_trade(topic, msg):
        alert = detector.update(msg)
        if alert is not None:
            alerts.append(alert)

    alert_sub = bus.subscribe("trades.*", _on_trade)
    for msg in demo_feed(symbols=symbols, seed=seed, n_ticks=n_ticks):
        bus.publish(f"trades.{msg['symbol']}", msg)
    # The bus dispatches asynchronously: wait until every subscriber has
    # seen every tick before summarizing, so the demo is deterministic.
    _wait_received(collector_sub, n_ticks)
    _wait_received(alert_sub, n_ticks)
    deadline = time.time() + 10.0
    while set(cache.symbols) != set(symbols) and time.time() < deadline:
        time.sleep(0.01)

    bars = resample(collected, bar_tf_s)
    summary = {
        "symbols": list(symbols),
        "seed": seed,
        "n_ticks": len(collected),
        "n_alerts": len(alerts),
        "alerts": alerts,
        "n_bars": len(bars),
        "bar_timeframe_s": bar_tf_s,
        "latest": cache.as_dict(),
        "spike_symbol": SPIKE_SYMBOL,
    }
    bus.close()
    return summary
