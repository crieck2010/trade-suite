# Pre-registered hypothesis: 0DTE EM-decay iron fly (SPX)

**Status:** PRE-REGISTERED — 2026-10-11. No backtest has been run.
**Source:** Dale Perryman 0DTE iron-fly interview, Theta Profits podcast, 2026-10-11 (video).
**Idea-journal entry:** logged 2026-10-11 (see trade-agents idea journal).

Every parameter below is marked **[FROZEN]**. Changing any of them after
seeing backtest results is overfitting and is prohibited by the house
pre-registration rule. If a parameter must change, it becomes a *new*
hypothesis with its own lineage.

## Thesis

Sell 0DTE SPX premium only after a fixed fraction of the opening expected
move has decayed — a timing filter on premium decay. The edge claim, if
any, comes from (a) harvesting theta on rangebound days while (b) cutting
losers mechanically at a pre-defined distance and (c) avoiding the
highest tail-risk sessions. This document records the claim; Tier-1
validation decides whether it is real.

## Frozen rule set

| # | Parameter | Value **[FROZEN]** | Source |
|---|---|---|---|
| 1 | Entry trigger | Enter first fly when the ATM straddle for today's expiry is **≤ 83% of the opening EM** (decay fraction ≤ 0.83, measured by `trade_data_options.em_decay`) | video |
| 2 | Structure | 0DTE SPX iron fly: short ATM call + short ATM put, long wings | video |
| 3 | Wing schedule | Wings start **50 points** wide at the open, narrowing through the session: **50 → 45 → 30 → 25 → 20** (20 wide in roughly the last 30 minutes); never wider than 50 | video |
| 4 | Add rule | Add a new fly at/near the money when price moves **±(credit − 5 points)** from the existing short strike | video |
| 5 | Cut rule | Close a fly when price moves **`credit` collected** away from its short strike ("the stop loss is the credit collected"); never take profit otherwise — let theta work | video + trade_risk.premium |
| 6 | Skip days | Do not trade: **FOMC announcement days**, **monthly OpEx (third Friday)** **[FROZEN]** (video claimed third Wednesday; third Friday is the documented standard and is what's frozen), **last trading day of the month** (per `trade_macro.skip_days`) | video, corrected |
| 7 | Sizing | **≤ 30% of account** allocated to iron flies; risk **≤ 1% of account per fly** (positioned via `trade_risk.premium_size`, which never rounds up) | video + house risk |
| 8 | Underlying | SPX (cash-settled, Section 1256 treatment); XSP explicitly excluded (less liquid, missing strikes — "off the reservation" per video) | video |

## What is explicitly NOT claimed

- The **83%** threshold is a hypothesis value from the video, **not a tuned
  optimum**. It was written down before any backtest.
- The video's claim that the three skip days "double performance" is
  **not adopted** — it is a sub-hypothesis to be tested, not a premise.
- The video's win-rate / P&L figures (~62% winning days, ~$2,200 average
  losing day) are **unverified** (no audited statements) and are not inputs
  to this hypothesis.

## Validation plan

1. **Data:** intraday SPX options NBBO quotes (ThetaData historical).
   Blocked until acquired — no validation on substitute data.
2. **Fill engine:** NBBO-aware options fill/cost model (buy at ask, sell at
   bid, per-contract commissions and fees, partial/non-fills). Blocked until
   built — this is hypothesis-doc item **1C**.
3. **Tier-1 gates** per `trade_strategies` GATES.md: walk-forward with
   embargo, costs on, DSR, max drawdown, worst-regime behavior, minimum
   trade counts. Language standard: **validated / invalidated / discarded**.
4. **DSR trial accounting via trade-multitest from day one.** The 83%
   threshold and the three skip days are selection-bias-shaped parameters;
   the honest trial count starts at this document, not at the first
   backtest that "works".
5. **Paper first:** only a validated hypothesis earns the pointed paper
   runner and the 63-day / 20-trade lifecycle clock. Nothing here is wired
   into REGCOND-1 or any live execution path.

## Blocked items (recorded, not built)

- **1C — 0DTE backtest harness** (intraday simulation consuming the decay
  signal, credit-based stops, skip-day filter, NBBO costs): blocked on
  ThetaData acquisition + NBBO options fill engine.
- **Dealer-gamma context** (short-gamma acceleration): parked for the same
  options-data acquisition; tracked separately.
