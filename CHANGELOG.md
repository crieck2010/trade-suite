# Changelog

All notable changes to `trade-suite` are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and versioning follows [Semantic Versioning](https://semver.org/).

## [0.4.0] - 2026-09-24

### Added
- Wired in **trade-breadth** (v0.1.0) as suite module twenty-one: market
  breadth engine (advance/decline, % above moving averages, new
  highs/lows, McClellan oscillator, breadth thrusts, broadening/narrowing
  regime, fragility gauge). New `pipeline.run_breadth` workflow +
  `summarize_breadth`, new `trade-suite breadth --preset --seed --days`
  CLI command, registry entry in `trade_suite.env`.
- Wired in **trade-macro** (v0.1.0) as suite module twenty-two: macro
  regime engine (EXPANSION / CONTRACTION / NEUTRAL from the copper:gold
  growth-expectations proxy, transition alerts on fast z-score moves).
  New `pipeline.run_macro` workflow + `summarize_macro`, new
  `trade-suite macro --preset --seed --days` CLI command, registry entry
  in `trade_suite.env`.
- Wired in **trade-stream** (v0.1.0) as suite module twenty-three:
  real-time streaming engine (WebSocket transport, pub/sub bus, message
  normalization, tick recording/replay, tick-to-bar resampling, spike
  alerts). New `pipeline.run_stream_demo` workflow +
  `summarize_stream_demo`, new `trade-suite stream --symbols --seed
  --ticks` CLI command (demo tick feed, no network), registry entry in
  `trade_suite.env`.
- New `pipeline.run_reconcile_demo` workflow + `summarize_reconcile` and
  `trade-suite reconcile` CLI command: a DEMO read-only reconcile of the
  paper ledger against an in-memory mock broker, exercising trade-paper
  v0.2.0's reconcile machinery (the same read-only diff the Robinhood
  MCP adapter uses). Printed output is labeled
  "DEMO — read-only reconcile against a mock broker"; it can never touch
  live state.
- All four flows delegate to the dashboards' canonical
  `run_breadth_job` / `run_macro_job` / `run_stream_demo_job` /
  `run_reconcile_demo_job` via `pipeline._services()` (web engine first,
  desktop fallback), following the established 0.2.0/0.3.0 wiring pattern:
  scripted, CLI, and dashboard runs of the same job agree exactly.

### Fixed
- **trade-eda** (wired in 0.3.0) was missing its git-URL dependency line in
  `pyproject.toml` and `requirements.txt`; added, alongside the three new
  modules.

### Notes
- trade-data-equities v0.2.0 added a PolygonProvider, but that is
  **data-layer only** — no suite code change was needed; the suite keeps
  talking to the engines through the unchanged `DataService`/`get_bars`
  paths.
- Registry is now twenty-three modules; `trade-suite status` derives its
  counts from `trade_suite.env` unchanged.

## [0.3.0] - 2026-09-24

### Added
- Wired in **trade-eda** as suite module twenty: correlation/covariance/
  EDA engine (Pearson/Spearman matrices, Ledoit-Wolf shrinkage, per-asset
  summary stats, data-quality checks, diversification stats). New
  `pipeline.run_correlation` workflow + `summarize_correlation`, new
  `trade-suite correlate` CLI command, registry entry in `trade_suite.env`.
  The workflow delegates to the dashboards' canonical
  `run_correlation_job`, so CLI, scripted, and Research Lab runs of the
  same universe agree exactly.
- Research Lab grows to eight panels in both dashboards (new Correlations
  panel), following the established 0.2.0 wiring pattern unchanged.

## [0.2.0] - 2026-09-24

