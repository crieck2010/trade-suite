"""Pure-logic services backing the desktop dashboard.  No tkinter imports.

Interoperability: when the ``trade-dashboard-web`` package is installed,
these names are bound to :mod:`trade_dashboard_web.engine` so both
dashboards share one implementation.  Otherwise the stdlib-only local
fallbacks in :mod:`trade_dashboard_desktop.engine.services` are used, which
expose identical names and signatures.
"""

from __future__ import annotations

_SERVICE_NAMES = (
    "DataService",
    "bar_to_dict",
    "describe_limits",
    "describe_strategy",
    "evaluate_orders_job",
    "list_strategies",
    "paper_approvals",
    "paper_approve",
    "paper_available",
    "paper_fidelity",
    "paper_status",
    "run_agent_activity_job",
    "run_backtest_job",
    "run_breadth_job",
    "run_correlation_job",
    "run_desk_job",
    "run_factor_analysis_job",
    "run_macro_job",
    "run_montecarlo_job",
    "run_network_job",
    "run_optimize_job",
    "run_orderbook_job",
    "run_pairs_job",
    "run_performance_job",
    "run_reconcile_demo_job",
    "run_risk_monitor_job",
    "run_sentiment_price_job",
    "run_stream_demo_job",
    "run_trades_job",
    "run_vol_surface_job",
    "trades_to_csv",
)

try:  # Prefer the web dashboard's engine: one source of truth in a meta-install.
    import trade_dashboard_web.engine as _web_engine

    for _name in _SERVICE_NAMES:
        globals()[_name] = getattr(_web_engine, _name)
    USING_SHARED_ENGINE = True
except ImportError:  # Standalone install: use the local equivalents.
    from .services import (  # noqa: F401
        DataService,
        bar_to_dict,
        describe_limits,
        describe_strategy,
        evaluate_orders_job,
        list_strategies,
        paper_approvals,
        paper_approve,
        paper_available,
        paper_fidelity,
        paper_status,
        run_agent_activity_job,
        run_backtest_job,
        run_breadth_job,
        run_correlation_job,
        run_desk_job,
        run_factor_analysis_job,
        run_macro_job,
        run_montecarlo_job,
        run_network_job,
        run_optimize_job,
        run_orderbook_job,
        run_pairs_job,
        run_performance_job,
        run_reconcile_demo_job,
        run_risk_monitor_job,
        run_sentiment_price_job,
        run_stream_demo_job,
        run_trades_job,
        run_vol_surface_job,
        trades_to_csv,
    )

    USING_SHARED_ENGINE = False

__all__ = list(_SERVICE_NAMES) + ["USING_SHARED_ENGINE"]
