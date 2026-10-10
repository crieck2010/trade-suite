"""Copper/gold price series: validation, alignment, and source trade-offs.

A *series* is a list of ``{"date": "YYYY-MM-DD", "price": float}`` dicts —
plain data, no timestamps with timezones, no pandas.

Source trade-offs (``source`` flag on :func:`snapshot` and the CLI):

- ``"futures"`` (default): HG (copper) and GC (gold) continuous front-month
  contracts via ``trade-data-futures``.  Purer exposure to the metals, but
  continuous contracts carry **roll effects** — ratio-adjusted back-adjusting
  shifts levels at each roll, and the choice of roll rule (volume vs
  calendar) changes history slightly.  Document which roll you used.
- ``"etf"``: CPER/JJC (copper) vs GLD (gold) via ``trade-data-equities``.
  Trivial to fetch and split/dividend-adjusted by the data engine, but you
  pay expense ratios and accept **tracking error** (CPER holds futures and
  can deviate from spot for weeks).

Either way the engine aligns the two legs on their *shared* dates (inner
join): a date present in only one leg is dropped, and the alignment is
reported, never silently padded.
"""

from __future__ import annotations

import math

SOURCE_NOTES = {
    "futures": (
        "HG/GC continuous front-month contracts via trade-data-futures. "
        "Purer metal exposure; watch roll effects (roll rule changes history)."
    ),
    "etf": (
        "CPER/JJC vs GLD via trade-data-equities. Easy and corporate-action "
        "adjusted; expense drag + tracking error vs the metals."
    ),
}


def validate_series(series: list[dict], name: str = "series") -> list[dict]:
    """Validate and date-sort a price series.

    Returns a *new* list sorted ascending by ``date``.  Raises ValueError
    for: empty input, missing ``date``/``price`` keys, non-finite or
    non-positive prices (a ratio needs positive legs), or duplicate dates.
    """
    if not series:
        raise ValueError(f"{name}: empty series")
    clean: list[dict] = []
    for i, row in enumerate(series):
        if "date" not in row or "price" not in row:
            raise ValueError(f"{name}[{i}]: need 'date' and 'price' keys")
        price = row["price"]
        if not isinstance(price, (int, float)) or not math.isfinite(price):
            raise ValueError(f"{name}[{i}]: price must be finite, got {price!r}")
        if price <= 0:
            raise ValueError(f"{name}[{i}]: price must be positive, got {price!r}")
        clean.append({"date": str(row["date"]), "price": float(price)})
    seen: set[str] = set()
    for row in clean:
        if row["date"] in seen:
            raise ValueError(f"{name}: duplicate date {row['date']!r}")
        seen.add(row["date"])
    clean.sort(key=lambda r: r["date"])
    return clean


def align_series(
    copper: list[dict],
    gold: list[dict],
) -> tuple[list[dict], list[dict], list[str]]:
    """Inner-join two validated series on shared dates.

    Returns ``(copper_aligned, gold_aligned, dates)`` — all three in the
    same ascending date order, covering exactly the dates present in *both*
    legs.  Raises ValueError when the overlap is empty.
    """
    cu = validate_series(copper, "copper")
    au = validate_series(gold, "gold")
    au_by_date = {r["date"]: r["price"] for r in au}
    cu_out, au_out, dates = [], [], []
    for r in cu:
        if r["date"] in au_by_date:
            dates.append(r["date"])
            cu_out.append({"date": r["date"], "price": r["price"]})
            au_out.append({"date": r["date"], "price": au_by_date[r["date"]]})
    if not dates:
        raise ValueError("copper and gold share no dates (empty inner join)")
    return cu_out, au_out, dates
