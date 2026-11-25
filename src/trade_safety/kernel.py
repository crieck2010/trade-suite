"""The safety kernel: the single latch service every order must pass.

Live-roadmap Phase 1, item 1. An execution adapter consults
:meth:`SafetyKernel.check` before submitting any order. The kernel
evaluates, in order:

1. **E-Stop latch** — engaged means nothing trades, no exceptions.
2. **Daily-loss circuit breaker** — session loss (realized + unrealized,
   broker-reported) at or beyond the configured limit trips the E-Stop,
   alerts, and locks out the rest of the session. Resetting the E-Stop
   does not clear the lockout.
3. **Per-trade cap** — one order's notional may not exceed the cap.
   Market orders (unknown notional) are flagged, not silently passed.
4. **Total-exposure cap** — existing gross exposure + the new order may
   not exceed the configured share of equity.
5. **Margin cushion** — (equity − maintenance margin) / equity must stay
   at or above the configured buffer (Moomoo IML proxy; see
   docs/MOOMOO_EXECUTION_DECISION.md).
6. **Approval policy** — approve / veto-window / autonomous
   (see policy.py). Consulted last so a doomed order never pages a human.

Checks 3–5 are skipped for orders flagged ``reduces_exposure`` (closing
a position must never be blocked by a cap) — checks 1, 2 and 6 are not.

Every decision, trip, engagement and reset is written to the audit log.
The kernel is broker-agnostic: adapters translate their payloads into
``OrderIntent`` / ``AccountSnapshot``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from .alerts import NullAlertSink
from .audit import MemoryAuditWriter
from .config import SafetyConfig
from .models import AccountSnapshot, Decision, OrderIntent
from .policy import authorize
from .state import SafetyState

logger = logging.getLogger(__name__)


class SafetyKernel:
    def __init__(
        self,
        config: SafetyConfig | None = None,
        state: SafetyState | None = None,
        audit: Any = None,
        alert_sink: Any = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config or SafetyConfig()
        self.state = state or SafetyState()
        self.audit = audit or MemoryAuditWriter()
        self.alerts = alert_sink or NullAlertSink()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Time / session
    # ------------------------------------------------------------------
    def _now(self) -> datetime:
        return self._clock()

    def _today(self) -> str:
        return self._now().date().isoformat()

    def update_session(self, account: AccountSnapshot) -> None:
        """Roll the session record over at day boundaries; latch start equity."""
        session = self.state.data["session"]
        if session["date"] != self._today():
            session["date"] = self._today()
            session["start_equity"] = account.equity
            session["breaker_tripped"] = False
            session["orders_allowed"] = 0
            session["orders_blocked"] = 0
            self.state.save()

    def daily_loss_limit(self) -> float | None:
        """The binding daily-loss limit in dollars (smaller of configured)."""
        session = self.state.data["session"]
        limits: list[float] = []
        if self.config.max_daily_loss_abs is not None:
            limits.append(self.config.max_daily_loss_abs)
        if self.config.max_daily_loss_pct is not None and session["start_equity"] > 0:
            limits.append(self.config.max_daily_loss_pct * session["start_equity"])
        return min(limits) if limits else None

    # ------------------------------------------------------------------
    # E-Stop
    # ------------------------------------------------------------------
    def engage_estop(self, actor: str, reason: str) -> None:
        self.state.engage_estop(actor=actor, reason=reason, at_iso=self._now().isoformat())
        self.audit.write("SAFETY_ESTOP_ENGAGED", {"actor": actor, "reason": reason})
        self.alerts.send("E-STOP ENGAGED", f"actor={actor} reason={reason}")
        logger.warning("SafetyKernel E-STOP engaged by %s: %s", actor, reason)

    def reset_estop(self, actor: str) -> None:
        if not actor:
            raise ValueError("E-Stop reset requires an actor (no anonymous resets)")
        self.state.reset_estop(at_iso=self._now().isoformat())
        self.audit.write("SAFETY_ESTOP_RESET", {"actor": actor})
        self.alerts.send("E-Stop reset", f"actor={actor}")
        logger.info("SafetyKernel E-STOP reset by %s", actor)

    # ------------------------------------------------------------------
    # Heartbeats (watchdog reads these)
    # ------------------------------------------------------------------
    def beat(self, source: str) -> None:
        self.state.beat(source, self._now().isoformat())

    def heartbeat_age_s(self, source: str) -> float | None:
        last = self.state.last_beat(source)
        if last is None:
            return None
        try:
            last_dt = datetime.fromisoformat(last)
        except ValueError:
            return None
        return (self._now() - last_dt).total_seconds()

    # ------------------------------------------------------------------
    # Circuit breaker
    # ------------------------------------------------------------------
    def evaluate_breaker(self, account: AccountSnapshot) -> bool:
        """Trip the breaker if the session loss is at/over the limit.

        Returns True when the breaker is tripped (now or previously
        this session).
        """
        self.update_session(account)
        session = self.state.data["session"]
        if session["breaker_tripped"]:
            return True
        limit = self.daily_loss_limit()
        if limit is None:
            return False
        if account.session_loss >= limit:
            session["breaker_tripped"] = True
            self.state.save()
            self.audit.write(
                "SAFETY_BREAKER_TRIP",
                {
                    "session_loss": account.session_loss,
                    "limit": limit,
                    "start_equity": session["start_equity"],
                },
            )
            self.engage_estop(
                actor="safety_kernel",
                reason=f"daily_loss_breaker: loss {account.session_loss:.2f} >= limit {limit:.2f}",
            )
            return True
        return False

    # ------------------------------------------------------------------
    # The gate
    # ------------------------------------------------------------------
    def check(self, intent: OrderIntent, account: AccountSnapshot) -> Decision:
        self.update_session(account)
        decision = Decision(allowed=True)
        cfg = self.config

        # 1. E-Stop latch
        estop = self.state.data["estop"]
        decision.checks["estop_clear"] = not self.state.estop_engaged
        if self.state.estop_engaged:
            decision.reasons.append(
                f"E-Stop engaged by {estop['actor']}: {estop['reason']}"
            )

        # 2. Daily-loss breaker (may trip right now)
        tripped = self.evaluate_breaker(account)
        decision.checks["breaker_clear"] = not tripped
        if tripped:
            decision.reasons.append("daily-loss breaker tripped; session locked out")

        # 3–5. Size / exposure / cushion (skipped for exposure-reducing orders)
        notional = intent.notional
        if intent.reduces_exposure:
            decision.notes.append("reduces_exposure: cap/cushion checks skipped")
            decision.checks["per_trade_cap"] = True
            decision.checks["exposure_cap"] = True
            decision.checks["margin_cushion"] = True
        else:
            if notional is None:
                decision.checks["per_trade_cap"] = True
                decision.notes.append("notional unverifiable (market order); per-trade cap not applied")
            elif cfg.per_trade_cap_abs is not None and notional > cfg.per_trade_cap_abs:
                decision.checks["per_trade_cap"] = False
                decision.reasons.append(
                    f"per-trade cap: notional {notional:.2f} > cap {cfg.per_trade_cap_abs:.2f}"
                )
            else:
                decision.checks["per_trade_cap"] = True

            if cfg.max_total_exposure_pct is not None and account.equity > 0:
                projected = account.gross_exposure + (notional or 0.0)
                limit = cfg.max_total_exposure_pct * account.equity
                decision.checks["exposure_cap"] = projected <= limit
                if projected > limit:
                    decision.reasons.append(
                        f"exposure cap: projected {projected:.2f} > {limit:.2f} "
                        f"({cfg.max_total_exposure_pct:.0%} of equity)"
                    )
            else:
                decision.checks["exposure_cap"] = True

            if cfg.min_margin_cushion_pct is not None and account.equity > 0:
                cushion_pct = account.margin_cushion / account.equity
                decision.checks["margin_cushion"] = cushion_pct >= cfg.min_margin_cushion_pct
                if cushion_pct < cfg.min_margin_cushion_pct:
                    decision.reasons.append(
                        f"margin cushion {cushion_pct:.1%} < minimum {cfg.min_margin_cushion_pct:.1%} "
                        "(IML proxy; broker forced-liquidation zone)"
                    )
            else:
                decision.checks["margin_cushion"] = True

        # 6. Approval policy — only if nothing else already doomed the order
        if not decision.reasons:
            ok, detail = authorize(
                cfg.approval_mode, cfg.approver, intent, cfg.veto_window_s
            )
            decision.checks["approval"] = ok
            if ok:
                decision.notes.append(f"approval: {detail}")
            else:
                decision.reasons.append(f"approval: {detail}")
        else:
            decision.checks["approval"] = False

        decision.allowed = not decision.reasons
        session = self.state.data["session"]
        if decision.allowed:
            session["orders_allowed"] += 1
        else:
            session["orders_blocked"] += 1
        self.state.save()

        self.audit.write(
            "SAFETY_CHECK_PASS" if decision.allowed else "SAFETY_CHECK_BLOCK",
            {
                "symbol": intent.symbol,
                "action": intent.action,
                "quantity": intent.quantity,
                "price": intent.price,
                "strategy": intent.strategy,
                "notional": notional,
                "reasons": decision.reasons,
                "checks": decision.checks,
            },
        )
        return decision
