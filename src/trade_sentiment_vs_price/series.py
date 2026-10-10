"""Time-series containers and alignment.

Sentiment arrives irregularly (some days have no mentions); prices are
regular trading days.  Everything downstream works on aligned
``(dates, sentiment, returns)`` triples built by ``align`` — inner join
on date, returns as simple close-to-close changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SentimentPoint:
    date: str            # "YYYY-MM-DD"
    symbol: str
    bullishness: float   # 0..10, trade-sentiment scale
    conviction: float    # 0..10
    mentions: int = 0


@dataclass
class PriceBar:
    date: str
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None


@dataclass
class AlignedSeries:
    symbol: str
    dates: list[str]
    bullishness: list[float]
    conviction: list[float]
    mentions: list[int]
    closes: list[float]
    returns: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.returns and len(self.closes) > 1:
            self.returns = [self.closes[i] / self.closes[i - 1] - 1.0
                            for i in range(1, len(self.closes))]
            # returns[i] aligns with dates[i+1]; drop the first date slot
            # from return-paired views via paired_returns().
        n = len(self.dates)
        for name in ("bullishness", "conviction", "mentions", "closes"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"{name} length mismatch")

    def paired_returns(self) -> tuple[list[str], list[float]]:
        """(dates[1:], returns) — returns aligned to their end date."""
        return self.dates[1:], self.returns


def align(symbol: str, sentiment: list[SentimentPoint],
          prices: list[PriceBar]) -> AlignedSeries:
    """Inner-join sentiment and prices on date, sorted ascending."""
    smap = {p.date: p for p in sentiment if p.symbol == symbol}
    pmap = {b.date: b for b in prices}
    dates = sorted(set(smap) & set(pmap))
    if len(dates) < 2:
        raise ValueError("need at least 2 overlapping dates")
    s = [smap[d] for d in dates]
    return AlignedSeries(
        symbol=symbol,
        dates=dates,
        bullishness=[p.bullishness for p in s],
        conviction=[p.conviction for p in s],
        mentions=[p.mentions for p in s],
        closes=[pmap[d].close for d in dates],
    )


def net_sentiment(bullishness: list[float]) -> list[float]:
    """Bull-bear spread on the 0..10 scale → −10..+10."""
    return [b - 5.0 for b in bullishness]


def demo_data(n_days: int = 180, seed: int = 11, lead: int = 1,
              symbol: str = "DEMO") -> tuple[list[SentimentPoint], list[PriceBar]]:
    """Synthetic pair where sentiment leads returns by ``lead`` days.

    Sentiment follows a slow AR(1); returns load on lagged sentiment change
    plus noise.  The lead/lag tool should recover ``lead``.
    """
    import random
    rng = random.Random(seed)
    dates, m, d = [], 1, 1
    while len(dates) < n_days:
        dates.append(f"2026-{m:02d}-{d:02d}")
        d += 1
        if d > 28:
            d, m = 1, m + 1
        if m > 12:
            m = 1
    bull, s = [], 5.0
    for _ in range(n_days):
        s = 0.9 * s + 0.1 * 5.0 + rng.gauss(0, 0.8)
        bull.append(min(10.0, max(0.0, s)))
    rets = []
    for t in range(n_days):
        drive = (bull[t - lead] - 5.0) / 5.0 if t - lead >= 0 else 0.0
        rets.append(0.02 * drive + rng.gauss(0, 0.015))
    closes, px = [], 100.0
    for r in rets:
        px *= 1 + r
        closes.append(px)
    sent = [SentimentPoint(d, symbol, b, 5.0 + abs(b - 5.0),
                           max(1, int(20 + 10 * abs(b - 5.0) + rng.gauss(0, 5))))
            for d, b in zip(dates, bull)]
    bars = [PriceBar(d, c) for d, c in zip(dates, closes)]
    return sent, bars
