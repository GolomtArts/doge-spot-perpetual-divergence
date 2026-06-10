from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from .binance import BinanceMarketData
from .config import BinanceConfig


FIELDS = [
    "timestamp_ms",
    "spot_bid",
    "spot_ask",
    "futures_bid",
    "futures_ask",
    "spot_observed_at_ms",
    "futures_observed_at_ms",
    "observation_gap_ms",
    "spot_request_duration_ms",
    "futures_request_duration_ms",
]


def collect(
    output: str | Path,
    symbol: str = "DOGEUSDT",
    interval_seconds: float = 1.0,
    samples: int = 0,
    max_observation_gap_ms: int = 1_000,
    env_path: str | Path = ".env",
) -> int:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    client = BinanceMarketData(BinanceConfig.from_env(env_path))
    write_header = not path.exists() or path.stat().st_size == 0
    written = 0

    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if write_header:
            writer.writeheader()
        while samples == 0 or written < samples:
            loop_started = time.monotonic()
            spot, futures = client.synchronized_book_tickers(symbol)
            observation_gap = abs(spot.observed_at_ms - futures.observed_at_ms)
            if observation_gap <= max_observation_gap_ms:
                writer.writerow(
                    {
                        "timestamp_ms": max(spot.observed_at_ms, futures.observed_at_ms),
                        "spot_bid": spot.bid,
                        "spot_ask": spot.ask,
                        "futures_bid": futures.bid,
                        "futures_ask": futures.ask,
                        "spot_observed_at_ms": spot.observed_at_ms,
                        "futures_observed_at_ms": futures.observed_at_ms,
                        "observation_gap_ms": observation_gap,
                        "spot_request_duration_ms": spot.request_duration_ms,
                        "futures_request_duration_ms": futures.request_duration_ms,
                    }
                )
                handle.flush()
                written += 1
            remaining = interval_seconds - (time.monotonic() - loop_started)
            if remaining > 0:
                time.sleep(remaining)
    return written


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Collect synchronized Binance spot/futures BBO")
    result.add_argument("--output", default="work/binance-dogeusdt-bbo.csv")
    result.add_argument("--symbol", default="DOGEUSDT")
    result.add_argument("--interval-seconds", type=float, default=1.0)
    result.add_argument("--samples", type=int, default=0, help="0 collects until interrupted")
    result.add_argument("--max-observation-gap-ms", type=int, default=1_000)
    result.add_argument("--env", default=".env")
    return result


def main() -> None:
    args = parser().parse_args()
    count = collect(
        output=args.output,
        symbol=args.symbol,
        interval_seconds=args.interval_seconds,
        samples=args.samples,
        max_observation_gap_ms=args.max_observation_gap_ms,
        env_path=args.env,
    )
    print(f"Wrote {count} synchronized samples to {args.output}")


if __name__ == "__main__":
    main()

