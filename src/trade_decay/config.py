"""Engine configuration: thresholds and file locations.

Default ``~/.trade-decay/config.json`` (override with
``$TRADE_DECAY_CONFIG``).  Only the ``thresholds`` object is read from
the file; anything else is ignored so the file can carry comments-as-
fields later.  Missing file -> compiled-in sane defaults.

Example ``config.json`` (see ``examples/config.json``)::

    {"thresholds": {
       "sharpe_warn_ratio": 0.5,
       "sharpe_demote_ratio": 0.25,
       "z_warn": -1.0,
       "z_demote": -2.0,
       "dd_warn_ratio": 1.0,
       "dd_demote_ratio": 1.5,
       "recover_ratio": 0.75,
       "min_daily_points": 20,
       "trailing_window_days": 60}}
"""

from __future__ import annotations

import json
import os

from .state_machine import Thresholds

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.trade-decay/config.json")


def _default_path() -> str:
    return os.environ.get("TRADE_DECAY_CONFIG", DEFAULT_CONFIG_PATH)


def load_config(path: str | None = None) -> Thresholds:
    """Load thresholds (file values over compiled-in defaults)."""
    resolved = os.path.expanduser(path or _default_path())
    data: dict = {}
    if os.path.isfile(resolved):
        try:
            with open(resolved, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                data = loaded.get("thresholds", {}) or {}
        except (OSError, json.JSONDecodeError):
            data = {}  # corrupt config -> defaults, never a crash
    return Thresholds.from_dict(data if isinstance(data, dict) else {})
