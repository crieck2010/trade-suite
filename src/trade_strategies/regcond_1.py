"""REGCOND-1: copper:gold regime-conditioned cross-asset allocation (production implementation).

Frozen specification: ``docs/validation/regcond-1/PRE-REGISTRATION.md`` (trial 4).
Validation record: ``docs/validation/regcond-1/tier1_evidence.json``
(Tier-1 5/5 under ``docs/validation/GATES.md``; trade-lifecycle status PAPER).

The maths
----------
1. Each day, take CPER (copper ETN) and GLD (gold) closes and form the
   copper:gold ratio ``r_t = log(CPER_t / GLD_t)``.
2. Standardise the ratio against its own 252-trading-day rolling window
   (``z_252 = (r_t - mean_252) / std_252``) and compare it with its
   200-day moving average (``MA200``).
3. Raw signal: ``EXPANSION`` if ``z_252 > 1`` and ``r_t > MA200``;
   ``CONTRACTION`` if ``z_252 < -1`` and ``r_t < MA200``; else ``NEUTRAL``.
   (Computed by ``trade_macro.ratio`` / ``trade_macro.regime`` with the
   ``"standard"`` preset — z threshold 1.0, 5-session persistence.)
4. Persisted label: a raw-signal change only takes effect after it has
   held for five consecutive sessions (whipsaw control).  The persisted
   label starts at NEUTRAL.
5. On the first trading day of each month, read the persisted label as of
   the previous month's final trading day and set fixed target weights::

       EXPANSION:    SPY 60% / CPER 20% / TLT 20% / GLD 0%
       CONTRACTION:  SPY 20% / CPER  0% / TLT 40% / GLD 40%
       NEUTRAL:      SPY 25% / CPER 25% / TLT 25% / GLD 25%

   Long-only, fully invested.  Positions are filled at the next session's
   open; costs are 5 bps per side.  The warmup window opens 2015-01-01 and
   the trade window 2018-01-01 (the validated window runs to 2026-09-25).

Signal contract
---------------
The common ``Signal`` object carries only direction and a 0-1 ``strength``.
REGCOND-1 uses a *documented extension* of that contract for target-weight
strategies: when a ``regcond_1`` signal has action ``LONG``, ``strength``
is the **target portfolio weight** (e.g. 0.60 for SPY in EXPANSION); an
``EXIT`` signal means target weight 0 (liquidate that leg).  The strategy
emits signals only on rebalance days (the first trading day of a month);
the four signals of a rebalance always sum to 1.0 (modulo float rounding).

The universe is frozen: the strategy raises ``ValueError`` unless it is
constructed with exactly ``("SPY", "CPER", "TLT", "GLD")`` (any order,
any case).  trade-macro is imported lazily so the strategies package
keeps its existing dependency boundary.
"""

from __future__ import annotations

from datetime import date, datetime

from .base import Signal, SignalAction, Strategy, field, timestamp_of

#: Frozen strategy universe (registry name ``regcond_1``).
SYMBOLS = ("SPY", "CPER", "TLT", "GLD")

#: Frozen target weights by persisted regime label.  Always sums to 1.0.
WEIGHTS: dict[str, dict[str, float]] = {
    "EXPANSION": {"SPY": 0.60, "CPER": 0.20, "TLT": 0.20, "GLD": 0.00},
    "CONTRACTION": {"SPY": 0.20, "CPER": 0.00, "TLT": 0.40, "GLD": 0.40},
    "NEUTRAL": {"SPY": 0.25, "CPER": 0.25, "TLT": 0.25, "GLD": 0.25},
}

#: Frozen design constants.
RATIO_NUMERATOR = "CPER"
RATIO_DENOMINATOR = "GLD"
REGIME_PRESET = "standard"
WARMUP_BARS = 260  # ~one trading year; matches the validated warmup


