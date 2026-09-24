# Architecture

## What the meta-package is (and isn't)

`trade-suite` contains no trading logic of its own. It is the **composition
root** of the system:

1. **One install** — `pyproject.toml` declares all twenty-three modules as
   `git+https` dependencies, so `pip install
   git+https://github.com/crieck2010/trade-suite.git` provisions the whole
   system.
2. **Introspection** — `env.py` answers "what is installed, at what
   version, and what's missing" for humans (`trade-suite status`) and for
   code (`env.require("trade-backtest")`).
3. **Orchestration** — `pipeline.py` composes sibling engines into
   end-to-end workflows (desk → backtest → risk review) that would otherwise
   be copy-pasted glue in every consumer.
4. **Unified entry** — the `trade-suite` CLI fronts the common operations
   (`status`, `doctor`, `demo`, `backtest`, `launch`).

```
┌──────────────────────────────────────────────────────────┐
│ trade-suite (this repo)                                  │
│  env.py        registry: 23 modules, roles, repo URLs     │
│  data.py       get_bars → dashboard DataService           │
│  pipeline.py   run_desk / run_backtest / evaluate_orders │
│                research_pipeline (desk→backtest→risk)     │
│                paper_overview (trade-paper state)         │
│                sentiment_scan (trade-sentiment pops)      │
│  research lab  run_pairs_screen / run_orderbook_sim /    │
│                run_optimize / run_montecarlo /           │
│                run_factor_analysis / run_vol_surface /   │
│                run_sentiment_price — one thin workflow   │
│                per new engine, plain-data in/out         │
│  cli.py        status | doctor | demo | backtest |        │
│                paper | sentiment | launch |              │
│                pairs | orderbook | optimize | montecarlo │
│                factors | sentiment-price | volsurface     │
├──────────────────────────────────────────────────────────┤
│ dashboards (services reused, not reimplemented)           │
│  trade-dashboard-web.engine  ← preferred service impl     │
│  trade-dashboard-desktop.engine ← fallback service impl  │
│  both expose a Research Lab tab over the same engines     │
├──────────────────────────────────────────────────────────┤
│ engines (lazy imports everywhere)                         │
│  trade-data-* → trade-strategies → trade-backtest        │
│  trade-risk → trade-agents → trade-paper (paper only)    │
│  trade-sentiment → trade-agents (sentiment_scout)        │
│  research lab: trade-pairs, trade-orderbook,             │
│  trade-optimize, trade-montecarlo, trade-volsurface,     │
│  trade-factors, trade-sentiment-vs-price                 │
└──────────────────────────────────────────────────────────┘
```

## The research-lab wiring pattern (0.2.0, extended 0.3.0)

The eight quant engines are wired in exactly like `trade-paper` and
`trade-sentiment` were: the meta-package holds **no logic of its own**.
Each engine stays the single engine of record; `pipeline.py` adds one thin
workflow per engine that

1. imports the engine lazily via `env.require(dist)` (a missing engine
   raises a `RuntimeError` naming the `pip install git+…` fix),
2. feeds it plain data (dict bars from `data.py`, or the engine's own
   demo/synthetic generators),
3. returns plain, JSON-serializable data the dashboards can render
   without importing the engine themselves.

This keeps three consumers — the `trade-suite` CLI, scripted Python, and
both dashboards' Research Lab tabs — running the **same** code path, so a
scripted run and a dashboard run of the same job agree exactly: the
meta-package delegates to the dashboard engine services, and each UI tab
only renders the plain-data result.

### Scaling notes

- **Engines stay independent.** A workflow never imports two engines
  except through their public plain-data adapters (e.g. optimize's
  returns matrix feeding montecarlo is done inline, not by coupling the
  packages), so any engine can be versioned, replaced, or scaled out
  (separate process / service) without touching the others.
- **Workflows are stateless and side-effect free.** No caches, no files,
  no globals: every call is `(params) → dict`, which makes them trivially
  parallelizable (thread/process pool over symbols) and safe to expose as
  HTTP endpoints — which is exactly what the web dashboard does.
- **Demo data is deterministic.** Seeded synthetic generators mean the
  full pipeline is testable offline and in CI with no network or keys.
- **Real data plugs in at the edges.** Delayed equities via
  `trade-data-equities`, Ken French CSVs via the factors engine's
  `load_french_csv`, real option chains via the volsurface engine's
  `from_option_chain`, archived sentiment rows via
  `run_sentiment_price(..., sentiment_rows=...)` — no workflow signatures
  change when a real source replaces demo data.

## Dependency rules

- `import trade_suite` imports **nothing** outside the stdlib. Every
  sibling is imported inside the function that needs it.
- `data.py` / `pipeline.py` resolve dashboard services with a
  web-first, desktop-fallback chain. Both dashboards expose identical
  service signatures (enforced by the desktop's own test suite), so the
  choice of provider never changes results.
- Failures name the fix: a missing module raises
  `RuntimeError("trade-x is not installed; install it with pip install
  git+https://…")` instead of a bare `ImportError`.

## Why the dashboards own the services

The `DataService`, `run_backtest_job`, `run_desk_job`, and
`evaluate_orders_job` functions live in the dashboard packages because the
dashboards were built first and both UIs need them. The meta-package
deliberately does **not** reimplement them — it delegates — so there is
exactly one implementation of each service in any installed environment.
If a headless-only service layer is ever wanted, the seam is clear: move
those functions to a `trade-services` package and point all three
consumers at it.

## Data flow: research_pipeline

```
symbols → data.get_bars_many (demo | delayed equities)
        → pipeline.run_desk → trade-agents default_desk
              researchers → portfolio manager → risk manager
        → DeskReport as plain dict
        → pipeline.run_backtest (optional strategy)
              trade-strategies registry → trade-backtest engine
        → metrics / equity curve / trades as plain dict
        → pipeline.evaluate_orders (desk's approved orders)
              trade-agents RiskManagerAgent over trade-risk limits
        → {"desk", "backtest", "risk"}
```

Every stage returns plain dicts/lists. Nothing engine-typed crosses a
stage boundary, which keeps results JSON-serializable and lets any stage be
replaced (e.g. a remote backtest service) without touching the others.

A second, lighter flow bypasses the dashboards entirely:
`pipeline.sentiment_scan` calls the `trade-sentiment` engine directly
(plain-data pops in, plain-data verdicts out). The same engine feeds the
trade-agents `sentiment_scout`, so a CLI scan and a desk run see the same
pops — one engine, two consumers, no duplicated logic.

## Scaling seams

- **Process boundary**: because stages communicate in plain data, the
  pipeline can later fan out across processes or machines (e.g. one desk
  run per symbol universe) with serialization at the existing seams.
- **UI scale**: the dashboards already run heavy jobs on background
  threads; the CLI is the headless counterpart for batch and cron use.
- **Data scale**: `get_bars_many` is sequential today; the per-symbol calls
  are independent and can be threaded when universes grow.

## Versioning

The meta-package versions independently (`0.1.2` here). It does not pin
sibling versions — each module follows semver, and the registry records the
installed version at runtime (`trade-suite status`) rather than at install
time. A breaking sibling release is handled by bumping the git dependency
and cutting a minor meta-release, documented in the changelog.
