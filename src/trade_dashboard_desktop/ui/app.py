"""Main application window."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .. import engine
from ..engine import licensing, updates
from .context import AppContext
from .tabs import (agents_tab, backtest_tab, data_tab, desk_tab, live_tab,
                   network_tab, paper_tab, performance_tab, risk_monitor_tab,
                   risk_tab, strategies_tab, trades_tab)
from .workers import Job, JobRunner

APP_TITLE = "TradeSuite Desktop"
GEOMETRY = "1180x820"


class TradeDeskApp(tk.Tk):
    def __init__(self, skip_update_check: bool = False) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(GEOMETRY)

        self.runner = JobRunner(self)
        self.data_service = engine.DataService()
        self.ctx = AppContext(
            engine=engine,
            data=self.data_service,
            submit=self._submit,
            status=self.set_status,
        )

        self._build_menu()
        self._build_body()
        self._build_statusbar()
        self._refresh_license_status()
        if not skip_update_check:
            self._check_updates_background()

    # -- layout -----------------------------------------------------------
    def _build_body(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=6, pady=6)
        for title, module in [
            ("Backtest Lab", backtest_tab),
            ("Strategies", strategies_tab),
            ("Agent Desk", desk_tab),
            ("Risk Review", risk_tab),
            ("Risk Monitor", risk_monitor_tab),
            ("Paper", paper_tab),
            ("Trades", trades_tab),
            ("Performance", performance_tab),
            ("Agents", agents_tab),
            ("Network", network_tab),
            ("Market Data", data_tab),
            ("Live", live_tab),
            ("Research Lab", research_tab),
        ]:
            tab = module.build(notebook, self.ctx)
            notebook.add(tab, text=title)

    def _build_statusbar(self) -> None:
        self._status_var = tk.StringVar(value="Ready")
        bar = ttk.Frame(self, relief="sunken", padding=(6, 2))
        bar.pack(fill="x", side="bottom")
        ttk.Label(bar, textvariable=self._status_var, anchor="w").pack(
            side="left", fill="x", expand=True)
        engine_label = ("shared engine (trade-dashboard-web)"
                        if engine.USING_SHARED_ENGINE else "bundled engine")
        ttk.Label(bar, text=engine_label, foreground="gray").pack(side="right")

    def set_status(self, message: str) -> None:
        self._status_var.set(message)

    def _submit(self, job: Job) -> None:
        self.runner.submit(job)

    # -- menu -------------------------------------------------------------
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Quit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Check for updates…",
                               command=self._check_updates_foreground)
        tools_menu.add_command(label="Enter license key…",
                               command=self._enter_license)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self._about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menubar)

    def _about(self) -> None:
        from .. import __version__

        messagebox.showinfo(
            "About",
            f"{APP_TITLE} v{__version__}\n\n"
            "Desktop research dashboard for the trade-suite:\n"
            "backtesting, strategy catalog, agentic research desk,\n"
            "risk review, trade blotter, performance analytics,\n"
            "agent activity, correlation network, and market data.\n\n"
            "Research and paper-trading tooling only — no live trading.",
        )

    # -- licensing ----------------------------------------------------------
    def _refresh_license_status(self) -> None:
        self._license_status = licensing.current_status()

    def _enter_license(self) -> None:
        key = simpledialog.askstring("License key", "Enter your license key "
                                                   "(format TD-XXXX-XXXX-XXXX):",
                                     parent=self)
        if key is None:
            return
        status = licensing.save_key(key)
        self._refresh_license_status()
        if status.valid:
            messagebox.showinfo("License", "License key accepted. "
                                           "Pro tier enabled.")
        else:
            messagebox.showwarning("License", f"Key not accepted: {status.detail}")
        self.set_status(f"License: {self._license_status.tier}")

    # -- updates ------------------------------------------------------------
    def _check_updates_background(self) -> None:
        from .. import __version__

        def on_done(result: dict) -> None:
            if result.get("update_available"):
                self.set_status(
                    f"Update available: {result['latest']} — "
                    f"Tools → Check for updates ({result['url']})")
            elif result.get("error"):
                self.set_status("Update check skipped (offline)")
            else:
                self.set_status("Up to date")

        def on_error(_error: str) -> None:
            self.set_status("Update check skipped (offline)")

        self.runner.submit(Job("update-check",
                               lambda: updates.check_for_updates(__version__),
                               on_done=on_done, on_error=on_error))

    def _check_updates_foreground(self) -> None:
        from .. import __version__

        self.set_status("Checking for updates…")

        def on_done(result: dict) -> None:
            if result.get("error"):
                messagebox.showwarning("Updates",
                                       f"Could not check for updates:\n{result['error']}")
                self.set_status("Update check failed")
            elif result.get("update_available"):
                messagebox.showinfo(
                    "Updates",
                    f"A newer release is available: {result['latest']}\n\n"
                    f"{result['url']}")
                self.set_status(f"Update available: {result['latest']}")
            else:
                messagebox.showinfo("Updates", "You are up to date.")
                self.set_status("Up to date")

        self.runner.submit(Job("update-check",
                               lambda: updates.check_for_updates(__version__),
                               on_done=on_done,
                               on_error=lambda e: self.set_status("Update check failed")))


def main(skip_update_check: bool = False) -> None:
    app = TradeDeskApp(skip_update_check=skip_update_check)
    app.mainloop()
