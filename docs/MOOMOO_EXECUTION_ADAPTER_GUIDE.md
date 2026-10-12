# Moomoo OpenAPI Execution Adapter Architecture & Guide

**Module:** `src/trade_execution/`  
**Package:** `trade_execution` (v0.1.0)  
**Primary Class:** `MoomooExecutionAdapter` ([`moomoo_adapter.py`](file:///c:/Agentic%20AI%20Algorithmic%20Trading%20System%20Software/src/trade_execution/moomoo_adapter.py))  
**Underlying SDK:** `moomoo-api` (v10.11+) / Moomoo OpenD Gateway  
**Author:** Antigravity (Google DeepMind Advanced Agentic Coding) in collaboration with Charlie Rieck  
**Target Workstation:** Windows 11 Workstation (`127.0.0.1:11111`)  
**Status:** Validated in Simulation (`TrdEnv.SIMULATE`) & Real-Ready (`TrdEnv.REAL`) with Hardware Safety Gates  

---

## 1. Executive Summary & Rationale

Charlie maintains a well-funded, active **Moomoo Margin Account**. Rather than introducing capital friction, transfer delays, or tax-reporting fragmentation by wiring capital to a new brokerage, `trade_execution.moomoo_adapter` provides a broker-grade interface between our autonomous agentic trading desk and Moomoo.

### Why Moomoo Outperforms Alternative Retail APIs:
1. **Cash-Settled European Index Options (`SPX` / `XSP`):**
   - Essential for 0DTE Expected Move decay harvesting.
   - Unlike Alpaca (which only supports American-style `SPY` options), Moomoo supports European-style cash settlement (`US..SPX...` and `US..XSP...`). Contracts settle in cash at 16:00 ET with **zero physical delivery pin risk**.
   - Qualifies for **IRC Section 1256 tax treatment** (60% long-term / 40% short-term capital gains tax rates).
2. **Atomic Multi-Leg Combo Execution (`place_combo_order`):**
   - Routes 4-leg Iron-Flies (ATM short straddle + 50-wide long wings) as a single composite order directly to the exchange.
   - Eliminates execution leg-in risk (either all 4 legs fill together, or none fill).
3. **Competitive Pricing:**
   - **$0 commission** on US Equities & ETFs (`SPY`, `TLT`, `GLD`, `CPER`).
   - **$0.50 / contract** for Index Options (`SPX`, `XSP`), significantly undercutting Interactive Brokers ($0.65) without requiring Tradier's monthly subscription fee.
4. **Mandatory Trade Password Gate (`unlock_trade`):**
   - Live orders (`TrdEnv.REAL`) strictly require an explicit trade unlock with Charlie's trading password. This provides a hardware-level safety barrier that prevents accidental live order execution during agent backtesting or paper-trading sessions.

---

## 2. Architectural Topology

```
┌────────────────────────────────────────────────────────────────────────┐
│                        LangGraph Multi-Agent Desk                      │
│     (RegCond-1 Allocator / 0DTE EM-Decay Harvester / Risk Desk)        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Staged Proposal
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Charlie Human-in-the-Loop Gate                       │
│    (Dashboard Tab 5 / Field Mode Tab 8 / Mattermost /trade approve)    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Approved Authorization
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     trade_execution Module Architecture                │
│                                                                        │
│   ExecutionAdapter (ABC)                                               │
│   ├── OrderPayload (Single-Leg ETF/Equity: SPY, TLT, GLD, CPER)        │
│   └── ComboOrderPayload (4-Leg Atomic 0DTE SPX Iron-Fly)               │
│                                                                        │
│   MoomooExecutionAdapter                                               │
│   ├── Safety Latch 1: allow_live_trading == True                       │
│   ├── Safety Latch 2: unlock_live_trading(password)                    │
│   └── Atomic Audit Log: audit_log.json                                 │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ TCP / Protobuf (:11111)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     Local Moomoo OpenD Gateway                         │
│                    (Runs on Windows Workstation)                       │
│                                                                        │
│   TrdEnv.SIMULATE (Paper Account)  │  TrdEnv.REAL (Live Margin Account)│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Encrypted SSL WAN
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       Moomoo Securities / Cboe                         │
│          (Cash-Settled SPX Index & US Equity Execution)                │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Installation & Local OpenD Gateway Setup

Moomoo Open API uses a local gateway daemon called **OpenD**. It runs locally on Charlie's machine, authenticates with Moomoo's servers, and provides an ultra-fast local TCP interface on `127.0.0.1:11111`.

### Step 1: Install Python SDK
The Python SDK has already been installed into the environment:
```powershell
pip install moomoo-api
```

### Step 2: Download & Launch Moomoo OpenD
1. Download **Moomoo OpenD for Windows** from the official portal:  
   [https://openapi.moomoo.com/](https://openapi.moomoo.com/)
2. Install and launch OpenD.
3. Configure `OpenD.xml` or use the OpenD GUI:
   - **Listen Port:** `11111` (Default)
   - **Listen IP:** `127.0.0.1` (Local loopback only)
   - **Login Account:** Charlie's Moomoo Account ID
   - **Trading Password:** Stored securely or prompted via CLI/environment variable `MOOMOO_TRADE_PASSWORD`.
4. Ensure OpenD reports `Connected to server successfully`.

---

## 4. Code Examples & Usage

### A. Initializing the Adapter (Simulation vs. Real)

```python
from trade_execution import (
    MoomooExecutionAdapter,
    MoomooAdapterConfig,
    ExecutionEnvironment,
    OrderAction,
    OrderPayload,
    OrderType,
)

# 1. Paper / Simulation Mode (Default & Safe)
sim_config = MoomooAdapterConfig(
    host="127.0.0.1",
    port=11111,
    env=ExecutionEnvironment.SIMULATE,
    allow_live_trading=False,  # Hard safety latch
)
sim_adapter = MoomooExecutionAdapter(sim_config)
sim_adapter.connect()

# 2. Live Real-Money Mode (Strictly Protected)
live_config = MoomooAdapterConfig(
    host="127.0.0.1",
    port=11111,
    env=ExecutionEnvironment.REAL,
    allow_live_trading=True,   # Must be explicitly set
    unlock_password="YOUR_TRADING_PASSWORD",
)
live_adapter = MoomooExecutionAdapter(live_config)
live_adapter.connect()
live_adapter.unlock_live_trading()  # Mandatory unlock gate
```

---

### B. Executing Macro Rebalancing (RegCond-1 Equities & ETFs)

```python
# Monthly delta sizing order: 100 shares SPY
order = OrderPayload(
    symbol="SPY",
    action=OrderAction.BUY,
    quantity=100,
    price=582.50,
    order_type=OrderType.LIMIT,
    strategy="regcond1_expansion",
)

result = sim_adapter.place_order(order)
print(f"Order ID: {result.order_id}, Status: {result.status}, Filled: {result.filled_qty}")
```

---

### C. Executing Atomic 0DTE European SPX Iron-Flies

```python
# Construct pre-registered 4-leg Iron-Fly at 83% Expected Move decay
# Strikes automatically conform to the multiples-of-5 rule
fly_payload = MoomooExecutionAdapter.create_0dte_iron_fly_payload(
    expiry_yymmdd="261012",
    atm_strike=5800.0,
    wing_width=50.0,     # Short 5800 straddle, Long 5750 P and 5850 C
    quantity=1,          # 1 lot = 4 contracts
    net_credit=18.50,    # Target net credit limit
    is_mini_xsp=False,   # True for mini XSP ($1/pt), False for full SPX ($10/pt)
    strategy="0dte_em_decay",
)

# Place combo order atomically on exchange
combo_res = sim_adapter.place_combo_order(fly_payload)
print(f"Combo Order ID: {combo_res.order_id}, Success: {combo_res.success}")
```

---

## 5. Security & Safety Gates

The `MoomooExecutionAdapter` enforces multi-layer defense-in-depth:

1. **`allow_live_trading` Boolean Latch:**
   Defaults to `False`. If an order is sent with `env == ExecutionEnvironment.REAL` while `allow_live_trading == False`, the adapter immediately throws `LiveSafetyError` before touching OpenD.
2. **`unlock_live_trading()` Verification:**
   Moomoo OpenD locks trading capabilities on restart. Live orders are rejected until unlocked with Charlie's dedicated trade password.
3. **Atomic Audit Logging (`audit_log.json`):**
   Every order submission, fill, rejection, cancellation, and unlock event writes atomically using a temporary file rename pattern to guarantee zero log corruption.
4. **Offline Fail-Soft Mode:**
   If Moomoo OpenD is offline during development or test execution, the adapter automatically switches to high-fidelity internal paper simulation without crashing the surrounding application or research lab.

---

## 6. Verification & Automated Tests

Run the dedicated test suite:
```powershell
python -m pytest tests/test_moomoo_execution.py -v
```

All 8 tests cover:
- Schema validation for single and multi-leg orders.
- Strike rounding and symbol formatting for Cboe European SPX/XSP options.
- Atomic combo order generation and execution.
- Strict enforcement of `LiveSafetyError` when live trading is attempted without authorization.
- Atomic `audit_log.json` recording.
