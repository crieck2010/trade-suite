# Decision Record: Moomoo as the Execution Broker

**Document ID:** `DOC-MOOMOO-EXECUTION-DECISION-v1.0`
**Date:** 2026-10-25
**Status:** DECIDED by Charlie (2026-10-24, live-trading roadmap)
**Supersedes:** the default recommendations in `BROKER_EXECUTION_EVALUATION.md`
(which evaluated Alpaca/Tradier/Tastytrade/IBKR but never evaluated Moomoo).

---

## Decision

All live-execution development targets **Moomoo (Futu Inc., `FUTUSECURITIES`)
via the local OpenD gateway and the `moomoo-api` SDK**, through the existing
`src/trade_execution/moomoo_adapter.py`. No other broker integration will be
built unless this record is formally revisited.

## Rationale

1. **The account and funds already exist there.** Charlie's brokerage
   relationship, margin account, and options permissions are at Moomoo;
   every alternative in the evaluation doc means a new account, new funding
   rails, and a new adapter.
2. **The adapter already exists and is verified in SIMULATE** (account
   auto-detection, OpenD auto-launch on port 11111, simulated order/account
   flows — commits `0b77a28`, `5469c1e`, `a2c8321`). Its REAL path is latched
   behind `allow_live_trading` (default `False`) plus a trade-password
   unlock, with an atomic audit log.
3. **API surface is sufficient for the roadmap's first live lane**
   (swing equities/ETFs — REGCOND-1 universe SPY/CPER/GLD/TLT): single-leg
   orders, account/position queries, ~15 orders/30 s rate limit per
   Moomoo's docs.

## Principles retained from the evaluation doc

The evaluation's *instrument* analysis stands even though its *broker*
conclusion is superseded:

- **SPY options are American-style** (physical delivery, pin/assignment risk
  if held into expiry); **SPX/XSP are European-style, cash-settled**, with
  Section 1256 tax treatment and no early assignment. Any future 0DTE lane
  prefers cash-settled index options *if* Moomoo's API can place them and
  the strategy has passed Tier-1 validation.
- Multi-leg atomicity matters: legging a 4-leg structure is not approved
  for live money under any phase of the roadmap.

## Open verification items (owned by roadmap phases)

| # | Question | How it gets answered | Phase |
|---|---|---|---|
| 1 | Can `moomoo-api` place an atomic multi-leg **options combo order** (e.g. iron fly) in SIMULATE? | `scripts/spike_combo_order_simulate.py` on Charlie's PC (OpenD, paper account) | 0 |
| 2 | What is Moomoo's current **intraday margin** house policy for a small US margin account, post-PDT-elimination (FINRA Rule 4210 amendments, effective 2026-06-04; broker phase-in to 2027-10-20)? | Written question to Moomoo support; answer filed with this record | 0/4 |
| 3 | Does Moomoo offer **SPX/XSP index options** trading to this account, and are they API-placeable? | App/API check during the Phase 3 0DTE track | 3 |
| 4 | OpenD unlock/session durability under the adapter (timeout, reconnect semantics) | Phase 1 watchdog build + drills | 1 |

## Consequences

- `BROKER_EXECUTION_EVALUATION.md` remains in the repo as analysis of
  record; its executive recommendation no longer governs.
- The live pilot (roadmap Phase 4) uses a **separate Moomoo account**
  segregated from Charlie's house fund, funded only with the pilot
  envelope. This record does not authorize any live trading; the roadmap's
  gates do that, one phase at a time, on Charlie's word.
