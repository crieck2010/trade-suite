"""Execution, order blotter, and backtesting service for Tabs 3 and 4.

Provides broker-grade trade logs and walk-forward validation telemetry.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .base import OrderRecord


def get_order_blotter() -> List[OrderRecord]:
    """Returns the historical and active order blotter with algorithmic rationale."""
    return [
        OrderRecord(
            order_id="ORD-2026-1006-001",
            timestamp="2026-10-06T10:00:05Z",
            symbol="SPY",
            side="BUY",
            quantity=78,
            order_type="MARKET",
            limit_price=None,
            fill_price=761.43,
            status="FILLED",
            agent_proposer="REGCOND-1 Allocator",
            rationale="Monthly rebalance: copper:gold regime read EXPANSION (60% target weight)",
            expected_price=761.40,
            slippage_bps=3.9,
        ),
        OrderRecord(
            order_id="ORD-2026-1006-002",
            timestamp="2026-10-06T10:00:07Z",
            symbol="CPER",
            side="BUY",
            quantity=510,
            order_type="MARKET",
            limit_price=None,
            fill_price=39.27,
            status="FILLED",
            agent_proposer="REGCOND-1 Allocator",
            rationale="Monthly rebalance: industrial metals tilt (20% target weight)",
            expected_price=39.26,
            slippage_bps=2.5,
        ),
        OrderRecord(
            order_id="ORD-2026-1006-003",
            timestamp="2026-10-06T10:00:09Z",
            symbol="TLT",
            side="BUY",
            quantity=257,
            order_type="MARKET",
            limit_price=None,
            fill_price=77.85,
            status="FILLED",
            agent_proposer="REGCOND-1 Allocator",
            rationale="Monthly rebalance: duration ballast (20% target weight)",
            expected_price=77.84,
            slippage_bps=1.3,
        ),
        OrderRecord(
            order_id="ORD-2026-1011-004",
            timestamp="2026-10-11T13:45:00Z",
            symbol="XLE",
            side="SELL",
            quantity=100,
            order_type="LIMIT",
            limit_price=88.50,
            fill_price=None,
            status="PENDING",
            agent_proposer="Covered Call Harvester",
            rationale="Overbought RSI(14)=74 on XLE; write 35 DTE covered call at 0.30 delta",
            expected_price=88.50,
            slippage_bps=0.0,
        ),
    ]


def get_validation_telemetry() -> Dict[str, Any]:
    """Returns walk-forward validation and Deflated Sharpe Ratio (DSR) metrics for Tab 4."""
    return {
        "strategy_name": "REGCOND-1 (Regime-Conditioned Allocation)",
        "status": "Tier-1 Validated (5/5 Gates Passed)",
        "deflated_sharpe_ratio": 1.000,
        "dsr_threshold": 0.80,
        "dsr_verdict": "PASS",
        "oos_median_sharpe": 1.385,
        "oos_sharpe_threshold": 0.30,
        "max_drawdown_oos": -23.0,
        "max_drawdown_threshold": -25.0,
        "sortino_ratio": 1.41,
        "sortino_threshold": 0.75,
        "excess_return_vs_60_40": 4.91,
        "walk_forward_geometry": "104w train / 26w test / 26w step (13 folds, 1670 bars)",
        "positive_folds": "10 of 13 folds positive",
        "n_trials_fixed": 2,
    }
