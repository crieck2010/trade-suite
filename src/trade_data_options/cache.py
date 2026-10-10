"""On-disk cache for option chains and expiry lists.

Chains are snapshots of fast-moving quotes, so the default TTL is short
(15 minutes). Only **raw** vendor chains are cached -- model IVs and
greeks are recomputed on every read, keeping model assumptions out of
stored data. Layout mirrors ``trade-data-equities``::

    <root>/<provider>/chain_<sha1>.json
    <root>/<provider>/expiries_<UNDERLYING>.json

The cache is stdlib-only (JSON). Point ``root`` at fast local storage for
large multi-expiry scans; ``TRADE_OPTIONS_CACHE`` overrides the default
``~/.cache/trade-data-options``.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import OptionQuote, ensure_utc
from .providers.base import RawChain
from .symbols import parse_occ


def _default_root() -> Path:
    return Path(os.environ.get("TRADE_OPTIONS_CACHE", Path.home() / ".cache" / "trade-data-options"))


class DiskCache:
    """JSON file cache for chains (TTL 15m) and expiries (TTL 24h)."""

    def __init__(
        self,
        root: str | Path | None = None,
        chain_ttl: timedelta = timedelta(minutes=15),
        expiries_ttl: timedelta = timedelta(hours=24),
    ) -> None:
        self.root = Path(root) if root is not None else _default_root()
        self.chain_ttl = chain_ttl
        self.expiries_ttl = expiries_ttl

    # -- chains ---------------------------------------------------------
    @staticmethod
    def _chain_key(provider: str, underlying: str, expiry: date) -> str:
        return "chain_" + hashlib.sha1(
            f"{provider}|{underlying.upper()}|{expiry.isoformat()}".encode()
        ).hexdigest()

    @staticmethod
    def _quote_to_dict(q: OptionQuote) -> dict[str, Any]:
        return {
            "occ": q.contract.occ_symbol,
            "timestamp": q.timestamp.isoformat(),
            "bid": q.bid,
            "ask": q.ask,
            "last": q.last,
            "volume": q.volume,
            "open_interest": q.open_interest,
            "implied_volatility": q.implied_volatility,
        }

    @staticmethod
    def _quote_from_dict(item: dict[str, Any]) -> OptionQuote:
        return OptionQuote(
            contract=parse_occ(item["occ"]),
            timestamp=ensure_utc(datetime.fromisoformat(item["timestamp"])),
            bid=item["bid"],
            ask=item["ask"],
            last=item["last"],
            volume=item["volume"],
            open_interest=item["open_interest"],
            implied_volatility=item["implied_volatility"],
        )

    def get_chain(self, provider: str, underlying: str, expiry: date) -> RawChain | None:
        raw = self._read(provider, self._chain_key(provider, underlying, expiry), self.chain_ttl)
        if raw is None:
            return None
        return RawChain(
            underlying=raw["underlying"],
            expiry=date.fromisoformat(raw["expiry"]),
            asof=ensure_utc(datetime.fromisoformat(raw["asof"])),
            calls=tuple(self._quote_from_dict(q) for q in raw["calls"]),
            puts=tuple(self._quote_from_dict(q) for q in raw["puts"]),
        )

    def put_chain(self, provider: str, chain: RawChain) -> None:
        payload = {
            "underlying": chain.underlying,
            "expiry": chain.expiry.isoformat(),
            "asof": chain.asof.isoformat(),
            "calls": [self._quote_to_dict(q) for q in chain.calls],
            "puts": [self._quote_to_dict(q) for q in chain.puts],
        }
        self._write(provider, self._chain_key(provider, chain.underlying, chain.expiry), payload)

    # -- expiries ---------------------------------------------------------
    def get_expiries(self, provider: str, underlying: str) -> list[date] | None:
        raw = self._read(provider, f"expiries_{underlying.upper()}", self.expiries_ttl)
        if raw is None:
            return None
        return [date.fromisoformat(d) for d in raw]

    def put_expiries(self, provider: str, underlying: str, expiries: list[date]) -> None:
        self._write(
            provider,
            f"expiries_{underlying.upper()}",
            [d.isoformat() for d in expiries],
        )

    # -- file io ----------------------------------------------------------
    def _path(self, namespace: str, key: str) -> Path:
        return self.root / namespace / f"{key}.json"

    def _read(self, namespace: str, key: str, ttl: timedelta) -> Any | None:
        path = self._path(namespace, key)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        fetched = datetime.fromisoformat(doc["fetched_at"])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched > ttl:
            return None
        return doc["payload"]

    def _write(self, namespace: str, key: str, payload: Any) -> None:
        path = self._path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"fetched_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
        path.write_text(json.dumps(doc), encoding="utf-8")

    def clear(self, namespace: str | None = None) -> int:
        """Delete cached files; returns the number removed."""
        targets = [self.root / namespace] if namespace else [self.root]
        removed = 0
        for target in targets:
            if not target.exists():
                continue
            for path in target.rglob("*.json"):
                path.unlink()
                removed += 1
        return removed
