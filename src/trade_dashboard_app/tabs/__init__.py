"""Tabs export for trade_dashboard_app."""

from .tab1_global_macro import render_tab1
from .tab2_agent_visualizer import render_tab2
from .tab3_execution_log import render_tab3
from .tab4_strategy_backtest import render_tab4
from .tab5_risk_controls import render_tab5
from .tab6_options_surface import render_tab6
from .tab7_stress_test import render_tab7
from .tab8_field_mode import render_tab8

__all__ = [
    "render_tab1",
    "render_tab2",
    "render_tab3",
    "render_tab4",
    "render_tab5",
    "render_tab6",
    "render_tab7",
    "render_tab8",
]


