"""Pure-logic services backing the dashboard.  No web-framework imports."""

from .backtest_service import run_backtest_job
from .data_service import DataService, bar_to_dict
from .desk_service import run_desk_job
from .paper_service import (
    paper_approvals,
    paper_approve,
    paper_available,
    paper_fidelity,
    paper_status,
)
from .research_service import (
    run_breadth_job,
    run_correlation_job,
    run_factor_analysis_job,
    run_macro_job,
    run_montecarlo_job,
    run_optimize_job,
    run_orderbook_job,
    run_pairs_job,
    run_reconcile_demo_job,
    run_sentiment_price_job,
    run_stream_demo_job,
    run_vol_surface_job,
)
from .risk_service import describe_limits, evaluate_orders_job
from .strategy_service import describe_strategy, list_strategies
from .terminal_service import (
    resolve_ledger_path,
    resolve_track_record_path,
    run_agent_activity_job,
    run_network_job,
    run_performance_job,
    run_risk_monitor_job,
    run_trades_job,
    trades_to_csv,
)

__all__ = [
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
    "resolve_ledger_path",
    "resolve_track_record_path",
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
]
