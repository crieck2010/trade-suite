"""Approval policy engine (live-roadmap Phase 1, item 4).

Three modes, selectable per deployment (and per strategy, by building
one kernel per strategy):

- ``APPROVE``     — a human must approve each order before it proceeds.
- ``VETO_WINDOW`` — orders proceed unless a human vetoes within a window.
- ``AUTONOMOUS``  — no per-order human step (paper campaigns first; the
  roadmap gates when this mode may be used with real money).

An ``Approver`` is the human channel (Mattermost gateway, dashboard,
test double). With no approver wired, APPROVE and VETO_WINDOW block
every order: absence of a channel is a stop, not a pass.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol


class ApprovalMode(str, Enum):
    APPROVE = "approve"
    VETO_WINDOW = "veto_window"
    AUTONOMOUS = "autonomous"


class Approver(Protocol):
    """Human-authorization channel used by the policy engine."""

    def request_approval(self, intent: Any) -> bool:
        """APPROVE mode: True only on an explicit human yes."""
        ...

    def check_veto(self, intent: Any, window_s: float) -> bool:
        """VETO_WINDOW mode: True if a human vetoed within the window."""
        ...


class AutoApprover:
    """Approver that always says yes / never vetoes.

    For paper-trading drills and tests. Using it with real money is a
    policy decision for Charlie, recorded wherever it is configured.
    """

    def request_approval(self, intent: Any) -> bool:
        return True

    def check_veto(self, intent: Any, window_s: float) -> bool:
        return False


class CallbackApprover:
    """Approver backed by plain callables (tests, CLI prompts, drills)."""

    def __init__(self, approve_fn=None, veto_fn=None) -> None:
        self._approve_fn = approve_fn
        self._veto_fn = veto_fn

    def request_approval(self, intent: Any) -> bool:
        if self._approve_fn is None:
            return False
        return bool(self._approve_fn(intent))

    def check_veto(self, intent: Any, window_s: float) -> bool:
        if self._veto_fn is None:
            return False
        return bool(self._veto_fn(intent, window_s))


def authorize(
    mode: ApprovalMode,
    approver: Approver | None,
    intent: Any,
    veto_window_s: float,
) -> tuple[bool, str]:
    """Return (allowed, human-readable detail) for one order intent."""
    if mode == ApprovalMode.AUTONOMOUS:
        return True, "autonomous mode: no per-order human step"
    if approver is None:
        return False, f"{mode.value} mode: no approver channel configured"
    if mode == ApprovalMode.APPROVE:
        ok = approver.request_approval(intent)
        return ok, "human approved" if ok else "human approval not granted"
    # VETO_WINDOW
    vetoed = approver.check_veto(intent, veto_window_s)
    return (not vetoed), "vetoed by human" if vetoed else "veto window elapsed, no veto"
