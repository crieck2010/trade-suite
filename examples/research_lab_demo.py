"""Research-lab demo: one thin workflow per new quant engine, all on demo data.

Usage:
    PYTHONPATH=src python examples/research_lab_demo.py [SYMBOL ...]

Needs the sibling engines importable (pip install -r requirements.txt, or
extend PYTHONPATH with each engine's src/ directory).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from trade_suite import pipeline  # noqa: E402


def main(symbols: list[str]) -> None:
    print("== 1. Pairs screen ==")
    print(pipeline.summarize_pairs(
        pipeline.run_pairs_screen(symbols, source="demo", max_pairs=5)))

    print("\n== 2. Order-book simulation ==")
    print(pipeline.summarize_orderbook(
        pipeline.run_orderbook_sim(symbol=symbols[0], quantity=120.0)))

    print("\n== 3. Portfolio optimization ==")
    print(pipeline.summarize_optimize(
        pipeline.run_optimize(symbols, source="demo", method="max_sharpe")))

    print("\n== 4. Monte Carlo VaR ==")
    print(pipeline.summarize_montecarlo(
        pipeline.run_montecarlo(symbols[:2], source="demo",
                                n_paths=2_000, n_steps=60)))

    print("\n== 5. Factor analysis ==")
    print(pipeline.summarize_factors(
        pipeline.run_factor_analysis(symbols[:2], source="demo", model="ff3")))

    print("\n== 6. Sentiment vs price ==")
    print(pipeline.summarize_sentiment_price(
        pipeline.run_sentiment_price(symbols[0], source="demo")))

    print("\n== 7. Vol surface ==")
    print(pipeline.summarize_volsurface(
        pipeline.run_vol_surface(symbol=symbols[0])))

    print("\n== 8. Enriched research pipeline ==")
    out = pipeline.research_pipeline(symbols[:1], source="demo", days=250,
                                     sentiment_price=True, factor_model="ff3")
    print("enrichments:", sorted(k for k in out if k not in
                                 {"desk", "backtest", "risk"}))


if __name__ == "__main__":
    main([s.upper() for s in sys.argv[1:]] or ["SPY", "AAPL", "MSFT"])
