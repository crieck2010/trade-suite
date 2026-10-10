"""Normalization: provider-specific JSON -> canonical plain-data messages.

The canonical message is the interop contract of this engine
(``schema_version: 1``). Every source normalizes to it; every consumer
(bus subscribers, recorder, bar resampler, adapters) reads only it::

    {
        "kind": "trade" | "quote" | "bar",   # what this message is
        "symbol": "BTC-USD",                 # provider symbol, verbatim
        "price": 67234.5,                   # trade price (None for quotes)
        "size": 0.012,                      # trade size in base units (None ok)
        "bid": 67234.0,                     # best bid (None ok)
        "ask": 67235.0,                     # best ask (None ok)
        "ts": 1727194800.123,               # epoch seconds, float
        "source": "coinbase",                # source name
        "schema_version": 1,
    }

Rules:

- ``ts`` is always epoch seconds (float). ISO-8601 strings from providers
  are parsed; unparseable/missing timestamps fall back to arrival time and
  the message keeps flowing — a missing timestamp must not kill a stream.
- Unknown or unmappable provider messages normalize to ``None`` (skipped),
  never raise. Normalization is a filter, not a gate.
- Symbols pass through verbatim (``BTC-USD``, ``AAPL``); mapping to a
  canonical symbology is the caller's job.
"""

from __future__ import annotations

import datetime
import time

SCHEMA_VERSION = 1

KINDS = ("trade", "quote", "bar")

REQUIRED = ("kind", "symbol", "ts", "source")


def _to_epoch(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Heuristic: > 1e12 is milliseconds, > 1e15 microseconds.
        v = float(value)
        if v > 1e15:
            return v / 1e6
        if v > 1e12:
            return v / 1e3
        return v
    if isinstance(value, str):
        s = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.datetime.fromisoformat(s)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    return None


def _canonical(kind: str, symbol: str, source: str, ts, **fields) -> dict | None:
    if kind not in KINDS or not symbol:
        return None
    epoch = _to_epoch(ts)
    if epoch is None:
        epoch = time.time()  # arrival-time fallback; stream keeps flowing
    msg = {
        "kind": kind,
        "symbol": str(symbol),
        "price": fields.get("price"),
        "size": fields.get("size"),
        "bid": fields.get("bid"),
        "ask": fields.get("ask"),
        "ts": epoch,
        "source": source,
        "schema_version": SCHEMA_VERSION,
    }
    return msg


def _fnum(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def normalize_coinbase(raw: dict) -> dict | None:
    """Normalize a Coinbase Exchange websocket message.

    Handles the ``matches`` channel (trades) and the ``ticker`` channel
    (quotes). Heartbeats, subscriptions acks, errors -> ``None``.
    """
    if not isinstance(raw, dict):
        return None
    rtype = raw.get("type")
    symbol = raw.get("product_id")
    if rtype == "match":
        return _canonical(
            "trade", symbol, "coinbase", raw.get("time"),
            price=_fnum(raw.get("price")), size=_fnum(raw.get("size")),
        )
    if rtype == "ticker":
        return _canonical(
            "quote", symbol, "coinbase", raw.get("time"),
            price=_fnum(raw.get("price")),
            bid=_fnum(raw.get("best_bid")), ask=_fnum(raw.get("best_ask")),
        )
    return None


def normalize_demo(raw: dict) -> dict | None:
    """Demo feed already emits canonical messages; validate and pass through."""
    if not isinstance(raw, dict):
        return None
    if raw.get("kind") not in KINDS or not raw.get("symbol"):
        return None
    msg = dict(raw)
    msg["schema_version"] = SCHEMA_VERSION
    msg["source"] = "demo"
    if _to_epoch(msg.get("ts")) is None:
        msg["ts"] = time.time()
    else:
        msg["ts"] = _to_epoch(msg["ts"])
    return msg


def validate_canonical(msg: dict) -> list[str]:
    """Return a list of contract violations (empty = valid)."""
    problems = []
    if not isinstance(msg, dict):
        return ["not-a-dict"]
    for field in REQUIRED:
        if field not in msg:
            problems.append(f"missing:{field}")
    if msg.get("kind") not in KINDS:
        problems.append(f"bad-kind:{msg.get('kind')}")
    if msg.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"bad-schema:{msg.get('schema_version')}")
    return problems
