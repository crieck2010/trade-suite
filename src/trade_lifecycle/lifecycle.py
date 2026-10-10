"""The lifecycle state machine: promotion gates as law, not advice.

States: RESEARCH -> VALIDATED -> PAPER -> LIVE -> RETIRED, strictly in
order — no skipping.  PAUSED is an overlay any post-RESEARCH state can
enter (kill conditions, manual) and exit (human re-approval only).
RETIRED is terminal.

Nothing here executes trades.  This module governs *permission*; the
execution layer (trade-paper) never consults it, which is deliberate:
the committee grants or withholds the mandate, it does not place orders.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

# Underlying lifecycle states.  PAUSED is not a state — it is an overlay
# flag on the record (see StrategyRegistry), so the audit trail always
# shows *where* a strategy was paused.
STATES = ("RESEARCH", "VALIDATED", "PAPER", "LIVE", "RETIRED")

# The one legal forward path.  Every entry is the complete set of states
# reachable from the key.  Anything not listed here is refused.
_FORWARD = {
    "RESEARCH": ("VALIDATED",),
    "VALIDATED": ("PAPER",),
    "PAPER": ("LIVE",),
    "LIVE": (),
    "RETIRED": (),
}

# Overlay pseudo-transitions.  PAUSED may be entered from any
# post-RESEARCH state; RESUME returns to the underlying state.
_PAUSABLE_FROM = ("VALIDATED", "PAPER", "LIVE")

# The guard each transition kind requires (implemented in gates.py).
GUARD_FOR = {
    "forward:RESEARCH>VALIDATED": "validation_gates",
    "forward:VALIDATED>PAPER": "human_approval+incubation",
    "forward:PAPER>LIVE": "graduation+second_approval+mode+policy",
    "pause": "reason",
    "resume": "human_approval",
    "retire": "reason",
}


def classify(to_state: str, state: str, paused: bool) -> dict:
    """Classify an attempted transition.

    Returns {"kind", "legal", "note"} where kind is one of
    "forward", "pause", "resume", "retire", or "unknown".
    Pure function — no I/O, no clock.
    """
    if to_state == "PAUSED":
        if state == "RETIRED":
            return {"kind": "pause", "legal": False,
                    "note": "RETIRED is terminal; a retired strategy cannot be paused."}
        if state == "RESEARCH":
            return {"kind": "pause", "legal": False,
                    "note": "RESEARCH strategies have nothing running to pause."}
        if paused:
            return {"kind": "pause", "legal": False,
                    "note": "Strategy is already paused."}
        if state not in _PAUSABLE_FROM:
            return {"kind": "pause", "legal": False,
                    "note": f"Cannot pause from {state}."}
        return {"kind": "pause", "legal": True,
                "note": f"Pause {state} (overlay; underlying state preserved)."}

    if to_state == "RESUME":
        if not paused:
            return {"kind": "resume", "legal": False,
                    "note": "Strategy is not paused; nothing to resume."}
        return {"kind": "resume", "legal": True,
                "note": f"Resume to {state} (requires human re-approval)."}

    if to_state == "RETIRED":
        if state == "RETIRED":
            return {"kind": "retire", "legal": False,
                    "note": "Already retired. RETIRED is terminal — no transitions out, ever."}
        return {"kind": "retire", "legal": True,
                "note": f"Retire from {state}{' (paused)' if paused else ''}. Terminal."}

    if to_state in STATES:
        if state == "RETIRED":
            return {"kind": "forward", "legal": False,
                    "note": "RETIRED is terminal — no transitions out, ever."}
        if paused:
            return {"kind": "forward", "legal": False,
                    "note": f"Strategy is paused in {state}; resume first."}
        if to_state in _FORWARD.get(state, ()):
            key = f"forward:{state}>{to_state}"
            return {"kind": "forward", "legal": True,
                    "note": f"Guard: {GUARD_FOR[key]}."}
        return {"kind": "forward", "legal": False,
                "note": (f"Illegal transition {state} -> {to_state}. The lifecycle "
                         f"is strictly ordered RESEARCH > VALIDATED > PAPER > LIVE; "
                         f"no state may be skipped.")}

    return {"kind": "unknown", "legal": False,
            "note": f"Unknown target state {to_state!r}. Valid: {list(STATES)} + PAUSED/RESUME."}


def transition_result(*, allowed: bool, reasons: list[str], frm: str,
                      to: str, at: str, actor: str, paused: bool = False) -> dict:
    """The canonical TransitionResult plain-data dict (schema_version 1)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "allowed": bool(allowed),
        "reasons": list(reasons),
        "from": frm,
        "to": to,
        "paused": bool(paused),
        "at": at,
        "actor": actor,
    }
