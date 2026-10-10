"""Constituent universe handling and the seeded demo universe.

A universe is ``{symbol: [bar, ...]}`` where each bar is a plain dict with
``date`` (ISO ``YYYY-MM-DD``), ``open``, ``high``, ``low``, ``close``,
``volume``.  Everything downstream works on this shape — no DataFrames,
no third-party types.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

BAR_KEYS = ("date", "open", "high", "low", "close", "volume")


def validate_universe(universe: dict) -> dict[str, list[dict]]:
    """Validate and normalize a universe; raises ValueError on bad input.

    Sorts each symbol's bars by date and drops exact duplicate dates
    (keeping the last bar).  Symbols with no usable bars are dropped; an
    empty universe raises.
    """
    if not isinstance(universe, dict) or not universe:
        raise ValueError("universe must be a non-empty dict of symbol -> bars")
    cleaned: dict[str, list[dict]] = {}
    for symbol, bars in universe.items():
        if not bars:
            continue
        seen: dict[str, dict] = {}
        for b in bars:
            if not isinstance(b, dict):
                raise ValueError(f"{symbol}: bar is not a dict: {b!r}")
            missing = [k for k in BAR_KEYS if k not in b]
            if missing:
                raise ValueError(f"{symbol}: bar missing keys {missing}")
            d = str(b["date"])
            for k in ("open", "high", "low", "close", "volume"):
                v = b[k]
                if not isinstance(v, (int, float)) or v != v:  # NaN check
                    raise ValueError(f"{symbol} {d}: {k} is not a number: {v!r}")
            if b["close"] <= 0 or b["high"] <= 0 or b["low"] <= 0:
                raise ValueError(f"{symbol} {d}: non-positive price in bar")
            seen[d] = {k: b[k] for k in BAR_KEYS}
            seen[d]["date"] = d
        if seen:
            cleaned[str(symbol)] = [seen[d] for d in sorted(seen)]
    if not cleaned:
        raise ValueError("universe has no symbols with usable bars")
    return cleaned


def _trading_dates(start_iso: str, n: int) -> list[str]:
    """n consecutive weekdays starting at start_iso (synthetic calendar)."""
    y, m, d = (int(p) for p in start_iso.split("-"))
    cur = date(y, m, d)
    out: list[str] = []
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def demo_universe(
    seed: int = 7,
    n_days: int = 600,
    start: str = "2024-01-02",
) -> tuple[dict[str, list[dict]], dict[str, float]]:
    """Seeded 60-symbol demo universe with a planted regime arc.

    Three archetypes, 20 symbols each:

    - **leaders** (LDRxx): large caps, lower vol, stay positive longest
    - **followers** (FLWxx): mid caps, fade in the middle of the sample
    - **laggards** (LAGxx): small caps, higher vol, turn down first

    The planted arc: days 0-79 grinding bear market, days 80-99 crash
    (acceleration collapses participation), days 100-129 V-recovery led by
    laggards (the classic early-cycle snap-back — the breadth thrust fires
    here), days 130-299 sustained broad rally, days 300-449 narrowing
    (leaders keep climbing, followers stall, laggards fall), days 450-549
    fragile (leaders grind while everyone else bleeds), days 550+ the
    small/mid-cap washout accelerates while leaders go flat and the
    cap-weight index holds up.  A common market factor plus idiosyncratic
    noise keeps the cross-section correlated but not lockstep.

    Returns ``(universe, caps)`` with synthetic market caps per symbol.
    Deterministic for a fixed seed.  Illustrative only — not real data.
    """
    rng = random.Random(seed)
    dates = _trading_dates(start, n_days)

    # (drift, vol, beta) per archetype per phase, in ANNUALIZED units.
    # Crashes and V-recoveries live in daily-move units, so their annualized
    # drifts look extreme (-350% ~= -1.4%/day; +450% ~= +1.8%/day).
    # The planted arc: grinding bear -> crash (acceleration collapses
    # participation) -> V-recovery led by laggards (the classic early-cycle
    # snap-back; this is where the breadth thrust fires) -> broad rally ->
    # narrowing (only leaders advance) -> fragile (leaders grind with
    # elevated vol, everyone else falls while the cap-weight index holds up).
    phases = [
        (0, 80, {"LDR": (-0.10, 0.24, 1.1), "FLW": (-0.18, 0.30, 1.0), "LAG": (-0.28, 0.42, 0.9)}),
        (80, 100, {"LDR": (-3.5, 0.48, 1.1), "FLW": (-3.5, 0.60, 1.0), "LAG": (-3.5, 0.80, 0.9)}),
        (100, 130, {"LDR": (2.0, 0.40, 1.1), "FLW": (3.0, 0.50, 1.0), "LAG": (4.5, 0.65, 0.9)}),
        (130, 300, {"LDR": (0.12, 0.22, 1.1), "FLW": (0.15, 0.28, 1.0), "LAG": (0.18, 0.38, 0.9)}),
        (300, 450, {"LDR": (0.10, 0.22, 1.1), "FLW": (0.01, 0.28, 1.0), "LAG": (-0.08, 0.38, 0.9)}),
        (450, 550, {"LDR": (0.03, 0.28, 1.1), "FLW": (-0.25, 0.30, 1.0), "LAG": (-0.45, 0.38, 0.9)}),
        (550, n_days, {"LDR": (0.00, 0.30, 1.1), "FLW": (-0.60, 0.40, 1.0), "LAG": (-0.90, 0.50, 0.9)}),
    ]
    specs = {
        "LDR": {"n": 20, "px": (200.0, 400.0), "vol": (2_000_000.0, 8_000_000.0)},
        "FLW": {"n": 20, "px": (50.0, 150.0), "vol": (500_000.0, 3_000_000.0)},
        "LAG": {"n": 20, "px": (10.0, 60.0), "vol": (100_000.0, 1_000_000.0)},
    }

    universe: dict[str, list[dict]] = {}
    caps: dict[str, float] = {}
    for arch, spec in specs.items():
        for i in range(1, spec["n"] + 1):
            symbol = f"{arch}{i:02d}"
            price = rng.uniform(*spec["px"])
            base_vol = rng.uniform(*spec["vol"])
            if arch == "LDR" and i <= 3:
                caps[symbol] = [2.2e12, 1.8e12, 1.5e12][i - 1]
            elif arch == "LDR":
                caps[symbol] = rng.uniform(2.5e11, 6.0e11)
            elif arch == "FLW":
                caps[symbol] = rng.uniform(4.0e10, 1.5e11)
            else:
                caps[symbol] = rng.uniform(2.0e9, 2.0e10)
            bars: list[dict] = []
            prev_close = price
            for t, d in enumerate(dates):
                phase = next(p for p in phases if p[0] <= t < p[1])
                mu, sig, beta = phase[2][arch]
                market = rng.gauss(0.0, 0.01)          # common factor
                idio = rng.gauss(0.0, 1.0)
                r = mu / 252.0 + beta * market + (sig / (252.0 ** 0.5)) * idio
                o = prev_close
                c = o * (2.718281828459045 ** r)
                wiggle = abs(rng.gauss(0.0, 1.0)) * 0.003
                h = max(o, c) * (1.0 + wiggle)
                low = min(o, c) * (1.0 - wiggle)
                v = base_vol * (1.0 + 0.5 * abs(idio)) * (1.0 + 2.0 * abs(r))
                bars.append({"date": d, "open": o, "high": h, "low": low,
                             "close": c, "volume": v})
                prev_close = c
            universe[symbol] = bars
    return universe, caps
