"""Press sources.  Every adapter is keyless, stdlib-only, and polite.

Phase 1 ships one source:

- ``GoogleNewsThemeSource`` — Google News RSS queried by a theme's
  search strings (no key).  This is the same endpoint family
  ``trade_sentiment``'s ``NewsSource`` uses, driven by theme queries
  instead of tickers.

The ``PressSource`` ABC is the seam for the Phase 2 adapters named in
the spec (SEC EDGAR full-text search, PR-wire RSS) — interfaces noted,
not built.

Only headlines and RSS summary snippets are ever taken — never full
article text (see ``licensing.py``).
"""

from __future__ import annotations

import html
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from .models import PressItem, ThemeDefinition, make_item_id

_UA = {"User-Agent": "trade-press/0.1.0 (research; contact: github.com/crieck2010)"}
_TIMEOUT = 15
_MAX_TITLE = 500
_MAX_SUMMARY = 1000

_TAG_RE = re.compile(r"<[^>]+>")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as res:
        return res.read()


def _clean_text(raw: str, limit: int) -> str:
    text = html.unescape(_TAG_RE.sub(" ", raw or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _parse_pubdate(value: str) -> datetime | None:
    """RSS pubDate → aware datetime; ``None`` when absent/unparseable."""
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_feed(xml_bytes: bytes, source_name: str,
               fetched_at: datetime) -> list[PressItem]:
    """Parse one RSS document into press items.  Pure; no network.

    Malformed XML yields ``[]`` (one bad feed must not kill a scan).
    Entries missing a title or a link are skipped.  An entry with no
    parseable ``pubDate`` keeps ``published_at=None`` and is observed at
    fetch time.  Items are de-duplicated by content id within the feed.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    out: list[PressItem] = []
    seen: set[str] = set()
    for entry in root.iter("item"):
        raw_title = (entry.findtext("title") or "").strip()
        link = (entry.findtext("link") or "").strip()
        if not raw_title or not link:
            continue
        publisher = (entry.findtext("source") or "").strip()
        title = html.unescape(raw_title)
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(f" - {publisher}")].strip()
        elif " - " in title:  # Google News suffixes " - Publisher"
            title = title.rsplit(" - ", 1)[0].strip()
        title = title[:_MAX_TITLE]
        summary = _clean_text(entry.findtext("description") or "",
                              _MAX_SUMMARY)
        published = _parse_pubdate(entry.findtext("pubDate") or "")
        observed = published if published is not None else fetched_at
        if observed > fetched_at:  # publisher clock skew: never future-date
            observed = fetched_at
        item_id = make_item_id(link, title)
        if item_id in seen:
            continue
        seen.add(item_id)
        out.append(PressItem(
            id=item_id, source=source_name, title=title, summary=summary,
            url=link, publisher=publisher, published_at=published,
            observed_at=observed, recorded_at=fetched_at,
        ))
    return out


class PressSource(ABC):
    """One place press coverage of a narrative theme can be fetched from."""

    name: str = "base"
    rate_limit_note: str = ""

    @abstractmethod
    def fetch(self, theme: ThemeDefinition,
              limit: int = 50) -> list[PressItem]:
        """Return up to ``limit`` recent items per theme query."""
        raise NotImplementedError


class GoogleNewsThemeSource(PressSource):
    """Google News RSS for a theme's search strings (no key)."""

    name = "google_news"
    rate_limit_note = "RSS, no key; be polite (pause between queries)"
    _last_call = 0.0

    def fetch(self, theme: ThemeDefinition,
              limit: int = 50) -> list[PressItem]:
        fetched_at = datetime.now(timezone.utc)
        out: list[PressItem] = []
        seen: set[str] = set()
        for query in theme.queries:
            self._polite()
            q = urllib.parse.quote(query)
            url = (f"https://news.google.com/rss/search?q={q}"
                   f"&hl=en-US&gl=US&ceid=US:en")
            try:
                items = parse_feed(_get(url), self.name, fetched_at)
            except Exception:
                items = []  # one bad query must not kill the scan
            for item in items[:limit]:
                if item.id not in seen:
                    seen.add(item.id)
                    out.append(item)
        return out

    def _polite(self):
        wait = 1.0 - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()


SOURCES: dict[str, type[PressSource]] = {
    "google_news": GoogleNewsThemeSource,
}


def get_source(name: str) -> PressSource:
    """Instantiate a source by name; ``KeyError`` with a hint otherwise."""
    try:
        return SOURCES[name.lower()]()
    except KeyError:
        raise KeyError(
            f"unknown press source {name!r}; "
            f"available: {', '.join(sorted(SOURCES))}"
        ) from None
