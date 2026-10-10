"""Paper track-record store: JSONL, one line per trading day.

Deliberately independent of trade-paper's SQLite audit ledger: this is the
*program* record (incubation days, regime conviction, drift verdicts), not
the *execution* record.  The two reconcile by date; neither depends on the
other's storage format.
"""

from __future__ import annotations

import json
import os


class IncubationLedger:
    """Append-only daily record for one incubation run."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self._days: list[dict] = []
        if path and os.path.exists(path):
            self.load()

    # -- writes -----------------------------------------------------------

    def record_day(self, day_record: dict) -> dict:
        """Append one day's record.  Returns the stored record."""
        rec = {"schema_version": 1, **day_record}
        self._days.append(rec)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
        return rec

    # -- reads ------------------------------------------------------------

    def load(self) -> list[dict]:
        """(Re)load from disk; returns all day records."""
        self._days = []
        if self.path and os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        self._days.append(json.loads(line))
        return self._days

    def days(self) -> list[dict]:
        return list(self._days)

    def equity_curve(self) -> list[float]:
        return [float(d["equity"]) for d in self._days if "equity" in d]

    def closed_trades(self) -> list[dict]:
        trades: list[dict] = []
        for d in self._days:
            trades.extend(d.get("trades", []))
        return trades

    def last(self) -> dict | None:
        return self._days[-1] if self._days else None
