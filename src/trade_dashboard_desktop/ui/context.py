"""Shared context passed to every tab builder (avoids app/tab import cycles)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class AppContext:
    """Everything a tab needs; owned by the main app window."""

    engine: Any  # trade_dashboard_desktop.engine (services + USING_SHARED_ENGINE)
    data: Any  # engine.DataService instance
    submit: Callable  # (label, target, args, kwargs, on_done, on_error) -> None
    status: Callable[[str], None]  # push a message to the status bar
