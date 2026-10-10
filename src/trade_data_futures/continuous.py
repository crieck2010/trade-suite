"""Continuous front-month series from per-contract bars.

A continuous contract stitches successive listed contracts into one
tradable-looking history so indicators and backtests don't see expiry
gaps. Two decisions:

* **Roll rule** -- when to switch contracts:
  - ``"volume"`` (default): switch on the first date the next contract's
    volume exceeds the front's -- the market's own liquidity vote.
  - ``"calendar"``: switch a fixed number of days before expiry
    (``roll_days_before``), using each contract's ``expiry`` date.
* **Back-adjustment** -- remove the roll gap from history:
  - ``"ratio"`` (default): multiply past prices by
    ``next_close / front_close`` at the roll. Breaks on non-positive
    prices (e.g. CL in Apr-2020); those boundaries fall back to difference.
  - ``"difference"``: add ``next_close - front_close`` to past prices.
  - ``"none"``: keep raw prices (gaps remain).

The backward pass composes each boundary as an affine transform
``p -> p * M + A``, so ratio and difference boundaries mix correctly.
Volume and open interest are never adjusted -- they always come from the
active contract. Output bars carry ``contract_code="<ROOT>=F"`` and
``source_contract`` naming the listed contract behind each bar.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from math import isfinite

from .exceptions import FuturesDataError
from .models import FuturesBar, FuturesContract


@dataclass(frozen=True, slots=True)
class ContractSeries:
    """Bars for one listed contract, sorted by timestamp."""

    contract: FuturesContract
    bars: tuple[FuturesBar, ...]

    def __post_init__(self) -> None:
        bars = tuple(sorted(self.bars, key=lambda b: b.timestamp))
        object.__setattr__(self, "bars", bars)

    def by_date(self) -> dict[date, FuturesBar]:
        return {b.timestamp.date(): b for b in self.bars}

    def close_on_or_before(self, day: date) -> FuturesBar | None:
        """Latest bar at or before ``day`` (for roll-date closes)."""
        best: FuturesBar | None = None
        for bar in self.bars:
            if bar.timestamp.date() <= day:
                best = bar
            else:
                break
        return best


def _roll_dates_volume(series: list[ContractSeries]) -> list[date]:
    """Per-pair roll date, aligned with ``zip(series, series[1:])``.

    First date the next contract's volume beats the front's; falls back to
    the last shared date, or the next contract's first date when the pair
    never overlaps.
    """
    rolls: list[date] = []
    for front, nxt in zip(series, series[1:]):
        f_map, n_map = front.by_date(), nxt.by_date()
        common = sorted(set(f_map) & set(n_map))
        rolled: date | None = None
        for day in common:
            f_vol, n_vol = f_map[day].volume, n_map[day].volume
            if n_vol > f_vol > 0:
                rolled = day
                break
        if rolled is None:
            rolled = common[-1] if common else (nxt.bars[0].timestamp.date() if nxt.bars else None)
        if rolled is None:
            raise FuturesDataError("cannot determine a roll date for an empty contract pair")
        rolls.append(rolled)
    return rolls


def _roll_dates_calendar(series: list[ContractSeries], roll_days_before: int) -> list[date]:
    rolls: list[date] = []
    for front in series[:-1]:
        if front.contract.expiry is None:
            raise FuturesDataError(
                f"calendar roll needs an expiry date for {front.contract.contract_code}"
            )
        rolls.append(front.contract.expiry - timedelta(days=roll_days_before))
    return rolls


def build_continuous(
    series: list[ContractSeries],
    *,
    roll: str = "volume",
    roll_days_before: int = 5,
    adjust: str = "ratio",
) -> list[FuturesBar]:
    """Stitch per-contract series into one continuous front-month series.

    :param series: per-contract bars; sorted by expiry internally.
    :param roll: ``"volume"`` or ``"calendar"``.
    :param adjust: ``"ratio"``, ``"difference"``, or ``"none"``.
    """
    if roll not in ("volume", "calendar"):
        raise ValueError(f"roll must be 'volume' or 'calendar', got {roll!r}")
    if adjust not in ("ratio", "difference", "none"):
        raise ValueError(f"adjust must be 'ratio', 'difference' or 'none', got {adjust!r}")
    ordered = sorted(series, key=lambda s: (s.contract.year, s.contract.month))
    if not ordered:
        return []
    root = ordered[0].contract.root
    if len(ordered) == 1:
        return [_tag(bar, ordered[0].contract, root) for bar in ordered[0].bars]

    roll_dates = (
        _roll_dates_volume(ordered)
        if roll == "volume"
        else _roll_dates_calendar(ordered, roll_days_before)
    )

    # Index bars by timestamp -> {contract_index: bar}.
    per_stamp: dict[datetime, dict[int, FuturesBar]] = {}
    for i, s in enumerate(ordered):
        for bar in s.bars:
            per_stamp.setdefault(bar.timestamp, {})[i] = bar
    stamps = sorted(per_stamp)

    # Forward pass: active contract per stamp; record each boundary with
    # the front/next closes on the roll date.
    stitched: list[tuple[int, FuturesBar]] = []  # (active_index, bar)
    boundaries: list[tuple[int, float, float]] = []  # (pos, front_close, next_close)
    active = 0
    for pos, stamp in enumerate(stamps):
        while active < len(roll_dates) and stamp.date() >= roll_dates[active]:
            f_bar = ordered[active].close_on_or_before(roll_dates[active])
            n_bar = ordered[active + 1].close_on_or_before(roll_dates[active])
            if f_bar is not None and n_bar is not None:
                boundaries.append((pos, f_bar.close, n_bar.close))
            active += 1
        choices = per_stamp[stamp]
        idx = active if active in choices else max((i for i in choices if i < active), default=min(choices))
        stitched.append((idx, choices[idx]))

    if adjust == "none" or not boundaries:
        return [_tag(bar, ordered[i].contract, root) for i, bar in stitched]

    # Backward pass: compose each boundary as p -> p * M + A. A boundary
    # recorded at position p adjusts positions *strictly before* p -- the
    # roll-date bar itself belongs to the new contract and stays raw.
    out: list[FuturesBar] = [None] * len(stitched)  # type: ignore[list-item]
    mult, add = 1.0, 0.0
    b = len(boundaries) - 1
    for pos in range(len(stitched) - 1, -1, -1):
        while b >= 0 and pos < boundaries[b][0]:
            _, f_close, n_close = boundaries[b]
            use_ratio = (
                adjust == "ratio"
                and f_close > 0 and n_close > 0
                and isfinite(f_close) and isfinite(n_close)
            )
            if use_ratio:
                r = n_close / f_close
                mult, add = mult * r, add  # (p*r)*M + A
            else:
                d = n_close - f_close
                mult, add = mult, add + d * mult  # (p+d)*M + A
            b -= 1
        i, bar = stitched[pos]
        o, h, l, c = (bar.open * mult + add, bar.high * mult + add,
                      bar.low * mult + add, bar.close * mult + add)
        out[pos] = replace(
            bar, open=o, high=max(h, l), low=min(h, l), close=c,
            contract_code=f"{root}=F", source_contract=ordered[i].contract.contract_code,
        )
    return out


def _tag(bar: FuturesBar, contract: FuturesContract, root: str) -> FuturesBar:
    return replace(bar, contract_code=f"{root}=F", source_contract=contract.contract_code)