### Added
- Wired in the seven new quant engines as suite modules thirteen through
  nineteen: **trade-pairs** (cointegration screen, hedge ratios, signals),
  **trade-orderbook** (limit-order-book simulator, execution analytics),
  **trade-optimize** (Markowitz optimization, efficient frontier),
  **trade-montecarlo** (simulated VaR/CVaR, drawdown scenarios),
  **trade-volsurface** (SVI surface fits, arbitrage checks),
  **trade-factors** (Fama-French regressions, GRS joint-alpha test), and
  **trade-sentiment-vs-price** (lead/lag, event studies, information
  coefficient, sentiment indicators). Git-URL dependencies in
  `pyproject.toml` / `requirements.txt`, registry entries in
  `trade_suite.env` (nineteen modules), and one thin workflow per engine
  in `trade_suite.pipeline` — plain data in, plain data out, demo-capable,
  each naming its engine of record the way `paper_overview` and
  `sentiment_scan` already do.
- Seven matching CLI commands: `trade-suite pairs|orderbook|optimize|
  montecarlo|factors|sentiment-price|volsurface`, each printing a one-screen
  summary.
- `research_pipeline()` gains two opt-in enrichments (off by default):
  `sentiment_price=True` attaches a per-symbol sentiment-vs-price verdict,
  and `factor_model="ff5"` attaches a Fama-French factor report.
- `docs/ARCHITECTURE.md` documents the research-lab wiring pattern; README
  quickstart and Python API examples cover all seven flows.

### Notes
- Demo bars cap at 750 days, so demo factor regressions use about two
  years of monthly history (synthetic factor date labels; alignment is
  what matters). Real Ken French CSVs plug into the engine's
  `load_french_csv`; real option chains into `from_option_chain`; real
  sentiment history into `run_sentiment_price(..., sentiment_rows=...)`.

## [0.1.2] - 2026-09-23

### Added
- Wired in the new **trade-sentiment** social/news sentiment engine as the
  twelfth module: git-URL dependency in `pyproject.toml` /
  `requirements.txt`, registry entry in `trade_suite.env`, new
  `trade_suite.sentiment_scan()` workflow (plain-data pops and verdicts,
  configurable window / mention / conviction bars), and a
  `trade-suite sentiment --symbols --window-hours --min-mentions
  --min-conviction` CLI command. The same engine feeds the trade-agents
  `sentiment_scout`, so the CLI and the desk see identical pops.
- README quickstart and Python API examples cover the sentiment flow;
  `docs/ARCHITECTURE.md` documents the direct-to-engine data flow and the
  one-engine-two-consumers design.

## [0.1.1] - 2026-09-23

### Added
- Wired in the new **trade-paper** paper-trading engine: git-URL dependency
  in `pyproject.toml` / `requirements.txt`, registry entry in
  `trade_suite.env` (eleven modules), new `trade_suite.paper_overview()`
  workflow, and a `trade-suite paper --config` CLI command printing the
  paper account, positions, active strategies, and the strategy-approval
  queue.
- Both dashboards' new **Paper** tabs (v0.1.1 releases) monitor the same
  `trade-paper` engine.

## [0.1.0] - 2026-09-23

### Added
- Meta-package over the ten trade-suite modules: one `pip install` for the
  whole system (git-URL dependencies in `pyproject.toml`, mirrored in
  `requirements.txt`).
- `trade_suite.env`: module registry with roles and repo URLs;
  `module_status()` / `installed_modules()` / `require()` introspection.
- `trade_suite.data`: `get_bars()` delegating to the dashboard engines'
  `DataService` (demo + delayed equities), with a clear install hint when
  no dashboard package is present.
- `trade_suite.pipeline`: end-to-end workflows — `run_backtest`,
  `run_desk`, `evaluate_orders` — orchestrating the sibling engines through
  the shared dashboard-engine services (identical results in either UI).
- `trade-suite` CLI: `status`, `doctor`, `demo`, `backtest`, `launch web|desktop`.
- `examples/end_to_end_demo.py`: desk → backtest → risk review on demo data.
- License-key check hook and GitHub-releases update-check hook.
- MIT license, README, architecture doc, test suite.
