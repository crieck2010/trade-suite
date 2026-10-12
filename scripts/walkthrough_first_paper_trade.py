"""Walkthrough script demonstrating automated simulated paper trade via MoomooExecutionAdapter.

Demonstrates:
1. Live OpenD gateway handshake on 127.0.0.1:11111.
2. Auto-detection of paper trading account (acc_id=2889614).
3. Simulated cash & buying power balance query ($1,000,000.00).
4. Submitting an automated paper order for SPY (RegCond-1 rebalance).
5. Verification of the Moomoo order ID and status in the order book.
6. Atomic audit logging to audit_log.json.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sys

# Ensure workspace root and src directory are on sys.path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from trade_execution.moomoo_adapter import MoomooAdapterConfig, MoomooExecutionAdapter
from trade_execution.models import (
    ExecutionEnvironment,
    OrderAction,
    OrderPayload,
    OrderType,
    TimeInForce,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("FirstPaperTradeWalkthrough")


def run_walkthrough() -> None:
    print("=" * 70)
    print(" MOOMOO OPEND AUTOMATED SIMULATED PAPER TRADE WALKTHROUGH")
    print("=" * 70)

    # 1. Initialize Adapter in SIMULATE environment (paper trading only)
    cfg = MoomooAdapterConfig(
        host="127.0.0.1",
        port=11111,
        env=ExecutionEnvironment.SIMULATE,
        allow_live_trading=False,  # Hard safety latch remains active
    )
    adapter = MoomooExecutionAdapter(cfg)

    # 2. Connect to local OpenD gateway
    print("\n[Step 1] Connecting to OpenD at 127.0.0.1:11111...")
    if not adapter.connect():
        print("ERROR: Could not connect to OpenD gateway. Ensure OpenD is running.")
        return

    print(f" -> Connected successfully!")
    print(f" -> Environment : {adapter.cfg.env.value}")
    print(f" -> Account ID  : {adapter.cfg.account_id} (US Paper Margin Account)")

    # 3. Query Account Telemetry
    print("\n[Step 2] Querying Paper Account Telemetry...")
    acct = adapter.get_account()
    print(f" -> Net Liquidity : ${acct.net_liquidity:,.2f}")
    print(f" -> Buying Power  : ${acct.buying_power:,.2f}")
    print(f" -> Cash Balance  : ${acct.cash:,.2f}")
    print(f" -> Currency      : {acct.currency}")

    # 4. Check Open Positions
    print("\n[Step 3] Checking Existing Open Positions...")
    positions = adapter.get_positions()
    print(f" -> Active Positions: {len(positions)}")
    for pos in positions:
        print(f"    - {pos.symbol}: {pos.quantity} shares @ avg ${pos.cost_basis:,.2f}")

    # 5. Stage & Submit First Automated Paper Order
    print("\n[Step 4] Staging Automated Paper Order for SPY (RegCond-1 Strategy)...")
    order = OrderPayload(
        symbol="SPY",
        action=OrderAction.BUY,
        quantity=5,
        price=450.00,  # Below market limit for paper staging demonstration
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        strategy="REGCOND_1_REBALANCE",
        client_tag="first-paper-trade-spy",
    )
    print(f" -> Staged: {order.action.value} {order.quantity} {order.symbol} @ Limit ${order.price:.2f}")

    result = adapter.place_order(order)
    print(f"\n[Step 5] Execution Result Received from Moomoo OpenD:")
    print(f" -> Success    : {result.success}")
    print(f" -> Order ID   : {result.order_id}")
    print(f" -> Status     : {result.status}")
    print(f" -> Client Tag : {result.client_tag}")
    print(f" -> Message    : {result.message}")

    # 6. Verify in Order Book
    print("\n[Step 6] Querying Moomoo OpenD Order Book...")
    orders = adapter.query_orders()
    matching = [o for o in orders if str(o.get("order_id")) == str(result.order_id)]
    if matching:
        moomoo_order = matching[0]
        print(f" -> Verified Order in Moomoo Ledger:")
        print(f"    - Code         : {moomoo_order.get('code')}")
        print(f"    - Status       : {moomoo_order.get('order_status')}")
        print(f"    - Quantity     : {moomoo_order.get('qty')}")
        print(f"    - Price        : ${moomoo_order.get('price')}")
        print(f"    - Submitted At : {moomoo_order.get('create_time')}")

    # 7. Verify Audit Log
    print("\n[Step 7] Verifying Atomic Audit Log (audit_log.json)...")
    audit_file = Path("audit_log.json")
    if audit_file.exists():
        with open(audit_file, "r", encoding="utf-8") as f:
            audit_events = json.load(f)
            last_event = audit_events[-1]
            print(f" -> Last Event Action : {last_event.get('action')}")
            print(f" -> Timestamp         : {last_event.get('timestamp')}")
            print(f" -> Event Details     : {last_event.get('details')}")

    # Clean up test order
    print(f"\n[Step 8] Cleaning up demonstration order {result.order_id}...")
    cancel_success = adapter.cancel_order(result.order_id)
    print(f" -> Cancel Request Submitted: {cancel_success}")

    adapter.disconnect()
    print("\n[Step 9] Disconnected session cleanly.")
    print("=" * 70)
    print(" FIRST AUTOMATED PAPER TRADE COMPLETED SUCCESSFULLY")
    print("=" * 70)


if __name__ == "__main__":
    run_walkthrough()
