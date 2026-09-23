# Architecture

## What the meta-package is (and isn't)

`trade-suite` contains no trading logic of its own. It is the **composition
root** of the system:

1. **One install** — `pyproject.toml` declares all eleven modules as
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
│  env.py        registry: 11 modules, roles, repo URLs     │
│  data.py       get_bars → dashboard DataService           │
│  pipeline.py   run_desk / run_backtest / evaluate_orders │
│                research_pipeline (desk→backtest→risk)     │
│                paper_overview (trade-paper state)         │
│  cli.py        status | doctor | demo | backtest |        │
│                paper | launch                             │
├──────────────────────────────────────────────────────────┤
│ dashboards (services reused, not reimplemented)           │
│  trade-dashboard-web.engine  ← preferred service impl     │
│  trade-dashboard-desktop.engine ← fallback service impl  │
├──────────────────────────────────────────────────────────┤
│ engines (lazy imports everywhere)                         │
│  trade-data-* → trade-strategies → trade-backtest        │
│  trade-risk → trade-agents → trade-paper (paper only)    │
└──────────────────────────────────────────────────────────┘
```

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

## Scaling seams

- **Process boundary**: because stages communicate in plain data, the
  pipeline can later fan out across processes or machines (e.g. one desk
  run per symbol universe) with serialization at the existing seams.
- **UI scale**: the dashboards already run heavy jobs on background
  threads; the CLI is the headless counterpart for batch and cron use.
- **Data scale**: `get_bars_many` is sequential today; the per-symbol calls
  are independent and can be threaded when universes grow.

## Versioning

The meta-package versions independently (`0.1.0` here). It does not pin
sibling versions — each module follows semver, and the registry records the
installed version at runtime (`trade-suite status`) rather than at install
time. A breaking sibling release is handled by bumping the git dependency
and cutting a minor meta-release, documented in the changelog.
