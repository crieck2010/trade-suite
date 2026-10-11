"""trade_dashboard_app: Streamlit-first Broker-Grade Agentic Trading Dashboard.

Adheres strictly to the pure-engine / thin-UI separation:
- Zero trading logic or raw calculation in UI components.
- Decoupled backend service layer with high-fidelity fail-soft fallbacks.
- Master audit logging for all manual overrides and risk actions.
- Packaging-ready for standalone Windows .exe wrapping via PyInstaller and pywebview.
"""

from __future__ import annotations

__version__ = "1.2.0"
__all__ = ["__version__"]
