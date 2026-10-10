"""Stream source definitions.

A source is a plain dict::

    {
        "name": "coinbase",
        "url": "wss://ws-feed.exchange.coinbase.com",
        "auth": "none",            # "none" | "api-key" | "oauth"
        "subscribe": fn(symbols) -> dict,   # subscribe message builder
        "normalize": fn(raw) -> canonical | None,
        "channels": [...],         # human-readable channel list
        "stub": False,             # True -> not implemented, setup docs only
    }

No network happens at import time. ``get_source(name)`` returns the
definition; :mod:`trade_stream.runner` turns it into a live session.

Sources today:

- ``demo`` — seeded simulated feed. Deterministic, offline, the default
  for tests, examples, and CI.
- ``coinbase`` — Coinbase Exchange public websocket feed. No auth, real
  market data. Subscribe message builder included and documented.
- ``polygon`` — STUB. Declared interface + setup docs; needs
  ``POLYGON_API_KEY``. Implement when the Polygon provider is written.
- ``alpaca`` — STUB. Declared interface + setup docs; needs
  ``APCA_API_KEY_ID`` / ``APCA_API_SECRET_KEY``.
"""

from __future__ import annotations

from . import normalizer as _nz


def _coinbase_subscribe(symbols: list[str]) -> dict:
    return {
        "type": "subscribe",
        "product_ids": list(symbols),
        "channels": [
            {"name": "matches"},   # trade executions
            {"name": "ticker"},    # top-of-book quotes
        ],
    }


def _demo_subscribe(symbols: list[str]) -> dict:
    return {"type": "demo-subscribe", "symbols": list(symbols)}


def _polygon_subscribe(symbols: list[str]) -> dict:
    # Polygon's socket cluster uses {"action": "auth", ...} then
    # {"action": "subscribe", "params": "T.AAPL,..."}.
    return {"action": "subscribe", "params": ",".join(f"T.{s}" for s in symbols)}


def _alpaca_subscribe(symbols: list[str]) -> dict:
    return {"action": "subscribe", "trades": list(symbols), "quotes": list(symbols)}


SOURCES: dict[str, dict] = {
    "demo": {
        "name": "demo",
        "url": None,
        "auth": "none",
        "subscribe": _demo_subscribe,
        "normalize": _nz.normalize_demo,
        "channels": ["simulated trades"],
        "stub": False,
        "note": "Seeded simulated feed. Deterministic; no network.",
    },
    "coinbase": {
        "name": "coinbase",
        "url": "wss://ws-feed.exchange.coinbase.com",
        "auth": "none",
        "subscribe": _coinbase_subscribe,
        "normalize": _nz.normalize_coinbase,
        "channels": ["matches", "ticker"],
        "stub": False,
        "note": "Public feed, no auth. Product ids like BTC-USD, ETH-USD.",
    },
    "polygon": {
        "name": "polygon",
        "url": "wss://socket.polygon.io/stocks",
        "auth": "api-key",
        "subscribe": _polygon_subscribe,
        "normalize": None,  # wire up when the Polygon provider is written
        "channels": ["T.* (trades)", "Q.* (quotes)"],
        "stub": True,
        "note": (
            "STUB — not implemented. Needs POLYGON_API_KEY and an auth "
            "handshake ({\"action\": \"auth\", \"params\": key}) before "
            "subscribing. See docs/STREAMING.md."
        ),
    },
    "alpaca": {
        "name": "alpaca",
        "url": "wss://stream.data.alpaca.markets/v2/sip",
        "auth": "api-key",
        "subscribe": _alpaca_subscribe,
        "normalize": None,
        "channels": ["trades", "quotes"],
        "stub": True,
        "note": (
            "STUB — not implemented. Needs APCA_API_KEY_ID and "
            "APCA_API_SECRET_KEY with an auth message first. "
            "See docs/STREAMING.md."
        ),
    },
}


def get_source(name: str) -> dict:
    """Return the source definition; raise KeyError listing valid names."""
    try:
        return SOURCES[name]
    except KeyError:
        raise KeyError(
            f"unknown source {name!r}; choose from {sorted(SOURCES)}"
        ) from None


def source_names() -> list[str]:
    return sorted(SOURCES)


def live_source_names() -> list[str]:
    """Sources that can actually stream today (not stubs)."""
    return sorted(n for n, s in SOURCES.items() if not s["stub"])


def require_live(name: str) -> dict:
    """Get a source or raise a helpful error if it is a stub."""
    src = get_source(name)
    if src["stub"]:
        raise RuntimeError(
            f"source {name!r} is a declared stub, not implemented. {src['note']}"
        )
    if src["normalize"] is None:
        raise RuntimeError(f"source {name!r} has no normalizer yet.")
    return src
