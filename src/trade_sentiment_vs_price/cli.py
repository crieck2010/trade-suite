"""Command-line interface for trade-sentiment-vs-price."""

from __future__ import annotations

import argparse
import csv
import json

from . import __version__
from .adapters import from_sentiment_scan, prices_from_dict_bars, to_agent_report
from .correlation import contemporaneous, lead_lag, rolling_correlation
from .events import detect_bursts, event_study
from .indicators import composite_attention
from .licensing import check_license, check_update
from .predict import forward_regression, information_coefficient, sign_accuracy
from .series import align, demo_data
from .signals import attention_rule, summarize_trades, zscore_rule


def load_inputs(args):
    if args.demo:
        sent, prices = demo_data(n_days=args.days, seed=11, lead=1,
                                 symbol=args.symbol)
        return args.symbol, sent, prices
    sent_rows = list(csv.DictReader(open(args.sentiment, newline="")))
    price_rows = list(csv.DictReader(open(args.prices, newline="")))
    return args.symbol, from_sentiment_scan(sent_rows), prices_from_dict_bars(price_rows)


def add_input_args(p):
    p.add_argument("--symbol", default="DEMO")
    p.add_argument("--demo", action="store_true",
                   help="use synthetic data with a 1-day sentiment lead")
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--sentiment", help="CSV: date,symbol,bullishness,conviction,mentions")
    p.add_argument("--prices", help="CSV: date,close")


def cmd_correlate(args):
    symbol, sent, prices = load_inputs(args)
    a = align(symbol, sent, prices)
    print(json.dumps({
        "symbol": symbol,
        "contemporaneous": contemporaneous(a),
        "lead_lag": {k: v for k, v in lead_lag(a, max_lag=args.max_lag).items()
                     if k != "lags"},
        "lag_table": lead_lag(a, max_lag=args.max_lag)["lags"],
    }, indent=2))
    return 0


def cmd_events(args):
    symbol, sent, prices = load_inputs(args)
    a = align(symbol, sent, prices)
    ev = detect_bursts(a, z_thresh=args.z, on=args.on)
    es = event_study(a, ev, pre=args.pre, post=args.post)
    es.pop("events")
    print(json.dumps({"symbol": symbol, "n_bursts": len(ev), **es}, indent=2))
    return 0


def cmd_ic(args):
    symbol, sent, prices = load_inputs(args)
    a = align(symbol, sent, prices)
    print(json.dumps({
        "symbol": symbol,
        "ic": information_coefficient(a, horizon=args.horizon),
        "sign_accuracy": sign_accuracy(a, horizon=args.horizon),
        "forward_regression": forward_regression(a, horizon=args.horizon),
    }, indent=2))
    return 0


def cmd_signals(args):
    symbol, sent, prices = load_inputs(args)
    a = align(symbol, sent, prices)
    print(json.dumps({
        "symbol": symbol,
        "zscore_rule": summarize_trades(zscore_rule(a, horizon=args.horizon)),
        "attention_rule": summarize_trades(attention_rule(a, horizon=args.horizon)),
    }, indent=2))
    return 0


def cmd_indicators(args):
    symbol, sent, prices = load_inputs(args)
    a = align(symbol, sent, prices)
    rows = composite_attention(a)
    print(json.dumps({"symbol": symbol, "latest": rows[-1],
                      "n": len(rows)}, indent=2))
    return 0


def cmd_report(args):
    symbol, sent, prices = load_inputs(args)
    print(json.dumps(to_agent_report(symbol, sent, prices), indent=2))
    return 0


def cmd_license(_a):
    print(json.dumps(check_license(), indent=2))
    return 0


def cmd_update_check(_a):
    print(json.dumps(check_update(), indent=2))
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="trade-sentiment-vs-price",
                                 description="Sentiment vs price analysis")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("correlate", help="contemporaneous + lead/lag correlation")
    add_input_args(p)
    p.add_argument("--max-lag", type=int, default=5)
    p.set_defaults(func=cmd_correlate)

    p = sub.add_parser("events", help="burst detection + event-study CAR")
    add_input_args(p)
    p.add_argument("--z", type=float, default=2.0)
    p.add_argument("--on", choices=["mentions", "sentiment_change"], default="mentions")
    p.add_argument("--pre", type=int, default=5)
    p.add_argument("--post", type=int, default=10)
    p.set_defaults(func=cmd_events)

    p = sub.add_parser("ic", help="information coefficient + forward regression")
    add_input_args(p)
    p.add_argument("--horizon", type=int, default=1)
    p.set_defaults(func=cmd_ic)

    p = sub.add_parser("signals", help="evaluate simple sentiment rules")
    add_input_args(p)
    p.add_argument("--horizon", type=int, default=5)
    p.set_defaults(func=cmd_signals)

    p = sub.add_parser("indicators", help="latest composite indicator bundle")
    add_input_args(p)
    p.set_defaults(func=cmd_indicators)

    p = sub.add_parser("report", help="full agent-ready JSON report")
    add_input_args(p)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("license", help="check the license-key hook")
    p.set_defaults(func=cmd_license)
    p = sub.add_parser("update-check", help="check for a newer release")
    p.set_defaults(func=cmd_update_check)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)
