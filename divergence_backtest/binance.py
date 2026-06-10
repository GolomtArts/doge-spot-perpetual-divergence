from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .config import BinanceConfig


@dataclass(frozen=True)
class BookTicker:
    bid: float
    ask: float
    observed_at_ms: int
    request_duration_ms: int


class BinanceMarketData:
    """Small dependency-free client for public Binance best-bid/ask data."""

    def __init__(self, config: BinanceConfig | None = None, timeout_seconds: float = 5.0):
        self.config = config or BinanceConfig.from_env()
        self.timeout_seconds = timeout_seconds

    def _get(self, base_url: str, path: str, params: dict[str, str]) -> dict:
        url = f"{base_url.rstrip('/')}{path}?{urllib.parse.urlencode(params)}"
        headers = {"User-Agent": "doge-divergence-research/0.1"}
        if self.config.api_key:
            headers["X-MBX-APIKEY"] = self.config.api_key
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _book_ticker(self, base_url: str, path: str, symbol: str) -> BookTicker:
        started_ns = time.time_ns()
        payload = self._get(base_url, path, {"symbol": symbol.upper()})
        ended_ns = time.time_ns()
        return BookTicker(
            bid=float(payload["bidPrice"]),
            ask=float(payload["askPrice"]),
            observed_at_ms=(started_ns + ended_ns) // 2_000_000,
            request_duration_ms=(ended_ns - started_ns) // 1_000_000,
        )

    def synchronized_book_tickers(self, symbol: str = "DOGEUSDT") -> tuple[BookTicker, BookTicker]:
        with ThreadPoolExecutor(max_workers=2) as executor:
            spot_future = executor.submit(
                self._book_ticker,
                self.config.spot_rest_url,
                "/api/v3/ticker/bookTicker",
                symbol,
            )
            futures_future = executor.submit(
                self._book_ticker,
                self.config.futures_rest_url,
                "/fapi/v1/ticker/bookTicker",
                symbol,
            )
            return spot_future.result(), futures_future.result()

