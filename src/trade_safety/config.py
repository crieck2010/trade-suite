"""Safety kernel configuration.

Defaults are deliberately conservative and sized for the roadmap's
first-live pilot envelope ($250-$1,000). Every limit is explicit; nothing
in the kernel hard-codes a number that is not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .policy import ApprovalMode


@dataclass
class SafetyConfig:
    # --- Daily-loss circuit breaker -------------------------------------
    # Trip when session loss reaches the SMALLER of the two limits that
    # are set. A trip latches the E-Stop and locks out the session; a
    # manual E-Stop reset does NOT clear the lockout.
    max_daily_loss_pct: float | None = 0.02  # of session-start equity
    max_daily_loss_abs: float | None = 25.0  # dollars (pilot-scaled)

    # --- Order-size controls --------------------------------------------
    per_trade_cap_abs: float | None = 1_000.0  # max notional per order
    max_total_exposure_pct: float | None = 0.50  # of equity, incl. new order

    # --- Margin cushion (Moomoo IML proxy) --------------------------------
    # Block new risk-increasing orders when (equity - maintenance margin)
    # falls below this share of equity, staying clear of the broker's
    # forced-liquidation zone.
    min_margin_cushion_pct: float | None = 0.25

    # --- Approval policy ---------------------------------------------------
    approval_mode: ApprovalMode = ApprovalMode.APPROVE
    veto_window_s: float = 30.0
    # Approver object (see policy.py). None in APPROVE/VETO_WINDOW mode
    # means "no human channel wired" and every order is blocked.
    approver: Any = None

    # --- Watchdog ----------------------------------------------------------
    heartbeat_timeout_s: dict[str, float] = field(
        default_factory=lambda: {"opend": 45.0, "data": 90.0}
    )
    data_freshness_max_s: float = 120.0

    # --- Account identity --------------------------------------------------
    # If set, preflight requires the account id to end with these digits.
    expected_account_last4: str = ""