def _trade_macro_label(cu_rows: list[dict], au_rows: list[dict]) -> str:
    """Persisted copper:gold regime label via the frozen trade-macro pipeline.

    ``cu_rows``/``au_rows`` are ``[{"date": "YYYY-MM-DD", "price": float}]``.
    Returns the persisted label for the final input date.
    """
    from trade_macro.ratio import ratio_series, enrich_ratios
    from trade_macro.regime import classify_regime

    rows = classify_regime(
        enrich_ratios(ratio_series(cu_rows, au_rows)), preset=REGIME_PRESET
    )
    return rows[-1]["regime"] if rows else "NEUTRAL"


class RegCond1(Strategy):
    """Monthly copper:gold regime tilt across SPY/CPER/TLT/GLD.

    See the module docstring for the frozen maths and the target-weight
    ``Signal`` contract.  The class carries ``production = True``: it is the
    executable form of lifecycle candidate REGCOND-1 and is runnable by the
    pointed trade-paper production path (delta-vs-position rebalancing),
    unlike the research scouts which only emit directional ideas.
    """

    name = "regcond_1"
    family = "regime"
    description = (
        "Monthly copper:gold regime tilt: fixed target weights across "
        "SPY/CPER/TLT/GLD, rebalanced on the first trading day of each month."
    )
    DEFAULT_PARAMS: dict = {}  # frozen: no tunable parameters
    production = True

    def __init__(self, symbols: list[str], **params) -> None:
        if params:
            raise ValueError(
                f"regcond_1 is frozen and takes no parameters, got {sorted(params)}"
            )
        want = set(SYMBOLS)
        got = {str(s).upper() for s in symbols}
        if got != want:
            raise ValueError(
                f"regcond_1 requires exactly the frozen universe {sorted(want)}, "
                f"got {sorted(got)}"
            )
        super().__init__(symbols, **params)
        # Daily close history per symbol, ascending: list of (date, close).
        self._closes: dict[str, list[tuple[date, float]]] = {
            s: [] for s in SYMBOLS
        }
        self._prev_date: date | None = None
        #: Persisted regime label as of the most recently processed bar.
        self._label = "NEUTRAL"
        #: Public audit trail: date -> persisted label for every processed bar.
        self.label_history: dict[date, str] = {}

    @property
    def warmup_bars(self) -> int:
        return WARMUP_BARS

    def _on_new_close(self, sym: str, day: date, close: float) -> None:
        hist = self._closes[sym]
        if hist and hist[-1][0] == day:
            hist[-1] = (day, close)
        else:
            hist.append((day, close))

    def _persisted_label(self) -> str:
        cu = [
            {"date": d.isoformat(), "price": p}
            for d, p in self._closes[RATIO_NUMERATOR]
        ]
        au = [
            {"date": d.isoformat(), "price": p}
            for d, p in self._closes[RATIO_DENOMINATOR]
        ]
        return _trade_macro_label(cu, au)

    def on_bar(self, timestamp: datetime, bars: dict[str, dict]) -> list[Signal]:
        day = timestamp.date()
        for sym in SYMBOLS:
            bar = bars.get(sym)
            if bar is None:
                # D3 hold policy: a missing leg reuses its last known close,
                # so the ratio (and label) carry forward like the validation.
                hist = self._closes[sym]
                if hist:
                    self._on_new_close(sym, day, hist[-1][1])
                continue
            self._on_new_close(sym, day, float(bar["close"]))

        rebalance = (
            self._prev_date is not None
            and (self._prev_date.year, self._prev_date.month) != (day.year, day.month)
        )
        # The rebalance decision reads the persisted label as of the *prior*
        # bar — i.e. the previous month's final trading day (D4).
        decision_label = self._label
        self._label = self._persisted_label()
        self.label_history[day] = self._label
        self._prev_date = day

        if not rebalance or len(self._closes[SYMBOLS[0]]) < WARMUP_BARS:
            return []
        weights = WEIGHTS[decision_label]
        signals: list[Signal] = []
        for sym, w in weights.items():
            if w > 0:
                signals.append(
                    Signal(
                        symbol=sym,
                        timestamp=timestamp,
                        action=SignalAction.LONG,
                        strength=w,
                    )
                )
            else:
                signals.append(
                    Signal(
                        symbol=sym,
                        timestamp=timestamp,
                        action=SignalAction.EXIT,
                    )
                )
        return signals
