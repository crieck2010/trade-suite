# trade-campaign

Long-running **paper campaigns** for validated strategies: the missing
link between "Tier-1 validated" and "graduation review". A campaign runs
one strategy, on one SIMULATE account, under one trade-incubate program,
until the program's graduation criteria are met or a kill condition
pauses it. Built for the live roadmap's Phase 2: the REGCOND-1
paper-autonomous campaign.

## How a campaign day works

1. **Replay.** The strategy (`trade_strategies.regcond_1.RegCond1`) is
   deterministic, so it is rebuilt each run by replaying the daily-close
   history (yfinance delayed closes via trade-data-equities). The
   campaign state file remembers which sessions were already lived
   through (`fed_through`), so re-running the same day is a no-op.
2. **Pre-flight.** If a safety kernel is attached, the session runs
   trade-safety's pre-flight; a failure aborts before anything is
   recorded.
3. **Advance.** The trade-incubate program advances exactly one day per
   live run (a catch-up run that feeds five sessions still counts one
   observed day, and the digest notes the catch-up).
4. **Rebalance (monthly).** When the newest unacted signal set exists,
   target weights × the program's stage size multiplier (WARMUP = 0.5)
   become target share counts; the diff against the broker's actual
   positions becomes marketable-limit orders (30 bps band through the
   last close), sells first. Every order passes through the safety
   kernel inside the adapter; blocks are recorded, never bypassed.
5. **Record.** Fills fold into per-symbol cost basis (realized P&L on
   exits; a closed trade is recorded when a position flattens). The day
   record goes to the trade-incubate ledger; the digest renders to
   `digests/<date>.md`.

## Safety posture (see `config.campaign_safety_config`)

AUTONOMOUS approval on the paper account; **no daily-loss breaker** —
REGCOND-1's validated design holds through drawdowns (max DD 23%), so
drawdown protection is the incubation program's kill conditions (pause
at 1.5× backtest DD; drift VIOLATION pauses) plus the manual E-Stop.
Exposure is capped at 105% of equity and a 10% margin-cushion floor
keeps the account clear of Moomoo's intraday-margin-deficit zone.

The campaign is paper-only by construction: `CampaignConfig` raises for
any env other than SIMULATE.

## Honest limits

- **Graduation arithmetic.** The incubation criteria (63 days, ≥ 20
  closed trades) were shaped for a swing strategy. REGCOND-1 rebalances
  monthly with four legs, so closed trades accrue slowly; the campaign
  will pass day 63 still short on trades and keep running in
  GRADUATION_REVIEW stage until both criteria hold. Expected horizon to
  graduation: ~5–6 months, not one quarter. The criteria are *not*
  lowered to fit — the digest reports both counters every day.
- Fills on the real paper account come from OpenD; the offline
  simulation exists for plumbing checks (`--allow-offline`) and is
  labeled as such.
- Slippage: fills are recorded with their actual average price versus
  the reference close, so the fills ledger supports the weekly slippage
  review the roadmap calls for; no slippage model is fitted yet.

## Run it

```bash
pip install -e ".[live,execution]"
# OpenD running, logged into the SIMULATE account:
python scripts/run_regcond1_campaign.py
python scripts/run_regcond1_campaign.py --dry-run   # compute only
```

State lives in `~/.trade-campaign/regcond1/` (`state.json`,
`incubation.jsonl`, `fills.jsonl`, `safety_state.json`,
`audit_log.json`, `digests/`).
