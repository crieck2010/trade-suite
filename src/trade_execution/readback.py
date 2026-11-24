"""Read-back verification after order placement (stolen pattern, 2026-11-24).

Pattern source: an r/ai_trading desk write-up Charlie reviewed on
2026-11-24 — after its controller placed an order, it read back what
the exchange had actually armed instead of trusting the submit call.

That is the rule here: **a submit response is a claim, not a fact.**
``place_order`` returning success says the gateway accepted a request;
it does not prove the order exists at the broker in the state the
caller believes. :func:`verify_execution` re-queries the broker's own
order list and compares what is actually there — presence, status,
filled quantity — against the expectation, and reports every mismatch
explicitly. Callers (the 0DTE runner above all) should treat an
unverified order the way the safety kernel treats a failed gate: stop
and surface it, never assume it.

Broker vocabularies differ, so rows are normalised into a small
canonical status set (``FILLED`` / ``PARTIAL`` / ``WORKING`` /
``CANCELLED`` / ``FAILED`` / ``UNKNOWN``) with the raw status kept on
the view for the audit trail. The normaliser tolerates the key
spellings of both the Moomoo/Futu order dicts (``order_status``,
``dealt_qty``, ``dealt_avg_price``) and this package's own simulated
rows (``status``, ``filled_qty``, ``avg_price``).

Pure functions over plain rows: any source that can produce order
dicts works — an adapter's ``query_orders()``, a test stub, a recorded
fixture. Polling is bounded and injectable (``attempts``, ``delay_s``,
``sleep``) so tests never wait.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .models import ExecutionResult, utcnow_str

logger = logging.getLogger(__name__)

# Canonical statuses.
FILLED = "FILLED"
PARTIAL = "PARTIAL"
WORKING = "WORKING"
CANCELLED = "CANCELLED"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"

TERMINAL_STATUSES = frozenset({FILLED, CANCELLED, FAILED})

_STATUS_MAP = {
    "FILLED": FILLED,
    "FILLED_ALL": FILLED,
    "FILL_ALL": FILLED,
    "COMPLETE": FILLED,
    "COMPLETED": FILLED,
    "FILLED_PART": PARTIAL,
    "PARTIALLY_FILLED": PARTIAL,
    "PARTIAL": PARTIAL,
    "SUBMITTED": WORKING,
    "SUBMITTING": WORKING,
    "SUBMITTED_NO_MSG": WORKING,
    "NEW": WORKING,
    "PENDING": WORKING,
    "WORKING": WORKING,
    "UNFILLED": WORKING,
    "WAITING_SUBMIT": WORKING,
    "NONE": WORKING,
    "CANCELLED_ALL": CANCELLED,
    "CANCELLED": CANCELLED,
    "CANCELED": CANCELLED,
    "CANCELLED_PART": CANCELLED,
    "FAILED": FAILED,
    "REJECTED": FAILED,
    "DELETED": FAILED,
    "DISABLED": FAILED,
}

_ID_KEYS = ("order_id", "id")
_STATUS_KEYS = ("order_status", "status")
_FILLED_KEYS = ("dealt_qty", "filled_qty", "qty_dealt")
_AVG_PRICE_KEYS = ("dealt_avg_price", "avg_price", "dealt_price")
_SYMBOL_KEYS = ("code", "symbol")


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def canonical_status(raw: Any) -> str:
    """Map a broker status string onto the canonical set."""
    if raw is None:
        return UNKNOWN
    return _STATUS_MAP.get(str(raw).strip().upper(), UNKNOWN)


@dataclass(frozen=True)
class OrderStateView:
    """One broker order row, normalised."""

    order_id: str
    status: str  # canonical
    raw_status: str
    filled_qty: float = 0.0
    avg_price: float = 0.0
    symbol: str = ""


def normalize_order_row(row: dict[str, Any]) -> OrderStateView | None:
    """Normalise one broker order dict; None when it carries no order id."""
    order_id = _first(row, _ID_KEYS)
    if order_id is None or str(order_id) == "":
        return None
    raw_status = _first(row, _STATUS_KEYS)
    filled = _first(row, _FILLED_KEYS)
    avg = _first(row, _AVG_PRICE_KEYS)
    symbol = _first(row, _SYMBOL_KEYS)
    return OrderStateView(
        order_id=str(order_id),
        status=canonical_status(raw_status),
        raw_status="" if raw_status is None else str(raw_status),
        filled_qty=float(filled) if filled is not None else 0.0,
        avg_price=float(avg) if avg is not None else 0.0,
        symbol="" if symbol is None else str(symbol),
    )


@dataclass
class ReadbackReport:
    """Outcome of one read-back verification."""

    order_id: str
    found: bool
    verified: bool
    observed: OrderStateView | None = None
    mismatches: list[str] = field(default_factory=list)
    attempts_used: int = 1
    checked_at: str = field(default_factory=utcnow_str)

    def summary(self) -> str:
        if not self.found:
            return f"order {self.order_id}: NOT FOUND at broker on read-back"
        obs = self.observed
        base = (
            f"order {self.order_id}: {obs.status} (raw {obs.raw_status!r}), "
            f"filled {obs.filled_qty:g} @ {obs.avg_price:g}"
        )
        if self.verified:
            return base + " — verified"
        return base + f" — MISMATCH: {'; '.join(self.mismatches)}"


def verify_readback(
    rows: Iterable[dict[str, Any]],
    order_id: str,
    *,
    expect_statuses: Iterable[str] | None = None,
    expect_filled_qty: float | None = None,
) -> ReadbackReport:
    """Verify one order against one snapshot of broker order rows.

    Verified means: the order is present, its canonical status is in
    ``expect_statuses`` (default: any status except FAILED — presence
    in a non-failed state is the baseline claim a submit makes), and
    its filled quantity equals ``expect_filled_qty`` when one is given.
    Every failed expectation is named in ``mismatches``.
    """
    observed: OrderStateView | None = None
    for row in rows:
        view = normalize_order_row(row)
        if view is not None and view.order_id == str(order_id):
            observed = view
            break
    if observed is None:
        return ReadbackReport(
            order_id=str(order_id),
            found=False,
            verified=False,
            mismatches=["order not present in broker order list"],
        )

    acceptable = (
        {canonical_status(s) for s in expect_statuses}
        if expect_statuses is not None
        else {FILLED, PARTIAL, WORKING, CANCELLED}
    )
    mismatches: list[str] = []
    if observed.status not in acceptable:
        mismatches.append(
            f"status {observed.status} (raw {observed.raw_status!r}) "
            f"not in expected {sorted(acceptable)}"
        )
    if expect_filled_qty is not None and observed.filled_qty != expect_filled_qty:
        mismatches.append(
            f"filled_qty {observed.filled_qty:g} != expected {expect_filled_qty:g}"
        )
    return ReadbackReport(
        order_id=str(order_id),
        found=True,
        verified=not mismatches,
        observed=observed,
        mismatches=mismatches,
    )


def verify_execution(
    source: Any,
    result: ExecutionResult,
    *,
    expect_statuses: Iterable[str] | None = None,
    expect_filled_qty: float | None = None,
    attempts: int = 1,
    delay_s: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> ReadbackReport:
    """Read back a placed order from its broker source and verify it.

    ``source`` is anything with ``query_orders()`` returning order
    dicts (e.g. :class:`MoomooExecutionAdapter`), or a zero-arg callable
    returning the rows. Polls up to ``attempts`` times, stopping early
    once verified or once the observed status is terminal — a terminal
    mismatch will not heal by waiting.
    """
    fetch: Callable[[], Iterable[dict[str, Any]]]
    if hasattr(source, "query_orders"):
        fetch = source.query_orders
    elif callable(source):
        fetch = source
    else:
        raise TypeError("source must expose query_orders() or be a callable returning rows")

    report: ReadbackReport | None = None
    for attempt in range(1, max(1, attempts) + 1):
        report = verify_readback(
            fetch(),
            result.order_id,
            expect_statuses=expect_statuses,
            expect_filled_qty=expect_filled_qty,
        )
        report.attempts_used = attempt
        if report.verified:
            break
        if report.observed is not None and report.observed.status in TERMINAL_STATUSES:
            break
        if attempt < attempts and delay_s > 0:
            sleep(delay_s)
    assert report is not None
    if report.verified:
        logger.info("Read-back verified: %s", report.summary())
    else:
        logger.error("Read-back FAILED: %s", report.summary())
    return report
