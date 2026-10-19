"""Point-in-time press archive.  Stdlib sqlite3, suite pattern.

Every archived item carries the timestamps of the spec §3.4 contract:

- ``published_at`` — when the publisher says the story ran (nullable:
  some feeds omit it).
- ``observed_at`` — the as-of time the item *refers to* (publication
  time when known, else fetch time).
- ``recorded_at`` — when the item *entered the archive* (the fetch
  time).  Always >= ``observed_at``; :meth:`PressArchive.record`
  enforces it.

No-lookahead contract (load-bearing, same rule as
``trade_sentiment.archive``): any read made as of decision time D may
use **only** items with ``recorded_at <= D``.  ``PressArchive.query()``
enforces this predicate in SQL and it cannot be opted out of.
Filtering on ``published_at``/``observed_at`` alone is not
point-in-time safe: a story published at 09:30 but fetched at 16:00 can
carry information (edits, corrections, syndication) from 16:00.

Coverage: the archive accumulates items from deployment forward.
There is no history before the first recorded item — never fabricate
history (spec §7: no backfill).  ``coverage()`` says so plainly.

Dedupe: the primary key is the item's content hash (URL + normalized
title), so the same wire story surfacing under several theme queries —
or again on the next scan — is stored exactly once.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import PressItem, ScoredPressItem

DEFAULT_ARCHIVE_PATH = Path.home() / ".trade-press" / "press-archive.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS press_items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    theme_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT NOT NULL,
    publisher TEXT,
    published_at TEXT,
    observed_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    polarity REAL,
    magnitude REAL,
    hits TEXT
);
CREATE INDEX IF NOT EXISTS idx_press_theme_recorded
    ON press_items(theme_id, recorded_at);
CREATE TABLE IF NOT EXISTS theme_daily (
    theme_id TEXT,
    date TEXT,
    n_items INTEGER,
    mean_polarity REAL,
    freq_z REAL,
    polarity_slope_7d REAL,
    state TEXT,
    stats_json TEXT,
    PRIMARY KEY (theme_id, date)
);
"""

_MAX_SUMMARY = 1000  # RSS snippet only; truncated again at record time


