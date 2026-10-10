"""On-disk cache for futures bars and contract listings.

Bars are keyed by ``(provider, contract, timeframe, start, end)`` with a
24-hour TTL (futures history is rarely revised beyond the last session).
Contract listings refresh every 24 hours as well. Layout::

    <root>/<provider>/bars_<sha1>.json
    <root>/<provider>/contracts_<ROOT>.json

Stdlib-only JSON. ``TRADE_FUTURES_CACHE`` overrides the default
``~/.cache/trade-data-futures``.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import FuturesBar, FuturesContract, Timeframe, ensure_utc
from .symbols import parse_contract_code


def _default_root() -> Path:
    return Path(os.environ.get("TRADE_FUTURES_CACHE", Path.home() / ".cache" / "trade-data-futures"))


class DiskCache:
    """JSON file cache for bars (TTL 24h) and contract lists (TTL 24h)."""

    def __init__(
        self,
        root: str | Path | None = None,
        bars_ttl: timedelta = timedelta(hours=24),
        contracts_ttl: timedelta = timedelta(hours=24),
    ) -> None:
        self.root = Path(root) if root is not None else _default_root()
        self.bars_ttl = bars_ttl
        self.contracts_ttl = contracts_ttl

    # -- bars -------------------------------------------------------------
    @staticmethod
    def _bars_key(provider: str, contract: str, timeframe: Timeframe, start: date, end: date) -> str:
        return "bars_" + hashlib.sha1(
            f"{provider}|{contract.upper()}|{timeframe.value}|{start.isoformat()}|{end.isoformat()}".encode()
        ).hexdigest()

    @staticmethod
    def _bar_to_dict(b: FuturesBar) -> dict[str, Any]:
        return {
            "contract_code": b.contract_code,
            "timestamp": b.timestamp.isoformat(),
            "open": b.open, "high": b.high, "low": b.low, "close": b.close,
            "volume": b.volume, "open_interest": b.open_interest,
            "source_contract": b.source_contract,
        }

    @staticmethod
    def _bar_from_dict(item: dict[str, Any]) -> FuturesBar:
        return FuturesBar(
            contract_code=item["contract_code"],
            timestamp=ensure_utc(datetime.fromisoformat(item["timestamp"])),
            open=item["open"], high=item["high"], low=item["low"], close=item["close"],
            volume=item["volume"], open_interest=item["open_interest"],
            source_contract=item.get("source_contract"),
        )

    def get_bars(
        self, provider: str, contract: str, timeframe: Timeframe, start: date, end: date
    ) -> list[FuturesBar] | None:
        raw = self._read(provider, self._bars_key(provider, contract, timeframe, start, end), self.bars_ttl)
        if raw is None:
            return None
        return [self._bar_from_dict(b) for b in raw]

    def put_bars(
        self, provider: str, contract: str, timeframe: Timeframe,
        start: date, end: date, bars: list[FuturesBar],
    ) -> None:
        self._write(
            provider,
            self._bars_key(provider, contract, timeframe, start, end),
            [self._bar_to_dict(b) for b in bars],
        )

    # -- contracts ----------------------------------------------------------
    @staticmethod
    def _contract_to_dict(c: FuturesContract) -> dict[str, Any]:
        return {
            "root": c.root, "year": c.year, "month": c.month,
            "expiry": c.expiry.isoformat() if c.expiry else None,
        }

    def get_contracts(self, provider: str, root: str) -> list[FuturesContract] | None:
        raw = self._read(provider, f"contracts_{root.upper()}", self.contracts_ttl)
        if raw is None:
            return None
        return [
            FuturesContract(
                root=item["root"], year=item["year"], month=item["month"],
                expiry=date.fromisoformat(item["expiry"]) if item["expiry"] else None,
            )
            for item in raw
        ]

    def put_contracts(self, provider: str, root: str, contracts: list[FuturesContract]) -> None:
        self._write(provider, f"contracts_{root.upper()}",
                    [self._contract_to_dict(c) for c in contracts])

    # -- file io ------------------------------------------------------------
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
