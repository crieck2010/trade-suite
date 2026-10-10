"""Entry point: ``python -m trade_dashboard_desktop``."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        description="trade-dashboard-desktop: trade-suite desktop dashboard"
    )
    parser.add_argument(
        "--skip-update-check",
        action="store_true",
        help="do not check GitHub for a newer release on startup",
    )
    args = parser.parse_args()

    from .ui.app import main as run_app

    run_app(skip_update_check=args.skip_update_check)


if __name__ == "__main__":
    main()
