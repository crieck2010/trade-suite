"""Reader for trade-paper SQLite ledgers.

The paper-trading ledger (trade-paper) records book-level
``equity_snapshots`` (``at``, ``equity``, ``cash``) and per-symbol
``position_snapshots`` on every pointed run.  This module turns those
snapshots into the equity series the decay metrics consume.

Each registered strategy points at one ledger file (``ledger_path`` in
the strategy registry).  Today that is one ledger per strategy book;
the reader does not assume a strategy column, because the schema has
none -- multi-strategy books are handled by giving each strategy its
own ledger file.

Schema expectations (fail-loud, not fail-soft: a misread ledger must
never silently produce metrics):
  equity_snapshots(at TEXT, equity REAL, cash REAL, ...)
  position_snapshots(at TEXT, run_id, symbol TEXT, quantity REAL,
                     avg_cost REAL, market_price REAL, ...)

Stdlib only (``sqlite3``).  Read-only: the connection is opened
``mode=ro`` and the module never writes.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime

#: Default ledger location.  Override with ``$TRADE_DECAY_LEDGER`` or
#: pass ``path`` explicitly (tests do the latter).
DEFAULT_LEDGER_PATH = os.path.expanduser("~/.trade-paper/regcond1.db")


class LedgerError(ValueError):
    """Raised when a ledger cannot be read (missing file, bad schema)."""


def _default_path() -> str:
    return os.environ.get("TRADE_DECAY_LEDGER", DEFAULT_LEDGER_PATH)


class LedgerReader:
    """Read-only view of one trade-paper ledger file."""

    def __init__(self, path: str | None = None):
        self.path = os.path.expanduser(path or _default_path())
        if not os.path.isfile(self.path):
            raise LedgerError(
                f"ledger not found: {self.path} "
                f"(set $TRADE_DECAY_LEDGER or pass path=)")

    def _connect(self) -> sqlite3.Connection:
        # Read-only open: a monitoring engine must not be able to
        # mutate the book it watches.
        uri = f"file:{self.path}?mode=ro"
        try:
            con = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as exc:
            raise LedgerError(f"cannot open ledger {self.path}: {exc}")
        return con

    def _require_table(self, con: sqlite3.Connection, table: str) -> None:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)).fetchone()
        if row is None:
            raise LedgerError(
                f"ledger {self.path} has no {table!r} table -- not a "
                f"trade-paper ledger (v0.5.0+)")

    def equity_series(self) -> list[tuple[datetime, float]]:
        """``[(datetime, equity)]`` ascending, from ``equity_snapshots``."""
        con = self._connect()
        try:
            self._require_table(con, "equity_snapshots")
            rows = con.execute(
                "SELECT at, equity FROM equity_snapshots ORDER BY at"
            ).fetchall()
        finally:
            con.close()
        series = []
        for at, equity in rows:
            try:
                value = float(equity)
            except (TypeError, ValueError):
                continue
            text = str(at).strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                ts = datetime.fromisoformat(text)
            except ValueError:
                continue
            series.append((ts, value))
        return series

    def snapshot_count(self) -> int:
        con = self._connect()
        try:
            self._require_table(con, "equity_snapshots")
            row = con.execute(
                "SELECT COUNT(*) FROM equity_snapshots").fetchone()
        finally:
            con.close()
        return int(row[0]) if row else 0

    def position_snapshots(self,
                           symbol: str | None = None) -> list[dict]:
        """Per-symbol position marks (latest mark per symbol by default).

        Returns dicts with ``symbol, quantity, avg_cost, market_price,
        unrealized_pnl, unrealized_pct, weight_pct, at``.  Empty list
        when the ledger predates per-position snapshots (v0.6.0+).
        """
        con = self._connect()
        try:
            row = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='position_snapshots'").fetchone()
            if row is None:
                return []
            query = ("SELECT at, symbol, quantity, avg_cost, market_price,"
                     " unrealized_pnl, unrealized_pct, weight_pct"
                     " FROM position_snapshots")
            params: tuple = ()
            if symbol is not None:
                query += " WHERE symbol = ?"
                params = (symbol,)
            query += " ORDER BY at"
            rows = con.execute(query, params).fetchall()
        finally:
            con.close()
        return [{"at": r[0], "symbol": r[1], "quantity": r[2],
                 "avg_cost": r[3], "market_price": r[4],
                 "unrealized_pnl": r[5], "unrealized_pct": r[6],
                 "weight_pct": r[7]} for r in rows]
