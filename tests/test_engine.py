import tempfile
import unittest
from pathlib import Path

from divergence_backtest.engine import (
    BacktestConfig,
    Quote,
    load_quotes,
    percentile,
    run_backtest,
    wilson_interval,
)
from divergence_backtest.synthetic import generate
from divergence_backtest.visualize import write_signal_chart


class EngineTests(unittest.TestCase):
    def test_percentile(self):
        self.assertEqual(percentile([1, 2, 3], 0.5), 2)
        self.assertEqual(percentile([1, 3], 0.5), 2)

    def test_wilson_interval_contains_observed_rate(self):
        lower, upper = wilson_interval(8, 10)
        self.assertLess(lower, 0.8)
        self.assertGreater(upper, 0.8)

    def test_rejects_unsorted_quotes(self):
        with self.assertRaises(ValueError):
            run_backtest(
                [
                    Quote(2, 1, 1.1, 1, 1.1),
                    Quote(1, 1, 1.1, 1, 1.1),
                ]
            )

    def test_synthetic_events_produce_trades(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.csv"
            generate(path, rows=15_000)
            quotes = load_quotes(path)
            config = BacktestConfig(
                history_ms=2_000_000,
                minimum_history=1_000,
                tail_quantile=0.995,
                move_lookback_ms=60_000,
                minimum_spot_move_bps=2.0,
                confirmation_fraction=0.05,
                max_confirmation_ms=120_000,
                entry_latency_ms=1_000,
                target_reversion_fraction=0.5,
                max_holding_ms=600_000,
                cooldown_ms=60_000,
                fee_bps_per_side=0.0,
                slippage_bps_per_side=0.0,
            )
            result = run_backtest(quotes, config)
            self.assertGreater(len(result.trades), 0)
            self.assertGreater(result.summary()["win_rate"], 0.5)
            marks = {signal.mark for signal in result.signals}
            self.assertIn("detected", marks)
            self.assertIn("candidate", marks)
            self.assertIn("confirmed", marks)
            self.assertIn("entry", marks)
            self.assertTrue(any(mark.startswith("exit_") for mark in marks))

            signals_path = Path(directory) / "signals.csv"
            result.write_signals_csv(signals_path)
            exported = signals_path.read_text(encoding="utf-8")
            self.assertIn("event_id,timestamp_ms,mark,direction,reason", exported)
            self.assertIn("confirmed", exported)

            chart_path = Path(directory) / "signals.html"
            write_signal_chart(quotes, result, chart_path)
            chart = chart_path.read_text(encoding="utf-8")
            self.assertIn("DOGEUSDT Spot / Futures Signal Marks", chart)
            self.assertIn('"mark":"confirmed"', chart)

    def test_unprofitable_confirmed_signal_is_marked_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.csv"
            generate(path, rows=15_000)
            config = BacktestConfig(
                history_ms=2_000_000,
                minimum_history=1_000,
                tail_quantile=0.995,
                move_lookback_ms=60_000,
                minimum_spot_move_bps=2.0,
                confirmation_fraction=0.05,
                max_confirmation_ms=120_000,
                entry_latency_ms=1_000,
                target_reversion_fraction=0.5,
                max_holding_ms=600_000,
                cooldown_ms=60_000,
                fee_bps_per_side=0.0,
                slippage_bps_per_side=0.0,
                minimum_edge_after_cost_bps=1_000.0,
            )
            result = run_backtest(load_quotes(path), config)
            reasons = {signal.reason for signal in result.signals if signal.mark == "rejected"}
            self.assertIn("insufficient_remaining_edge_after_costs", reasons)
            self.assertEqual(len(result.trades), 0)


if __name__ == "__main__":
    unittest.main()
