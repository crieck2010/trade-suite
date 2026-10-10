"""Dashboard tabs; each exposes ``build(parent, ctx)``."""

from . import (agents_tab, backtest_tab, data_tab, desk_tab, live_tab,
               network_tab, paper_tab, performance_tab, research_tab,
               risk_monitor_tab, risk_tab, strategies_tab, trades_tab)

__all__ = ["agents_tab", "backtest_tab", "data_tab", "desk_tab", "live_tab",
           "network_tab", "paper_tab", "performance_tab", "research_tab",
           "risk_monitor_tab", "risk_tab", "strategies_tab", "trades_tab"]
