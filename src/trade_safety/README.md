# trade_safety — execution safety kernel

The single latch service every order must pass before an execution
adapter submits it. Built for the live-trading roadmap Phase 1: the
fail-safe set agreed 2026-10-19 (kill switch, daily-loss breaker,
exposure caps, pre-flight checks, heartbeat watchdog) as enforced code,
not conventions.

Broker-agnostic and stdlib-only. Adapters translate their payloads into
`OrderIntent` / `AccountSnapshot`; the kernel knows nothing about
Moomoo, OpenD, or any SDK.

## The gates (evaluated in order)

1. **E-Stop latch** — engaged ⇒ nothing trades. Reset requires a named
   actor; anonymous resets are refused.
2. **Daily-loss circuit breaker** — session loss (broker realized +
   unrealized P&L) at/over the limit trips the E-Stop, sends an alert,
   and **locks out the rest of the session**. Resetting the E-Stop does
   not clear the lockout.
3. **Per-trade cap** — max notional for one order. Market orders have
   unverifiable notional: they are flagged in the decision, not silently
   passed.
4. **Total-exposure cap** — existing gross exposure + the new order ≤ a
   configured share of equity.
5. **Margin cushion** — (equity − maintenance margin) / equity ≥ a
   configured buffer. This is a proxy for Moomoo's Intraday Margin Level
   (IML = ELV − SRO maintenance margin requirement; see
   `docs/MOOMOO_EXECUTION_DECISION.md`). It keeps the account clear of
   the broker's forced-liquidation zone.
6. **Approval policy** — `approve` (human yes per order), `veto_window`
   (proceed unless vetoed in N seconds), or `autonomous` (no per-order
   human step). With no approver channel wired, `approve` and
   `veto_window` block everything: a missing channel is a stop.

Gates 3–5 are skipped for orders flagged `reduces_exposure=True`;
gates 1, 2 and 6 never are.

## Components

| Module | Contents |
|---|---|
| `kernel.py` | `SafetyKernel.check()` and the breaker/E-Stop logic |
| `config.py` | `SafetyConfig` — every limit, explicit, pilot-scaled defaults |
| `state.py` | `SafetyState` — atomic JSON persistence (E-Stop, session, heartbeats) |
| `policy.py` | `ApprovalMode`, `Approver` protocol, `AutoApprover`, `CallbackApprover` |
| `preflight.py` | `run_preflight()` — session-start checklist as code |
| `watchdog.py` | `Watchdog.tick()` — stale heartbeat ⇒ E-Stop + cancel-all callback |
| `alerts.py` | Alert sinks: Mattermost webhook, memory (tests), null |
| `audit.py` | `JsonAuditWriter` (the shared `audit_log.json`), `MemoryAuditWriter` |

## Adapter wiring

`MoomooExecutionAdapter` consults the kernel when
`MoomooAdapterConfig.safety_config` is set (opt-in; default behavior is
unchanged). In REAL mode the adapter is **fail-closed**: a dead gateway
raises `OpenDConnectionError` and a blocked order raises
`SafetyBlockedError` — the offline simulation fallback exists only in
SIMULATE. See `tests/test_moomoo_safety_wiring.py`.

## Defaults (pilot-scaled; all configurable)

| Limit | Default |
|---|---|
| Daily loss | min(2% of session-start equity, $25) |
| Per-trade notional cap | $1,000 |
| Total exposure | 50% of equity |
| Min margin cushion | 25% of equity |
| Heartbeats | opend 45 s, data 90 s |
| Approval mode | `approve` |

## Drills

`scripts/drill_safety_kernel.py` runs the three Phase 1 drills
(E-Stop mid-run, breaker trip, watchdog trip) and writes a dated log to
`docs/logs/`. The phase gate also wants the drills repeated on Charlie's
PC against OpenD paper; the script runs there unchanged.
