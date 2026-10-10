"""Strategy registry: which live strategies the engine watches.

A strategy entry records everything decay monitoring needs that the
ledger itself does not carry -- chiefly the **validation-time
expectations** (expected Sharpe and its dispersion, validation
max-drawdown) against which live performance is judged.  Without a
recorded expectation there is nothing to decay *from*.

Registry file: JSON, default ``~/.trade-decay/strategies.json``
(override with ``$TRADE_DECAY_REGISTRY``).  Example::

    {"strategies": [
      {"strategy_id": "regcond1",
       "ledger_path": "~/.trade-paper/regcond1.db",
       "inception": "2026-10-01",
       "expected_sharpe": 1.2,
       "expected_sharpe_std": 0.3,
       "validation_maxdd": 0.08,
       "half_life_class": "data-dependent",
       "notes": "Tier-1 validated 5/5, allocator candidate pool"}
    ]}

``expected_sharpe`` / ``validation_maxdd`` come from the strategy's
Tier-1 validation record (trade-strategies ``docs/validation/GATES.md``);
``half_life_class`` reuses the idea-journal vocabulary
(``market-structure`` / ``data-dependent`` / ``timeless``) so the
research-side journal and this live-side monitor speak the same
language about decay horizons.

Stdlib only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

#: Half-life classes shared with the trade-agents idea journal.
HALF_LIFE_CLASSES = ("market-structure", "data-dependent", "timeless")

DEFAULT_REGISTRY_PATH = os.path.expanduser("~/.trade-decay/strategies.json")


class RegistryError(ValueError):
    """Raised for registry I/O problems and invalid strategy specs."""


def _default_path() -> str:
    return os.environ.get("TRADE_DECAY_REGISTRY", DEFAULT_REGISTRY_PATH)


@dataclass
class StrategySpec:
    """One watched live strategy and its validation-time expectations."""
    strategy_id: str
    ledger_path: str
    inception: str                      # YYYY-MM-DD
    expected_sharpe: float
    expected_sharpe_std: float | None = None
    validation_maxdd: float | None = None   # fraction, e.g. 0.08
    half_life_class: str = "data-dependent"
    notes: str = ""

    def __post_init__(self):
        if not self.strategy_id or not str(self.strategy_id).strip():
            raise RegistryError("strategy_id is required")
        if not self.ledger_path:
            raise RegistryError(
                f"strategy {self.strategy_id!r}: ledger_path is required")
        try:
            float(self.expected_sharpe)
        except (TypeError, ValueError):
            raise RegistryError(
                f"strategy {self.strategy_id!r}: expected_sharpe must be "
                f"numeric")
        if float(self.expected_sharpe) <= 0:
            raise RegistryError(
                f"strategy {self.strategy_id!r}: expected_sharpe must be "
                f"positive (decay is measured against a positive edge)")
        if self.validation_maxdd is not None:
            v = float(self.validation_maxdd)
            if not 0 < v < 1:
                raise RegistryError(
                    f"strategy {self.strategy_id!r}: validation_maxdd must "
                    f"be a fraction in (0, 1)")
        if self.half_life_class not in HALF_LIFE_CLASSES:
            raise RegistryError(
                f"strategy {self.strategy_id!r}: half_life_class must be "
                f"one of {HALF_LIFE_CLASSES}")

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "ledger_path": self.ledger_path,
            "inception": self.inception,
            "expected_sharpe": float(self.expected_sharpe),
            "expected_sharpe_std": (None if self.expected_sharpe_std is None
                                    else float(self.expected_sharpe_std)),
            "validation_maxdd": (None if self.validation_maxdd is None
                                 else float(self.validation_maxdd)),
            "half_life_class": self.half_life_class,
            "notes": self.notes,
        }


def load_registry(path: str | None = None) -> list[StrategySpec]:
    """Load strategy specs.  Missing file -> empty list (nothing watched)."""
    resolved = os.path.expanduser(path or _default_path())
    if not os.path.isfile(resolved):
        return []
    try:
        with open(resolved, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read registry {resolved}: {exc}")
    entries = data.get("strategies", []) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise RegistryError(
            f"registry {resolved}: expected a list under 'strategies'")
    specs = [StrategySpec(**e) for e in entries]
    ids = [s.strategy_id for s in specs]
    if len(set(ids)) != len(ids):
        raise RegistryError(f"registry {resolved}: duplicate strategy_id")
    return specs


def save_registry(specs: list[StrategySpec],
                  path: str | None = None) -> str:
    """Write strategy specs (creates ``~/.trade-decay/`` if needed)."""
    resolved = os.path.expanduser(path or _default_path())
    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    payload = {"strategies": [s.to_dict() for s in specs]}
    tmp = resolved + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, resolved)
    return resolved


def find_spec(specs: list[StrategySpec], strategy_id: str) -> StrategySpec:
    for spec in specs:
        if spec.strategy_id == strategy_id:
            return spec
    raise RegistryError(f"unknown strategy_id {strategy_id!r}")