def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class PressArchive:
    """SQLite point-in-time store for scored press items and rollups.

    ``path`` may be a file path, ``":memory:"``, or None (the default
    on-disk location ``~/.trade-press/press-archive.db``).
    """

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            self.path = DEFAULT_ARCHIVE_PATH
        else:
            self.path = Path(path) if path != ":memory:" else ":memory:"
        if self.path != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(
            str(self.path) if self.path != ":memory:" else ":memory:")
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._db.commit()

    # -- writes ------------------------------------------------------------
    def record(self, scored: ScoredPressItem) -> bool:
        """Archive one scored item; True when a new row was inserted.

        Re-recording the same content (same id) is a no-op returning
        False — syndicated duplicates collapse onto the primary key.
        Raises ``ValueError`` if ``observed_at`` is after
        ``recorded_at``: an item must never incorporate information from
        after it was archived.  This invariant is what makes the archive
        point-in-time safe.
        """
        item = scored.item
        obs, rec = item.observed_at, item.recorded_at
        if obs.tzinfo is None:
            obs = obs.replace(tzinfo=timezone.utc)
        if rec.tzinfo is None:
            rec = rec.replace(tzinfo=timezone.utc)
        if obs > rec:
            raise ValueError(
                f"observed_at ({obs.isoformat()}) is after recorded_at "
                f"({rec.isoformat()}): an item must never incorporate "
                "information from after it was archived")
        cur = self._db.execute(
            """INSERT OR IGNORE INTO press_items
               (id, source, theme_id, title, summary, url, publisher,
                published_at, observed_at, recorded_at,
                polarity, magnitude, hits)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item.id, item.source, scored.theme_id, item.title,
             item.summary[:_MAX_SUMMARY], item.url, item.publisher,
             _utc_iso(item.published_at) if item.published_at else None,
             _utc_iso(obs), _utc_iso(rec),
             scored.polarity, scored.magnitude,
             json.dumps(list(scored.hits))),
        )
        self._db.commit()
        return cur.rowcount > 0

    def record_many(self, items: list[ScoredPressItem]) -> int:
        """Archive a batch; returns how many rows were newly inserted."""
        return sum(1 for s in items if self.record(s))

    # -- reads -------------------------------------------------------------
    def query(
        self,
        theme_id: str,
        as_of: datetime | str,
        *,
        since: datetime | str | None = None,
        limit: int | None = None,
    ) -> list[ScoredPressItem]:
        """Point-in-time query: items knowable at ``as_of``.

        Returns only rows with ``recorded_at <= as_of`` — this predicate
        is the no-lookahead contract and is applied unconditionally.
        Rows are ordered by ``observed_at`` (oldest first).  ``since``
        bounds ``observed_at`` from below; ``limit`` caps the row count.
        """
        if isinstance(as_of, str):
            as_of = _parse_iso(as_of)
        if isinstance(since, str):
            since = _parse_iso(since)
        sql = ("SELECT * FROM press_items WHERE theme_id = ? "
               "AND recorded_at <= ?")
        params: list = [theme_id, _utc_iso(as_of)]
        if since is not None:
            sql += " AND observed_at >= ?"
            params.append(_utc_iso(since))
        sql += " ORDER BY observed_at ASC, id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [self._row_to_scored(r)
                for r in self._db.execute(sql, params).fetchall()]

    def coverage(self, theme_id: str | None = None) -> dict | None:
        """Min/max ``recorded_at`` and row counts.

        ``coverage(theme_id)`` for one theme, ``coverage()`` for the
        whole archive.  Returns None when (that slice of) the archive is
        empty — no history before deployment exists, and this says so
        plainly.
        """
        if theme_id is None:
            row = self._db.execute(
                "SELECT MIN(recorded_at) lo, MAX(recorded_at) hi, "
                "COUNT(*) n, COUNT(DISTINCT theme_id) nthemes "
                "FROM press_items").fetchone()
        else:
            row = self._db.execute(
                "SELECT MIN(recorded_at) lo, MAX(recorded_at) hi, "
                "COUNT(*) n FROM press_items WHERE theme_id = ?",
                (theme_id,)).fetchone()
        if row["n"] == 0:
            return None
        out = {"first_recorded": row["lo"], "last_recorded": row["hi"],
               "n_items": row["n"]}
        if theme_id is None:
            out["n_themes"] = row["nthemes"]
        else:
            out["theme_id"] = theme_id
        return out

    # -- rollups -------------------------------------------------------------
    def save_rollup(self, payload: dict, stats: dict) -> None:
        """Store one day's narrative-state payload (idempotent upsert).

        ``payload`` is a ``press.narrative_state.v1`` dict; ``stats`` is
        the matching ``ThemeDayStats`` dict, kept inside the payload's
        numbers so the row is self-describing and reproducible.
        """
        self._db.execute(
            """INSERT OR REPLACE INTO theme_daily
               (theme_id, date, n_items, mean_polarity, freq_z,
                polarity_slope_7d, state, stats_json)
               VALUES (?,?,?,?,?,?,?,?)""",
            (payload["theme_id"], payload["as_of"], payload["n_items"],
             payload["mean_polarity"], payload["freq_z"],
             payload["polarity_slope_7d"], payload["state"],
             json.dumps(payload)),
        )
        self._db.commit()

    def get_rollup(self, theme_id: str, day: str) -> dict | None:
        """The stored ``press.narrative_state.v1`` payload for a day.

        ``day`` is an ISO date.  Returns None when no rollup exists for
        that exact (theme, date) — callers must not substitute a stale
        read (see ``context.narrative_input``).
        """
        row = self._db.execute(
            "SELECT stats_json FROM theme_daily "
            "WHERE theme_id = ? AND date = ?", (theme_id, day)).fetchone()
        if row is None:
            return None
        return json.loads(row["stats_json"])

    def close(self) -> None:
        self._db.close()

    def _row_to_scored(self, row: sqlite3.Row) -> ScoredPressItem:
        from trade_sentiment.models import SentimentLabel, label_for

        item = PressItem(
            id=row["id"], source=row["source"], title=row["title"],
            summary=row["summary"] or "", url=row["url"],
            publisher=row["publisher"] or "",
            published_at=_parse_iso(row["published_at"]),
            observed_at=_parse_iso(row["observed_at"]),
            recorded_at=_parse_iso(row["recorded_at"]),
        )
        polarity = row["polarity"]
        return ScoredPressItem(
            item=item, theme_id=row["theme_id"],
            polarity=polarity if polarity is not None else 0.0,
            magnitude=row["magnitude"] if row["magnitude"] is not None
            else 0.0,
            label=(label_for(polarity) if polarity is not None
                   else SentimentLabel.NEUTRAL),
            hits=tuple(json.loads(row["hits"] or "[]")),
        )
