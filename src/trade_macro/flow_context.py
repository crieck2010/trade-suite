"""Flow-context flags: "who is there to buy the dip?"

Two cheap, honest regime-*context* inputs inspired by the classic
market-microstructure observation that a dip without buyers is just a
falling price (corporate buybacks, systematic funds, options dealers,
pension rebalancing).  Of those four buyer types, two are computable from
free data with no fitted parameters — those are the two flags here:

- :func:`buyback_blackout` — calendar flag: US corporates are the largest
  consistent equity buyers, but SEC/issuer blackout policies sideline them
  around earnings season.  When the bid is sidelined, dips have less
  structural support.
- :func:`forced_selling_risk` — vol flag: vol-control / risk-parity funds
  mechanically delever when realized vol spikes and CTA trend-followers
  flip short below trend.  Both create *forced*, non-fundamental selling
  pressure.

These are CONTEXT for the graded-conviction decision layer / regime
arbiter (the "when"), alongside :mod:`trade_macro.regime`.  They are not
a strategy, they carry no entry/exit rules, and they change no strategy's
weights by themselves.  See :func:`trade_macro.adapters.flow_context_input`
for the digest shaped for ``trade-agents``' ``market_context`` merge.

No-look-ahead discipline: every window is trailing and inclusive of
``as_of`` — data at or before ``as_of`` only, never the future (see
``tests/test_flow_context.py::test_no_lookahead_*``).

Stdlib only.  Plain data in/out.  Research/backtesting/paper-trading only.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date


# ---------------------------------------------------------------------------
# Flag 1 — buyback blackout calendar
# ---------------------------------------------------------------------------

# Quarter-ends around which US earnings (and hence buyback blackouts) cluster.
_QUARTER_ENDS = ((3, 31), (6, 30), (9, 30), (12, 31))

# Heuristic windows, in days, relative to each quarter-end.  These are
# *documented approximations*, not fitted values:
#   - Issuer 10b5-1 / blackout policies typically bar repurchases from
#     ~4-6 weeks before quarter-end (the "4-6 week" range is the industry
#     convention; 5 weeks = 35 days sits in the middle of it).
#   - The bar lifts ~48h after the earnings release; with earnings
#     clustering 2-4 weeks after quarter-end, a 21-day post-quarter tail
#     covers the bulk of earnings season.
#   - The "deep" core (2 weeks before through 1 week after quarter-end) is
#     when the maximum share of the corporate bid is sidelined.
PRE_QUARTER_DAYS = 35   # blackout window opens this many days pre quarter-end
POST_QUARTER_DAYS = 21  # ... and closes this many days post quarter-end
DEEP_PRE_DAYS = 14      # "deep" core: peak sidelining starts here pre-QE
DEEP_POST_DAYS = 7       # ... and ends here post-QE

_SEVERITY_REASONS = {
    2: "deep buyback blackout",
    1: "buyback blackout shoulder",
    0: "no buyback blackout",
}


@dataclass(frozen=True)
class BuybackContext:
    """Calendar read on the corporate buyback bid for ``as_of``."""

    as_of: str                      # ISO date the read applies to
    in_blackout_window: bool        # True when the corporate bid is sidelined
    severity: int                   # 0 = active, 1 = shoulder, 2 = deep
    score: float                    # severity / 2 — 0.0, 0.5 or 1.0
    quarter: str                    # e.g. "2025-Q4": the quarter-end matched
    source: str                     # "calendar-heuristic" | "calendar+earnings-input"
    reason: str                     # human-readable

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "in_blackout_window": self.in_blackout_window,
            "severity": self.severity,
            "score": self.score,
            "quarter": self.quarter,
            "source": self.source,
            "reason": self.reason,
        }


def _as_date(value: date | str, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(f"{name}: expected date or ISO 'YYYY-MM-DD', "
                         f"got {value!r}") from None


def _add_days(d: date, n: int) -> date:
    from datetime import timedelta
    return d + timedelta(days=n)


def _quarter_end_dates(year: int) -> list[date]:
    return [date(year, m, d) for m, d in _QUARTER_ENDS]


def buyback_blackout(
    as_of: date | str,
    blackout_ranges: list[tuple[date | str, date | str]] | None = None,
) -> BuybackContext:
    """Calendar flag: is the corporate buyback bid sidelined on ``as_of``?

    Heuristic (no per-company data needed): a date is *in blackout* when it
    falls within ``[QE − 35d, QE + 21d]`` of any quarter-end, *deep* when
    within ``[QE − 14d, QE + 7d]``.  Constants are documented approximations
    above — conventions, not fitted values.

    ``blackout_ranges`` is the scaling slot: an optional list of
    ``(start, end)`` blackout windows from a real earnings calendar (e.g. a
    future ``trade-data-equities`` earnings-date adapter mapping each
    earnings date ``E`` to ``[E − 35d, E + 2d]``).  When supplied, any range
    covering ``as_of`` *confirms* the blackout (severity raised to 2) with
    zero changes to this flag's logic.
    """
    day = _as_date(as_of, "as_of")
    iso = day.isoformat()

    ranges: list[tuple[date, date]] = []
    if blackout_ranges:
        for i, (s, e) in enumerate(blackout_ranges):
            s_d, e_d = _as_date(s, f"blackout_ranges[{i}][0]"), _as_date(
                e, f"blackout_ranges[{i}][1]")
            if e_d < s_d:
                raise ValueError(
                    f"blackout_ranges[{i}]: end {e_d} before start {s_d}")
            ranges.append((s_d, e_d))

    severity, quarter, matched_qe = 0, "", None
    for yr in (day.year - 1, day.year, day.year + 1):
        for qe in _quarter_end_dates(yr):
            lo = _add_days(qe, -PRE_QUARTER_DAYS)
            hi = _add_days(qe, POST_QUARTER_DAYS)
            if lo <= day <= hi:
                deep = (_add_days(qe, -DEEP_PRE_DAYS)
                        <= day <= _add_days(qe, DEEP_POST_DAYS))
                sev = 2 if deep else 1
                if sev > severity:
                    severity, matched_qe = sev, qe
    if matched_qe is not None:
        quarter = f"{matched_qe.year}-Q{matched_qe.month // 3}"

    confirmed = any(s <= day <= e for s, e in ranges)
    source = "calendar-heuristic"
    if confirmed:
        severity = max(severity, 2)
        source = "calendar+earnings-input"

    in_window = severity > 0
    label = _SEVERITY_REASONS[severity]
    if severity == 0:
        reason = (f"{label}: {iso} is outside earnings-season blackout "
                  f"windows; the corporate bid is presumed active.")
    else:
        reason = (f"{label}: {iso} falls in the buyback blackout window "
                  f"around the {quarter} quarter-end "
                  f"([QE-{PRE_QUARTER_DAYS}d, QE+{POST_QUARTER_DAYS}d]); "
                  f"the corporate bid is structurally sidelined, so dips "
                  f"have less support.")
    if confirmed:
        reason += " Confirmed by a supplied earnings-calendar blackout range."

    return BuybackContext(
        as_of=iso,
        in_blackout_window=in_window,
        severity=severity,
        score=severity / 2.0,
        quarter=quarter,
        source=source,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Flag 2 — vol-spike forced-selling risk
# ---------------------------------------------------------------------------

# Minimum history: 63 baseline vol readings, each a 21-day realized vol,
# needing 83 log returns = 84 prices.  Fewer prices -> abstain (score 0.0),
# never a crash.
MIN_PRICES = 84
RV_WINDOW = 21          # realized-vol window (sessions)
BASELINE_WINDOW = 63   # baseline = median of this many trailing RV readings
TREND_WINDOW = 63      # medium-term trend = price vs trailing MA63
VOL_RATIO_THRESHOLD = 1.5  # "elevated" vol: 1.5x its own baseline.
# ^ A conventional choice (same family as Bollinger-style 1.5-2x bands),
#   documented here, NOT fitted to returns.
TRADING_DAYS = 252


@dataclass(frozen=True)
class ForcedSellingContext:
    """Vol-regime read for ``as_of``: is the tape under forced selling?"""

    as_of: str                 # ISO date the read applies to
    risk_score: float          # 0..1; linear ramp on vol_ratio (see docstring)
    elevated: bool             # score >= 0.5 AND price below trend
    realized_vol_21d: float | None   # annualized 21-day realized vol
    vol_ratio: float | None    # realized_vol_21d / 63-day median (None: n/a)
    below_trend: bool | None   # price < trailing 63-day MA (None: n/a)
    reason: str                # human-readable

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "risk_score": self.risk_score,
            "elevated": self.elevated,
            "realized_vol_21d": self.realized_vol_21d,
            "vol_ratio": self.vol_ratio,
            "below_trend": self.below_trend,
            "reason": self.reason,
        }


def _validate_price_series(series: list[dict], name: str = "series"
                            ) -> list[dict]:
    """Repo-convention price series: ``[{"date", "price"}]``, date-sorted.

    Raises ValueError on empty input, missing keys, non-finite or
    non-positive prices, or duplicate dates — the same discipline as
    :func:`trade_macro.series.validate_series`.
    """
    if not series:
        raise ValueError(f"{name}: empty series")
    clean: list[dict] = []
    for i, row in enumerate(series):
        if "date" not in row or "price" not in row:
            raise ValueError(f"{name}[{i}]: need 'date' and 'price' keys")
        price = row["price"]
        if (not isinstance(price, (int, float))
                or not math.isfinite(price)):
            raise ValueError(
                f"{name}[{i}]: price must be finite, got {price!r}")
        if price <= 0:
            raise ValueError(
                f"{name}[{i}]: price must be positive, got {price!r}")
        clean.append({"date": str(row["date"]), "price": float(price)})
    seen: set[str] = set()
    for row in clean:
        if row["date"] in seen:
            raise ValueError(f"{name}: duplicate date {row['date']!r}")
        seen.add(row["date"])
    clean.sort(key=lambda r: r["date"])
    return clean


def forced_selling_risk(
    series: list[dict],
    as_of: date | str | None = None,
) -> ForcedSellingContext:
    """Vol flag: is the market under *forced* (non-fundamental) selling?

    Takes the repo-standard price series (``[{"date", "price"}]``) and
    derives log returns internally, so callers never hand-roll returns
    (a classic look-ahead bug source).  Everything is trailing and
    inclusive of ``as_of`` — strictly data at or before ``as_of``.

    Definition:

    - ``rv21_t`` = sample stdev of daily log returns over the trailing 21
      sessions ending at ``t``, annualized (× √252).
    - ``baseline_t`` = median of the 63 trailing ``rv21`` readings ending
      at ``t`` — vol judged against *its own* recent norm.
    - ``vol_ratio_t = rv21_t / baseline_t``.
    - ``risk_score`` = ``clamp((vol_ratio − 1) / 1, 0, 1)``: a conventional
      linear ramp — 1.0× baseline scores 0, 1.5× scores 0.5, 2.0× scores
      1.0.  Documented convention, not fitted.
    - ``below_trend`` = close below its trailing 63-day simple MA
      (deleveraging pressure means *downside* vol, not upside vol).
    - ``elevated`` = ``risk_score >= 0.5`` **and** ``below_trend``.

    Insufficient history (< 84 prices) abstains: score 0.0, ``elevated``
    False, ``vol_ratio``/``below_trend`` None, reason "insufficient
    history" — never a crash.
    """
    rows = _validate_price_series(series, "series")
    day = _as_date(as_of, "as_of") if as_of is not None else None
    if day is not None:
        rows = [r for r in rows if r["date"] <= day.isoformat()]
    as_of_iso = rows[-1]["date"] if rows else (
        day.isoformat() if day else "")

    def abstain(why: str) -> ForcedSellingContext:
        return ForcedSellingContext(
            as_of=as_of_iso, risk_score=0.0, elevated=False,
            realized_vol_21d=None, vol_ratio=None, below_trend=None,
            reason=f"insufficient history: {why}.")

    if len(rows) < MIN_PRICES:
        return abstain(f"need >= {MIN_PRICES} prices, got {len(rows)}")

    prices = [r["price"] for r in rows]
    logrets = [math.log(prices[i] / prices[i - 1])
               for i in range(1, len(prices))]

    # Trailing 21-day realized vol, one reading per session (annualized).
    rv: list[float] = []
    for j in range(RV_WINDOW - 1, len(logrets)):
        window = logrets[j - RV_WINDOW + 1: j + 1]
        m = sum(window) / len(window)
        var = sum((v - m) ** 2 for v in window) / (len(window) - 1)
        rv.append(math.sqrt(var) * math.sqrt(TRADING_DAYS))

    baseline_readings = rv[-BASELINE_WINDOW:]
    if len(baseline_readings) < BASELINE_WINDOW:
        return abstain(f"need >= {BASELINE_WINDOW} vol readings, "
                       f"got {len(baseline_readings)}")
    baseline = statistics.median(baseline_readings)
    current_rv = rv[-1]

    if baseline <= 0:
        # Degenerate: vol was exactly zero for the whole baseline.
        if current_rv <= 0:
            vol_ratio, score = 1.0, 0.0
            ratio_note = "baseline vol is zero and current vol is zero"
        else:
            vol_ratio, score = None, 1.0
            ratio_note = ("baseline vol is zero while current vol is "
                          "positive — maximally abnormal")
    else:
        vol_ratio = current_rv / baseline
        score = min(1.0, max(0.0, (vol_ratio - 1.0) / 1.0))
        ratio_note = ""

    ma63 = sum(prices[-TREND_WINDOW:]) / TREND_WINDOW
    below = prices[-1] < ma63
    elevated = score >= 0.5 and below

    if vol_ratio is None:
        reason = (f"forced-selling risk maximal ({ratio_note}); price "
                  f"{'below' if below else 'above'} 63-day trend.")
    elif elevated:
        reason = (f"elevated forced-selling risk: 21-day realized vol "
                  f"{current_rv:.1%} is {vol_ratio:.2f}x its 63-day median "
                  f"baseline with price below its 63-day trend — "
                  f"vol-control deleveraging and CTA short-flip pressure, "
                  f"not fundamental selling.")
    elif score >= 0.5 and not below:
        reason = (f"vol spike without downside: realized vol "
                  f"{current_rv:.1%} is {vol_ratio:.2f}x baseline but price "
                  f"holds above its 63-day trend — upside vol, not forced "
                  f"selling.")
    else:
        reason = (f"no forced-selling pressure: 21-day realized vol "
                  f"{current_rv:.1%} is {vol_ratio:.2f}x its 63-day median "
                  f"baseline.")

    return ForcedSellingContext(
        as_of=as_of_iso,
        risk_score=score,
        elevated=elevated,
        realized_vol_21d=current_rv,
        vol_ratio=vol_ratio,
        below_trend=below,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Combined read
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FlowContext:
    """Both flags in one read — the unit the regime arbiter consumes."""

    as_of: str
    buyback: BuybackContext = field(repr=False)
    forced_selling: ForcedSellingContext = field(repr=False)

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "buyback": self.buyback.to_dict(),
            "forced_selling": self.forced_selling.to_dict(),
        }


def flow_context(
    series: list[dict],
    as_of: date | str | None = None,
    blackout_ranges: list[tuple[date | str, date | str]] | None = None,
) -> FlowContext:
    """Combined flow-context read for one date.

    ``series`` is the repo-standard price series (used by the vol flag);
    the buyback flag needs only the calendar date.  Pure function, no
    look-ahead (both flags see data at or before ``as_of`` only).

    When ``as_of`` is omitted, both flags anchor on the last date present
    in ``series`` — a single consistent read, never beyond available data.
    """
    fs = forced_selling_risk(series, as_of=as_of)
    bb = buyback_blackout(fs.as_of, blackout_ranges=blackout_ranges)
    return FlowContext(as_of=fs.as_of, buyback=bb, forced_selling=fs)
