from __future__ import annotations

import csv
import math
import random
import sys
from pathlib import Path


def generate(path: str | Path, rows: int = 30_000, seed: int = 7) -> None:
    random.seed(seed)
    timestamp = 1_700_000_000_000
    spot = 0.08
    futures = spot
    spread = 0.00001
    active_event: tuple[int, int] | None = None

    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp_ms", "spot_bid", "spot_ask", "futures_bid", "futures_ask"])
        for index in range(rows):
            common_return = random.gauss(0.0, 0.00008)
            spot *= math.exp(common_return + random.gauss(0.0, 0.00001))
            futures *= math.exp(common_return + random.gauss(0.0, 0.00001))

            if index > 2_000 and index % 4_000 == 0:
                direction = 1 if (index // 4_000) % 2 == 0 else -1
                spot *= math.exp(direction * 0.0025)
                active_event = (direction, 0)

            if active_event:
                direction, age = active_event
                if age < 30:
                    futures *= math.exp(direction * 0.0025 / 30.0)
                    active_event = (direction, age + 1)
                else:
                    active_event = None

            spot_half = spot * spread / 2.0
            futures_half = futures * spread / 2.0
            writer.writerow(
                [
                    timestamp,
                    spot - spot_half,
                    spot + spot_half,
                    futures - futures_half,
                    futures + futures_half,
                ]
            )
            timestamp += 1_000


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "work/synthetic.csv"
    generate(path)
    print(path)


if __name__ == "__main__":
    main()

