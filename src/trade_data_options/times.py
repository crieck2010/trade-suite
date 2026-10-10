"""Expiry time arithmetic shared by the client and analytics."""

from __future__ import annotations

from datetime import date, datetime

from .models import ensure_utc

#: Approximation used for 0DTE chains (Black-Scholes is degenerate at T=0).
ZERO_DTE_YEARS = 6.0 / (365.0 * 24.0)


def time_to_expiry(expiry: date, asof: datetime) -> float:
    """Years from ``asof`` to ``expiry`` (Actual/365, 0DTE ~= 6h)."""
    days = (expiry - ensure_utc(asof).date()).days
    return days / 365.0 if days > 0 else ZERO_DTE_YEARS
