from __future__ import annotations

import argparse
import json

from .engine import BacktestConfig, load_quotes, run_backtest
from .visualize import write_signal_chart


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Backtest spot/perpetual divergence events")
    result.add_argument("csv", help="Synchronized BBO CSV")
    result.add_argument("--report", help="Write full JSON report")
    result.add_argument("--signals", help="Write every detected/rejected/confirmed signal mark to CSV")
    result.add_argument("--chart", help="Write an HTML price chart with signal markers")
    result.add_argument("--tail-quantile", type=float, default=0.999)
    result.add_argument("--minimum-history", type=int, default=1_000)
    result.add_argument("--entry-latency-ms", type=int, default=1_000)
    result.add_argument("--max-holding-minutes", type=float, default=60.0)
    result.add_argument("--fee-bps", type=float, default=5.0)
    result.add_argument("--slippage-bps", type=float, default=1.0)
    return result


def main() -> None:
    args = parser().parse_args()
    config = BacktestConfig(
        tail_quantile=args.tail_quantile,
        minimum_history=args.minimum_history,
        entry_latency_ms=args.entry_latency_ms,
        max_holding_ms=int(args.max_holding_minutes * 60_000),
        fee_bps_per_side=args.fee_bps,
        slippage_bps_per_side=args.slippage_bps,
    )
    quotes = load_quotes(args.csv)
    result = run_backtest(quotes, config)
    if args.report:
        result.write_json(args.report)
    if args.signals:
        result.write_signals_csv(args.signals)
    if args.chart:
        write_signal_chart(quotes, result, args.chart)
    print(json.dumps(result.summary(), indent=2))


if __name__ == "__main__":
    main()
