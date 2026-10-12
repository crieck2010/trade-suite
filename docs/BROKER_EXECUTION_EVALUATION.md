# Algorithmic Execution Broker Evaluation & Architecture Guide

**Document ID:** `DOC-BROKER-EXECUTION-EVALUATION-v1.0`  
**Target System:** Agentic AI Algorithmic Trading System (`trade-suite`)  
**Data Engine of Record:** Local ThetaData Terminal v3 (EOD + Intraday WebSocket Stream)  
**Execution Target:** Production Brokerage Integration for Equities (REGCOND-1) & 0DTE Options (Perryman Iron-Fly)  
**Author:** Antigravity (Advanced Agentic Pair Programmer) for Charlie Rieck & Meta Muse  

---

## 1. Executive Summary & Recommendation

For Charlie's agentic algorithmic trading architecture:

| Trading Domain | Top Recommendation | Secondary / Alternative | Rationale |
| :--- | :--- | :--- | :--- |
| **Equities & ETFs (REGCOND-1)** | **Alpaca API** | Interactive Brokers (IBKR) | Commission-free, native Python SDK (`alpaca-py`), fractional shares, zero-friction REST/WebSocket paper-to-live parity. |
| **0DTE Options (SPX / XSP / SPY)** | **Tradier API** | **Tastytrade API** | Alpaca does **not** support cash-settled index options (SPX/XSP). Tradier offers **$10/month unlimited commission-free options trading**, atomic 4-leg Iron Condor tickets, and cash-settled European options (zero early assignment risk). |

> [!IMPORTANT]
> **The SPY (American) vs. SPX/XSP (European) 0DTE Reality Check:**
> * **SPY Options (Alpaca):** American-style. Physical delivery of 100 SPY shares per contract upon exercise. In 0DTE trading, holding short ITM wings into the 4:00 PM close exposes the account to catastrophic overnight pin risk / after-hours exercise.
> * **SPX / XSP Options (Tradier / Tastytrade / IBKR):** European-style. 100% **cash-settled** with Section 1256 tax treatment (60% long-term / 40% short-term capital gains tax rates). Cannot be exercised early; no share assignment risk.

---

## 2. In-Depth Broker Comparison Matrix

| Feature / Criteria | **Alpaca** | **Tradier Brokerage** | **Tastytrade** | **Interactive Brokers (IBKR)** |
| :--- | :--- | :--- | :--- | :--- |
| **API Architecture** | Modern REST + WebSocket | Modern REST + WebSocket | Modern REST + WebSocket | Client Portal Gateway / TWS API |
| **Official Python SDK** | `alpaca-py` (Excellent) | Community + REST | `tastytrade` (Clean) | `ib_insync` / Official TWS |
| **Equity Commission** | **$0.00** | $0.00 | $0.00 | $0.005/share (Tiered) |
| **Options Commission** | $0.00 / contract (+ ~$0.03 reg) | **$0.00** (with $10/mo sub) or $0.35/contract | $1.00 to open / $0 to close (Capped at $10/leg) | $0.15 – $0.65 / contract + exchange fees |
| **Cash-Settled Index Options (SPX / XSP)** | ❌ **No** (ETFs/Equities only) | ✅ **Yes** | ✅ **Yes** | ✅ **Yes** |
| **Multi-Leg Atomic Orders (4-Leg Iron Fly)** | Limited (2-leg spreads) | ✅ **Yes (Atomic 4-leg)** | ✅ **Yes (Atomic 4-leg)** | ✅ **Yes (Combo orders / BAG)** |
| **Paper-Trading Sandbox** | **Flawless (Identical API)** | Good Sandbox | Good Sandbox | Requires running TWS/Gateway |
| **Direct Market Access (Lit Exchanges)** | ❌ (PFOF Wholesalers) | ❌ (Clearing routes) | ❌ (Clearing routes) | ✅ **Yes (SMART / Lit Routing)** |
| **Account Minimum** | $0 | $0 | $0 | $0 |

---

## 3. Detailed Pros & Cons Analysis

### Option A: Alpaca (`alpaca-py`)
* **Best For:** Equity portfolio rebalancing (REGCOND-1: SPY, CPER, GLD, TLT) and single-leg / simple ETF options.
* **Pros:**
  1. Exceptional developer experience: Webhooks, REST, WebSocket streaming, instant sandbox key generation.
  2. $0 commissions on US equities and ETF options.
  3. Easy fractional share execution makes exact dollar-weight rebalancing trivial.
* **Cons:**
  1. **No SPX / XSP support:** Restricts 0DTE trading to SPY.
  2. Complex multi-leg options order routing is less mature than dedicated derivatives brokers.

### Option B: Tradier Brokerage (The Best Value for Algorithmic Options)
* **Best For:** 0DTE systematic options selling (Dale Perryman Iron-Fly and Expected Move harvesting).
* **Pros:**
  1. **Flat-Rate Subscription ($10/month):** Unlimited commission-free options trading (exchange fees still apply, ~$0.15-$0.45 for proprietary index products). For an active 0DTE trader trading 10–50 contracts daily, this saves thousands of dollars annually compared to Tastytrade or IBKR.
  2. Full SPX / XSP cash-settled European options support with Section 1256 tax advantages.
  3. Pure REST/WebSocket API with straightforward OAuth and personal API tokens.
* **Cons:**
  1. Requires the $10/mo subscription to unlock zero-commission options (otherwise $0.35/contract).

### Option C: Tastytrade
* **Best For:** Derivatives-centric algorithmic desks wanting modern Python integration with capped fees.
* **Pros:**
  1. Built by the creators of ThinkorSwim specifically for options mechanics.
  2. Clean open-source Python SDK (`tastytrade`).
  3. Full support for SPX, XSP, equity options, and CME equity futures (`/ES`, `/MES`).
* **Cons:**
  1. $1.00 per contract to open adds friction for small 1-contract test orders (though capped at $10 per leg).

### Option D: Interactive Brokers (IBKR)
* **Best For:** Multi-asset institutional scaling across futures, FX, bonds, and international equities.
* **Pros:**
  1. Deepest liquidity, lowest margin loan interest rates in the industry.
  2. Direct exchange routing and advanced algorithmic execution (VWAP, TWAP, Adaptive Algo).
* **Cons:**
  1. Gateway architecture: Requires running a local Java process (TWS or Client Portal Gateway) with daily 2FA re-authentication.

---

## 4. Recommended Two-Broker Hybrid Architecture

1. **Alpaca API for Macro & Equities (`trade_paper` -> `trade_broker_alpaca`):**
   * Executes REGCOND-1 monthly asset allocation across `SPY`, `GLD`, `TLT`, and `CPER`.
   * Commission-free, fractional share precision.
2. **Tradier API for Intraday 0DTE Options (`trade_data_options` -> `trade_broker_tradier`):**
   * Uses ThetaData v3 WebSocket for real-time tick-by-tick expected move decay inputs.
   * Executes atomic 4-leg Iron Flies on cash-settled `SPX` or `XSP` via Tradier's $10/month flat-rate API.
   * Eliminates early assignment and overnight share delivery risk.
