"""Entry point: ``python -m trade_dashboard_web``."""

import argparse

from .web import run


def main() -> None:
    parser = argparse.ArgumentParser(description="trade-dashboard-web: trade-suite dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    run(args.host, args.port)


if __name__ == "__main__":
    main()
