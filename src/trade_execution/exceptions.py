"""Execution-layer specific exceptions and safety barriers."""

from __future__ import annotations


class ExecutionError(Exception):
    """Base exception for all strategy execution errors."""


class LiveSafetyError(ExecutionError):
    """Raised when an action violates the live trading safety rules.

    Thrown if:
    - Live trading is requested without explicit ``allow_live_trading=True``.
    - Strategy code attempts to bypass Charlie's human-in-the-loop authorization gate.
    - System is under an active E-Stop.
    """


class TradeUnlockError(ExecutionError):
    """Raised when broker trade context cannot be unlocked (e.g. invalid trading password)."""


class OpenDConnectionError(ExecutionError):
    """Raised when connection to local Moomoo OpenD (127.0.0.1:11111) fails."""


class OrderRejectionError(ExecutionError):
    """Raised when broker or exchange rejects an order."""
