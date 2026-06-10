import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from divergence_backtest.binance import BinanceMarketData
from divergence_backtest.config import BinanceConfig, load_env


class BinanceTests(unittest.TestCase):
    def test_load_env_does_not_override_existing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("BINANCE_API_KEY=file-key\n", encoding="utf-8")
            with patch.dict(os.environ, {"BINANCE_API_KEY": "existing-key"}, clear=False):
                load_env(path)
                self.assertEqual(os.environ["BINANCE_API_KEY"], "existing-key")

    def test_book_ticker_parsing(self):
        client = BinanceMarketData(BinanceConfig())
        with patch.object(
            client,
            "_get",
            return_value={"bidPrice": "0.1000", "askPrice": "0.1001"},
        ):
            ticker = client._book_ticker("https://example.com", "/book", "DOGEUSDT")
        self.assertEqual(ticker.bid, 0.1)
        self.assertEqual(ticker.ask, 0.1001)


if __name__ == "__main__":
    unittest.main()
