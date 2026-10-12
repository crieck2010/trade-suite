"""Abstract base class for strategy execution adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import (
    AccountState,
    ComboOrderPayload,
    ExecutionEnvironment,
    ExecutionResult,
    OrderPayload,
    PositionSnapshot,
)


class ExecutionAdapter(ABC):
    """Unified interface for executing trading orders across brokers.

    Enforces strict separation between presentation/agent layers and raw broker execution.
    Supports both simulated paper execution (`TrdEnv.SIMULATE`) and live real-money
    execution (`TrdEnv.REAL`) with an explicit human-in-the-loop authorization gate.
    """

    adapter_name: str = "base"

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection to broker gateway or API."""

    @abstractmethod
    def disconnect(self) -> None:
        """Cleanly terminate broker session."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if connection is healthy."""

    @abstractmethod
    def get_environment(self) -> ExecutionEnvironment:
        """Return current execution environment (SIMULATE or REAL)."""

    @abstractmethod
    def get_account(self) -> AccountState:
        """Retrieve latest account balance and margin telemetry."""

    @abstractmethod
    def get_positions(self) -> list[PositionSnapshot]:
        """Retrieve current open positions."""

    @abstractmethod
    def place_order(self, order: OrderPayload) -> ExecutionResult:
        """Submit single-leg equity, ETF, or option order."""

    @abstractmethod
    def place_combo_order(self, combo: ComboOrderPayload) -> ExecutionResult:
        """Submit multi-leg combo order (e.g. 4-leg European SPX 0DTE Iron-Fly)."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by ID."""

    @abstractmethod
    def unlock_live_trading(self, password: str) -> bool:
        """Unlock trading capabilities for live execution (PIN/Password gate)."""

    @abstractmethod
    def lock_live_trading(self) -> bool:
        """Relock live trading capabilities."""
