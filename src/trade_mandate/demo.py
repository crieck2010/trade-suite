"""Mandate theater: a deterministic walk through the constitution.

A valid proposal passes; then each violation class is refused with its
rule named; then an amendment is proposed and ratified with sign-off;
then a tampered file is caught by verify().  Seeded for convention —
the theater is deterministic by construction.
"""

from __future__ import annotations

import os

from .adapters import pm_check
from .amend import MandateStore
from .mandate import new_mandate
from .templates import get_preset
from .validate import check


def _base_proposal(**kw) -> dict:
    proposal = {
        "orders": [
            {"symbol": "AAPL", "side": "buy", "qty": 40, "price": 200.0,
             "order_type": "limit", "asset_class": "equity", "adv": 80_000_000},
            {"symbol": "MSFT", "side": "buy", "qty": 20, "price": 400.0,
             "order_type": "limit", "asset_class": "equity", "adv": 30_000_000},
        ],
        "current_positions": {
            "AAPL": {"weight": 0.02, "sector": "tech", "unrealized_pnl": 150.0},
            "MSFT": {"weight": 0.01, "sector": "tech", "unrealized_pnl": 40.0},
        },
        "equity": 100_000.0,
        "regime_conviction": 62,
        "current_drawdown": 0.03,
        "holds_overnight": False,
    }
    proposal.update(kw)
    return proposal


def run_demo(store_dir: str = "/tmp/trade-mandate-demo", seed: int = 7) -> dict:
    """Run the full theater; returns every act's plain-data result."""
    if os.path.isdir(store_dir):  # fresh stage every run
        import shutil
        shutil.rmtree(store_dir)
    store = MandateStore(store_dir)

    # Act 1 — ratify the house mandate (balanced preset)
    created = store.create(
        "house", approver="Charlie", rationale="initial constitution",
        effective_date="2026-09-24", **get_preset("balanced"))
    mandate = store.load("house")

    # Act 2 — a valid proposal passes
    valid = check(mandate, _base_proposal())

    # Act 3 — violations, each refused with its rule named
    violations = {}

    p = _base_proposal(orders=[
        {"symbol": "NVDA", "side": "buy", "qty": 125, "price": 200.0,
         "order_type": "limit", "asset_class": "equity", "adv": 50_000_000},
    ])  # 25% weight vs 10% single-name cap
    violations["concentration"] = check(mandate, p)

    p = _base_proposal(target_weights={"A": 0.6, "B": 0.6, "C": 0.6})
    violations["leverage"] = check(mandate, p)  # 1.8x vs 1.5x cap

    p = _base_proposal(orders=[
        {"symbol": "SPY", "side": "sell", "qty": 10, "price": 500.0,
         "order_type": "limit", "asset_class": "option",
         "instrument_type": "naked_short_call", "adv": 10_000_000},
    ])
    violations["forbidden_instrument"] = check(mandate, p)

    p = _base_proposal(regime_conviction=10)  # below min 25
    violations["stand_down"] = check(mandate, p)

    p = _base_proposal(orders=[
        {"symbol": "AAPL", "side": "buy", "qty": 5_000_000, "price": 200.0,
         "order_type": "limit", "asset_class": "equity", "adv": 80_000_000},
    ])  # 6.25% of ADV vs 5% cap
    violations["order_size"] = check(mandate, p)

    p = _base_proposal(
        current_positions={"TSLA": {"weight": 0.05, "sector": "auto",
                                    "unrealized_pnl": -800.0}},
        orders=[{"symbol": "TSLA", "side": "buy", "qty": 50, "price": 200.0,
                 "order_type": "limit", "asset_class": "equity",
                 "adv": 100_000_000}],
    )
    violations["martingale"] = check(mandate, p)

    # Act 4 — the exit door stays open under stand-down: a risk-reducing
    # sell during low conviction is allowed
    p = _base_proposal(
        regime_conviction=10,
        current_positions={"AAPL": {"weight": 0.08, "sector": "tech",
                                    "unrealized_pnl": 100.0}},
        orders=[{"symbol": "AAPL", "side": "sell", "qty": 40, "price": 200.0,
                 "order_type": "limit", "asset_class": "equity",
                 "adv": 80_000_000}],
    )
    exit_door = check(mandate, p)

    # Act 5 — amendment with sign-off, then tamper detection
    amendment = store.propose_amendment(
        "house", {"max_drawdown": 0.12}, proposer="Charlie")
    ratified = store.ratify(
        "house", amendment["amendment_id"], approver="Charlie",
        rationale="tighter leash after vol spike", effective_date="2026-09-25")
    amended_mandate = store.load("house")
    verify_clean = store.verify("house")

    # tamper: flip a byte in the .json without ratification
    with open(store.json_path("house"), "a") as fh:
        fh.write(" ")
    verify_tampered = store.verify("house")

    # Act 6 — the PM hook, fail-closed without a mandate
    pm_ok = pm_check(mandate, _base_proposal())
    pm_missing = pm_check("nonexistent-policy", _base_proposal(),
                          search_dirs=[store_dir])

    return {
        "seed": seed,
        "created": created,
        "valid_proposal": {"allowed": valid["allowed"],
                           "n_violations": len(valid["violations"])},
        "violations": {
            name: {"allowed": r["allowed"],
                   "rules": [v["rule"] for v in r["violations"]]}
            for name, r in violations.items()
        },
        "exit_door_open": exit_door["allowed"],
        "amendment": {"id": amendment["amendment_id"],
                      "ratified_version": ratified["version"]},
        "amended_max_drawdown": amended_mandate["max_drawdown"],
        "verify_clean": verify_clean["ok"],
        "verify_tampered": {"ok": verify_tampered["ok"],
                            "tampered_files": verify_tampered["tampered_files"]},
        "pm_hook": {"with_mandate": pm_ok["allowed"],
                    "without_mandate_refused": not pm_missing["allowed"]},
        "mandate": mandate,  # v1, for inspection
    }


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(run_demo(), indent=2, default=str))
