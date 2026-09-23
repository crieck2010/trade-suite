"""End-to-end demo: desk research -> backtest -> risk review, all on demo data.

Usage:
    PYTHONPATH=src python examples/end_to_end_demo.py [SYMBOL ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from trade_suite import pipeline  # noqa: E402


def main(symbols: list[str]) -> None:
    print("== 1. Agent desk ==")
    desk = pipeline.run_desk(symbols, source="demo", days=250, equity=100_000.0)
    print(pipeline.summarize_desk(desk))

    print("\n== 2. Backtest (donchian_breakout) ==")
    backtest = pipeline.run_backtest("donchian_breakout", symbols,
                                     {"entry": 20, "exit": 10},
                                     source="demo", days=250)
    print(pipeline.summarize_backtest(backtest))

    print("\n== 3. Risk review of desk orders ==")
    risk = pipeline.evaluate_orders(desk.get("approved_orders", []))
    print(f"{len(risk['approved'])} approved, {len(risk['vetoed'])} vetoed")


if __name__ == "__main__":
    main([s.upper() for s in sys.argv[1:]] or ["SPY", "AAPL"])
