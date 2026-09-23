# Changelog

All notable changes to `trade-suite` are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and versioning follows [Semantic Versioning](https://semver.org/).

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
