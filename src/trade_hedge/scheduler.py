"""The scheduled loop: run_cycle(portfolio_state, market_state, config,
loop_state) -> {exposures, proposals, diagnostics, alerts, halted,
state_snapshot}.

Idempotent by design: identical inputs produce identical outputs. The only
state the loop carries is an explicit, JSON-serializable LoopState that the
CALLER threads through — never hidden module globals. This is what makes the
loop safe to run on a schedule (3x daily like trade-paper's runner, or every
N minutes) and what lets it parallelize across portfolios later without
signature changes: one LoopState per portfolio.

The loop NEVER places orders. Proposals are emitted; trade-paper's approval
queue (with the user as the final gate) is what can act on them.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json

from .exposures import compute_exposures
from .hedges import propose_hedges
from .safety import safety_check


class LoopState(dict):
    """Explicit, serializable loop memory. Thread through run_cycle.

    Keys used: "last_cycle_ts" (ISO), "last_proposal_signature" (str),
    "cycles_run" (int), "consecutive_halts" (int).
    """

    def snapshot(self) -> dict:
        return dict(self)


def _proposal_signature(proposals: list[dict]) -> str:
    parts = sorted(
        f'{p.get("rule_id")}|{p.get("instrument")}|{p.get("qty")}|{p.get("action")}'
        for p in proposals
    )
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def run_cycle(
    portfolio_state: dict,
    market_state: dict,
    config: dict | None = None,
    loop_state: LoopState | dict | None = None,
) -> dict:
    config = config or {}
    state = LoopState(loop_state or {})

    check = safety_check(portfolio_state, market_state, config)
    alerts = list(check["alerts"])

    exposures = compute_exposures(
        portfolio_state.get("positions", []),
        market_state.get("prices", {}),
        config,
    )

    proposals: list[dict] = []
    diagnostics: dict = {}
    if check["halted"]:
        alerts.append("cycle halted: zero proposals emitted")
    else:
        proposals, diagnostics = propose_hedges(exposures, config, market_state)

    signature = _proposal_signature(proposals)
    changed = signature != state.get("last_proposal_signature")

    new_state = LoopState({
        "last_cycle_ts": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(),
        "last_proposal_signature": signature,
        "cycles_run": int(state.get("cycles_run", 0)) + 1,
        "consecutive_halts": (int(state.get("consecutive_halts", 0)) + 1
                              if check["halted"] else 0),
    })

    return {
        "exposures": exposures,
        "proposals": proposals,
        "diagnostics": diagnostics,
        "alerts": alerts,
        "halted": check["halted"],
        "changed_since_last": changed,
        "state_snapshot": new_state.snapshot(),
    }


def state_to_json(state: dict) -> str:
    """Serialize a LoopState for persistence between scheduled runs."""
    return json.dumps(state, indent=2, sort_keys=True)


def state_from_json(payload: str) -> LoopState:
    return LoopState(json.loads(payload))
