# trade_press — Narrative Momentum Engine (Press Listener)

Listens to the financial press by **narrative theme** rather than by ticker,
archives what it hears point-in-time, and reduces each theme to one daily
question:

> Is this narrative gaining momentum, holding steady, or fading?

`trade_press` is the sibling of `trade_sentiment`. That engine asks *"what are
people saying about NVDA?"*; this one asks *"is the AI-capex story losing
momentum?"* — it measures **shifts in narrative sentiment frequency**: how
often a story is being told, and whether its tone is rolling over.

**Research-only.** Outputs are context (like the `trade_macro` weather
barometer), never trade signals. Nothing downstream may trade on narrative
state until a narrative→return relationship passes Tier-1 validation
(see *Validation pathway* below).

Spec: `2026-10-19_press-listener-spec_v0.1.0.md` (trading goal files).

## Quickstart

```bash
# Fetch, classify, score, and archive today's AI-capex coverage
python -m trade_press scan --theme ai_infrastructure_capex \
    --archive ~/.trade-press/press-archive.db

# Compute + store today's narrative state (prints the v1 payload)
python -m trade_press rollup --theme ai_infrastructure_capex \
    --archive ~/.trade-press/press-archive.db

# Read a stored state back (strict as-of: no rollup that day → error)
python -m trade_press state --theme ai_infrastructure_capex \
    --as-of 2026-10-19 --archive ~/.trade-press/press-archive.db

python -m trade_press themes   # list registered theme packs
python -m trade_press policy   # storage/licensing rules
```

On day one the honest state is `INSUFFICIENT_DATA`: the momentum rules need a
30-day baseline of recorded days, and the archive starts accumulating the day
you first run it. There is no backfill — RSS is a snapshot of the recent past,
and this engine never fabricates history.

## How it works

```
RSS fetch (sources.py)         Google News RSS by theme query, keyless
  → classify (classify.py)     deterministic keywords; hits stored for audit
  → score (scoring.py)         shared trade_sentiment lexicon (lazy import)
  → archive (archive.py)       SQLite, dual timestamps, dedupe by content hash
  → rollup (aggregate.py)      daily stats + frozen momentum state machine
  → context (context.py)       press.narrative_state.v1 → agents' market_context
```

### Point-in-time discipline

Every item carries three timestamps: `published_at` (when the publisher says
it ran), `observed_at` (publication when known, else fetch), and `recorded_at`
(when it entered the archive). All reads filter on `recorded_at <= as_of` —
the suite's no-lookahead contract, identical to `trade_sentiment.archive`.
Daily stats bucket items by their **recorded** day: the day an item entered
the archive is the day it became knowable.

### Momentum conventions (frozen, spec §8)

Documented conventions, **not fitted to returns**. Changing them requires a
spec version bump and a changelog entry.

| State | Rule |
|---|---|
| `INSUFFICIENT_DATA` | fewer than 30 baseline days recorded |
| `FADING` | `freq_z <= -0.5` **and** `polarity_slope_7d <= -0.05` |
| `RISING` | `freq_z >= +0.5` **and** `polarity_slope_7d >= +0.05` |
| `STEADY` | anything else with a full baseline |

A narrative is "losing momentum" only when it is told *less often* and *less
warmly* at the same time — either alone is noise. `freq_z` is today's item
count vs the trailing 30-day distribution of daily counts; `polarity_slope_7d`
is the last 7 days' mean polarity minus the prior 7 days'.

## Frozen schemas

**`press.observation.v1`** — one archived item: the `PressItem` fields plus
`theme_id`, `polarity`, `magnitude`, `label`, and `hits` (the classifier +
lexicon terms that fired). Emitted by `ScoredPressItem.to_dict()`.

**`press.narrative_state.v1`** — the daily per-theme verdict:

```json
{
  "schema": "press.narrative_state.v1",
  "theme_id": "ai_infrastructure_capex",
  "as_of": "2026-10-19",
  "state": "FADING",
  "n_items": 41,
  "freq_z": -1.23,
  "mean_polarity": 0.08,
  "polarity_slope_7d": -0.11,
  "n_publishers": 17,
  "baseline_days": 30,
  "notes": []
}
```

## Theme packs

Packs are **data** in `themes.py` — queries, include/exclude terms, `min_hits`,
related symbols (cross-reference only), and a pack `version`. An item matches
a theme when at least `min_hits` include terms appear in title + summary and
no exclude term appears (exclusions veto). Adding a theme is a data change
plus tests, not an engine change.

Phase 1 ships one pack: `ai_infrastructure_capex` v1.0.0 (AI data-center /
hyperscaler capex narrative; related: NVDA, AVGO, MSFT, GOOGL, AMZN, META,
ORCL).

## Interoperability

| Consumer | Surface |
|---|---|
| `trade_agents` | `press.narrative_state.v1` via `context.narrative_input()` / `adapters.to_agent_context()` into `market_context` |
| `trade_macro.weather` | Future optional input slot; Phase 1 does **not** modify weather |
| `trade_sentiment` | Shared lexicon + label vocabulary (lazy import); archive discipline and CLI conventions mirrored |
| Dashboards | `adapters.to_dashboard_rows()` — flat per-theme rows |

## Operations

Accumulation mirrors the sentiment archive job: run `scan` then `rollup`
weekdays after the close against `~/.trade-press/press-archive.db`. (Any cron
is a separate, explicitly approved step — the engine ships first.) Re-running
a past date's rollup is safe and reproducible: it reads only items recorded
through that date.

## Storage & licensing

Headlines, RSS summary snippets, URLs, publisher names, and timestamps only —
**never full article text** (see `licensing.py`). Redistribution is limited to
derived statistics. The archive is a private local research store, not a
republishing surface.

## Limitations

- **No backfill.** History begins at first deployment; every coverage report
  states the first recorded date.
- **RSS is a snapshot.** Feeds surface recent items; a story that scrolls off
  the feed between scans is missed. Daily cadence keeps the gap small.
- **Keyword classification is crude.** It will miss paraphrases and catch some
  false positives; the stored `hits` make both auditable. An LLM-assisted
  classifier is Phase 3 and advisory-only.
- **Lexicon tone is a heuristic**, shared with `trade_sentiment` — comparable
  across the suite, not a trained model.
- **Syndication:** one wire story at 40 outlets is one item (content-hash
  dedupe); `n_publishers` reports the breadth separately.

## Phasing

Phase 1 (this release): one theme, one source, deterministic everything.
Phase 2: SEC EDGAR 8-K source + PR-wire sources, second theme pack.
Phase 3: LLM-assisted classification in the challenger seat (advisory labels
alongside the deterministic record). Phase 4 (separate spec): the full
confluence scoreboard.

## Validation pathway

1. Accumulate ≥ 6 months of point-in-time theme data.
2. Pre-register any narrative→return hypothesis (frozen doc, honest trial
   lineage).
3. Tier-1 validation with `trade_multitest` corrections (DSR / Reality Check
   / SPA / Holm).
4. Only a *validated* verdict may promote narrative state from context to a
   sizing input — a separate, explicit decision.
