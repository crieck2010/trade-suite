"""Module registry and environment introspection.

``MODULES`` is the single source of truth for what belongs to the suite:
(distribution name, import name, role, repository URL).  Everything else —
``pip`` metadata, the CLI ``status`` command, docs — is derived from it.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
from dataclasses import dataclass


@dataclass(frozen=True)
class Module:
    dist: str      # pip distribution name, e.g. "trade-backtest"
    package: str   # import name, e.g. "trade_backtest"
    role: str      # one-line description of its job in the suite
    repo: str      # GitHub repository URL


MODULES: tuple[Module, ...] = (
    Module("trade-data-equities", "trade_data_equities",
           "Market data: stocks & ETFs (delayed)",
           "https://github.com/crieck2010/trade-data-equities"),
    Module("trade-data-options", "trade_data_options",
           "Market data: options chains, pricing, Greeks",
           "https://github.com/crieck2010/trade-data-options"),
    Module("trade-data-futures", "trade_data_futures",
           "Market data: futures contracts & term structure",
           "https://github.com/crieck2010/trade-data-futures"),
    Module("trade-data-crypto", "trade_data_crypto",
           "Market data: crypto spot / perpetuals",
           "https://github.com/crieck2010/trade-data-crypto"),
    Module("trade-backtest", "trade_backtest",
           "Event-driven backtesting engine",
           "https://github.com/crieck2010/trade-backtest"),
    Module("trade-strategies", "trade_strategies",
           "Strategy library (19 strategies, 7 families)",
           "https://github.com/crieck2010/trade-strategies"),
    Module("trade-risk", "trade_risk",
           "Risk limits, sizers, drawdown guards",
           "https://github.com/crieck2010/trade-risk"),
    Module("trade-agents", "trade_agents",
           "Agentic research desk (scouts → PM → risk)",
           "https://github.com/crieck2010/trade-agents"),
    Module("trade-paper", "trade_paper",
           "Paper-trading execution engine (Alpaca paper)",
           "https://github.com/crieck2010/trade-paper"),
    Module("trade-sentiment", "trade_sentiment",
           "Social/news sentiment engine (Reddit/StockTwits/news RSS)",
           "https://github.com/crieck2010/trade-sentiment"),
    Module("trade-dashboard-web", "trade_dashboard_web",
           "Web dashboard (shared engine services)",
           "https://github.com/crieck2010/trade-dashboard-web"),
    Module("trade-dashboard-desktop", "trade_dashboard_desktop",
           "Desktop dashboard (tkinter)",
           "https://github.com/crieck2010/trade-dashboard-desktop"),
)

_BY_DIST = {m.dist: m for m in MODULES}
_BY_PACKAGE = {m.package: m for m in MODULES}


def module_status() -> list[dict]:
    """One dict per module: dist, package, role, repo, installed, version."""
    out = []
    for mod in MODULES:
        version: str | None = None
        try:
            pkg = importlib.import_module(mod.package)
            version = getattr(pkg, "__version__", None) or _dist_version(mod.dist)
        except ImportError:
            pkg = None
        out.append({
            "dist": mod.dist,
            "package": mod.package,
            "role": mod.role,
            "repo": mod.repo,
            "installed": pkg is not None,
            "version": version or "—",
        })
    return out


def _dist_version(dist: str) -> str | None:
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return None


def installed_modules() -> list[Module]:
    """Modules importable in this environment."""
    return [m for m in MODULES
            if importlib.util.find_spec(m.package) is not None]


def missing_modules() -> list[Module]:
    """Modules not importable in this environment."""
    installed = {m.dist for m in installed_modules()}
    return [m for m in MODULES if m.dist not in installed]


def require(dist: str):
    """Import ``dist``'s package or raise a helpful error naming the repo."""
    mod = _BY_DIST.get(dist)
    if mod is None:
        raise KeyError(f"unknown suite module {dist!r}")
    try:
        return importlib.import_module(mod.package)
    except ImportError as exc:
        raise RuntimeError(
            f"{dist} is not installed; install it with "
            f"`pip install git+{mod.repo}.git`"
        ) from exc


def status_table() -> str:
    """Human-readable module table for the CLI."""
    rows = module_status()
    width = max(len(r["dist"]) for r in rows)
    lines = []
    for r in rows:
        mark = "✓" if r["installed"] else "✗"
        lines.append(f"  {mark} {r['dist']:<{width}}  v{r['version']:<8}  {r['role']}")
    n = sum(1 for r in rows if r["installed"])
    lines.append(f"\n{n}/{len(rows)} modules installed")
    missing = [r for r in rows if not r["installed"]]
    if missing:
        lines.append("Install missing modules with, e.g.:")
        lines.append(f"  pip install git+{missing[0]['repo']}.git")
        lines.append("…or everything at once: pip install -r requirements.txt")
    return "\n".join(lines)
