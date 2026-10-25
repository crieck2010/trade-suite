"""Pre-flight checklist (live-roadmap Phase 1, item 5).

Run once per session before the first order. Any failure means no
trading that session, with the reason in the report (and the audit log,
when the caller writes it there). The checklist is pure: the caller
supplies the facts (connection state, account snapshot, data age,
market-open flag), so it is fully testable without a broker.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import SafetyConfig
from .kernel import SafetyKernel
from .models import AccountSnapshot

# The execution adapter's offline fallback reports this account id; in a
# REAL session it proves the numbers are simulated, not the broker's.
SIMULATED_ACCOUNT_ID = "moomoo-simulated"


@dataclass
class PreflightReport:
    passed: bool
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"{'PASS' if self.passed else 'FAIL'} preflight"]
        for name, ok, detail in self.checks:
            lines.append(f"  [{'x' if ok else ' '}] {name}: {detail}")
        return "\n".join(lines)


def run_preflight(
    *,
    env: str,  # "REAL" or "SIMULATE"
    connected: bool,
    account: AccountSnapshot | None,
    kernel: SafetyKernel,
    config: SafetyConfig,
    planned_notional: float | None = None,
    data_age_s: float | None = None,
    market_open: bool | None = None,
) -> PreflightReport:
    checks: list[tuple[str, bool, str]] = []
    is_real = env.upper() == "REAL"

    # E-Stop / breaker state
    checks.append(
        ("estop_clear", not kernel.state.estop_engaged, "E-Stop latch state")
    )
    checks.append(
        (
            "session_not_locked",
            not kernel.state.data["session"]["breaker_tripped"],
            "daily-loss breaker lockout state",
        )
    )

    # Gateway connection: mandatory for REAL; offline simulation is a
    # legitimate paper mode, so SIMULATE only notes it.
    if is_real:
        checks.append(("gateway_connected", connected, "OpenD must be connected for REAL"))
    else:
        checks.append(
            ("gateway_connected", True, "connected" if connected else "offline simulation (paper)")
        )

    # Account reality: in REAL the snapshot must be the broker's, never
    # the adapter's simulated fallback.
    if account is None:
        checks.append(("account_available", False, "no account snapshot"))
    elif is_real and account.account_id == SIMULATED_ACCOUNT_ID:
        checks.append(
            ("account_available", False, "account snapshot is the simulated fallback, not the broker's")
        )
    else:
        checks.append(("account_available", True, f"account {account.account_id}"))

    # Account identity (last-4) when configured
    if config.expected_account_last4:
        ok = bool(account) and str(account.account_id).endswith(config.expected_account_last4)
        checks.append(
            ("account_match", ok, f"expected account ending {config.expected_account_last4}")
        )

    # Buying power covers the planned first order, when sized
    if planned_notional is not None:
        ok = bool(account) and account.buying_power >= planned_notional
        checks.append(
            ("buying_power", ok, f"planned {planned_notional:.2f} vs buying power "
             f"{account.buying_power if account else 0:.2f}")
        )

    # Margin cushion above the kernel buffer
    if account is not None and config.min_margin_cushion_pct is not None and account.equity > 0:
        cushion_pct = account.margin_cushion / account.equity
        checks.append(
            (
                "margin_cushion",
                cushion_pct >= config.min_margin_cushion_pct,
                f"cushion {cushion_pct:.1%} vs minimum {config.min_margin_cushion_pct:.1%}",
            )
        )

    # Data freshness, when the caller measured it
    if data_age_s is not None:
        checks.append(
            (
                "data_fresh",
                data_age_s <= config.data_freshness_max_s,
                f"data age {data_age_s:.0f}s vs max {config.data_freshness_max_s:.0f}s",
            )
        )

    # Market open, when the caller checked a calendar
    if market_open is not None:
        checks.append(("market_open", market_open, "exchange calendar"))

    return PreflightReport(passed=all(ok for _, ok, _ in checks), checks=checks)
