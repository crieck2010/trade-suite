"""Tests for trade_press.sources — RSS parsing on static fixtures (no network)."""

from __future__ import annotations

from datetime import datetime, timezone

from trade_press.sources import parse_feed

FETCHED = datetime(2026, 10, 19, 20, 0, tzinfo=timezone.utc)

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Google News</title>
<item>
  <title>Microsoft expands data center buildout with new GPU cluster - Reuters</title>
  <link>https://example.com/story1</link>
  <description>&lt;p&gt;Microsoft said capex will rise as the data center
  buildout accelerates.&lt;/p&gt;</description>
  <pubDate>Sun, 19 Oct 2026 14:30:00 GMT</pubDate>
  <source url="https://www.reuters.com">Reuters</source>
</item>
<item>
  <title>Hyperscaler power capacity deals surge - Bloomberg</title>
  <link>https://example.com/story2</link>
  <description>Power capacity for AI infrastructure is tight.</description>
  <source url="https://www.bloomberg.com">Bloomberg</source>
</item>
<item>
  <title>Item without a link is skipped</title>
  <description>No link element at all.</description>
</item>
<item>
  <title>Microsoft expands data center buildout with new GPU cluster - Reuters</title>
  <link>https://example.com/story1</link>
  <description>Syndicated duplicate of the first item.</description>
  <pubDate>Sun, 19 Oct 2026 14:30:00 GMT</pubDate>
  <source url="https://www.reuters.com">Reuters</source>
</item>
</channel></rss>
"""


def test_parse_feed_happy_path():
    items = parse_feed(FEED, "google_news", FETCHED)
    assert len(items) == 2  # link-less skipped, duplicate collapsed
    first = items[0]
    assert first.title == \
        "Microsoft expands data center buildout with new GPU cluster"
    assert first.publisher == "Reuters"
    assert first.url == "https://example.com/story1"
    assert "capex will rise" in first.summary
    assert "<p>" not in first.summary
    assert first.recorded_at == FETCHED


def test_pubdate_parsed_and_observed():
    first = parse_feed(FEED, "google_news", FETCHED)[0]
    assert first.published_at == datetime(2026, 10, 19, 14, 30,
                                           tzinfo=timezone.utc)
    assert first.observed_at == first.published_at


def test_missing_pubdate_observed_at_fetch():
    second = parse_feed(FEED, "google_news", FETCHED)[1]
    assert second.published_at is None
    assert second.observed_at == FETCHED
    assert second.publisher == "Bloomberg"


def test_future_pubdate_is_clamped_to_fetch():
    feed = FEED.replace(b"19 Oct 2026 14:30:00 GMT",
                        b"20 Oct 2026 14:30:00 GMT")
    first = parse_feed(feed, "google_news", FETCHED)[0]
    assert first.observed_at == FETCHED  # never future-dated
    assert first.published_at > FETCHED  # publisher's claim kept as-is


def test_malformed_xml_yields_empty():
    assert parse_feed(b"<rss><channel><item>", "google_news", FETCHED) == []
    assert parse_feed(b"", "google_news", FETCHED) == []


def test_item_ids_are_stable():
    a = parse_feed(FEED, "google_news", FETCHED)
    b = parse_feed(FEED, "google_news", FETCHED)
    assert [i.id for i in a] == [i.id for i in b]
