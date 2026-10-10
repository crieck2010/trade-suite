"""Lazy, fail-soft, fail-CLOSED sibling bridges.

Every function here tries the sibling import inside the call (never at
module import), and returns None / a clearly-marked unavailable dict when
the sibling is absent.  Callers — the guards in registry.py — treat a
missing answer as a FAILED guard with a stated reason, never as a pass.
Absence of evidence is not evidence of validity.
"""

from __future__ import annotations

# Test/demo injection: use_backends(validation_report_fn=..., incubation_status_fn=...)
_BACKENDS: dict = {}


def use_backends(**kwargs) -> None:
    """Inject backend callables (tests, demo).  Pass None values to clear."""
    for key, value in kwargs.items():
        if value is None:
            _BACKENDS.pop(key, None)
        else:
            _BACKENDS[key] = value


def clear_backends() -> None:
    _BACKENDS.clear()


def get_validation_report(strategy_id: str) -> dict | None:
    """Fetch a trade-swing ValidationReport for the strategy, if obtainable.

    trade-swing produces reports per run rather than storing them, so with
    no injected backend there is nothing to fetch: callers must pass
    report= explicitly.  Returns None (fail-closed downstream).
    """
    fn = _BACKENDS.get("validation_report_fn")
    if fn is not None:
        return fn(strategy_id)
    try:
        import trade_swing  # noqa: F401  (proves the sibling exists)
    except ImportError:
        return None
    # Sibling present but report-less: the caller must supply report=.
    return None


def get_incubation_status(strategy_id: str) -> dict | None:
    """Fetch trade-incubate status for the strategy, if obtainable.

    Returns {"enrolled": bool, "graduated": bool} or None when the
    sibling (or an injected backend) cannot answer.  None fails the
    PAPER/LIVE guards closed.
    """
    fn = _BACKENDS.get("incubation_status_fn")
    if fn is not None:
        return fn(strategy_id)
    try:
        import trade_incubate  # noqa: F401
    except ImportError:
        return None
    # Sibling present but this engine holds no program registry of its
    # own; without an injected status source there is nothing to read.
    return None


def sibling_available(name: str) -> bool:
    """Probe whether a sibling package imports cleanly."""
    try:
        __import__(name)
    except ImportError:
        return False
    return True
