# DOGE Spot/Perpetual Divergence Research Backtester

This repository contains a causal, event-driven backtester for studying whether
Binance `DOGEUSDT` spot/perpetual divergences predict subsequent perpetual
returns.

It intentionally avoids technical indicators. Signals are built from synchronized
best bid/ask quotes, event ordering, and historical tail probabilities.

## Data format

Input is a time-ordered CSV file:

```csv
timestamp_ms,spot_bid,spot_ask,futures_bid,futures_ask
1700000000000,0.08000,0.08001,0.08000,0.08001
```

Each row must be a synchronized snapshot. Prices must be positive and asks must
not be below bids.

## Signal model

The backtester:

1. Computes the log mid-price basis `log(F / S)`.
2. Uses only earlier observations to estimate the normal basis and a tail
   threshold.
3. Starts a candidate only when the residual basis enters a historical tail.
4. Requires the divergence-forming move to be led by spot.
5. Waits for futures to begin closing the divergence before entering.
6. Executes on futures bid/ask after configurable latency.
7. Exits on convergence, adverse expansion, or a time limit.

This is a testable research hypothesis, not an assertion that the strategy has
an edge.

## Run

Create a local configuration file:

```bash
cp .env.example .env
```

Market-data collection uses public Binance endpoints, so API credentials are
optional. When private account or trading functionality is added later, place
the credentials only in `.env`; it is excluded from Git.

Collect synchronized Binance Spot/Futures `DOGEUSDT` best bid/ask snapshots:

```bash
python3 -m divergence_backtest.collect --samples 100
```

Collect continuously until interrupted:

```bash
python3 -m divergence_backtest.collect
```

Backtest collected data:

```bash
python3 -m divergence_backtest.cli work/binance-dogeusdt-bbo.csv \
  --report outputs/binance-backtest-report.json \
  --signals outputs/binance-signal-marks.csv
```

Every independent tail event receives an `event_id`. The signal CSV records its
full lifecycle:

```text
detected   basis entered its historical tail
candidate  spread and spot-lead hard conditions passed
confirmed  futures began closing the divergence; trade signal is valid
entry      simulated futures entry after configured latency
rejected   condition failed, with the exact reason recorded
exit_*     target, stop, or time exit
```

Only `confirmed` marks are actionable trade signals. `detected` marks are
observations, not permission to trade.

A confirmed signal is allowed only when convergence is primarily repaired by
futures rather than spot retreating, and when the remaining expected move after
entry latency exceeds round-trip fees, slippage, and the configured safety
margin. Failed conditions are exported with their exact rejection reason.

Generate synthetic data and run a backtest:

```bash
python3 -m divergence_backtest.synthetic work/synthetic.csv
python3 -m divergence_backtest.cli work/synthetic.csv --report outputs/report.json
```

Run tests:

```bash
python3 -m unittest discover -s tests -v
```

## Important limitations

- Public candle data is insufficient. Real research requires synchronized BBO
  or order-book snapshots with exchange timestamps.
- The included REST collector is suitable for initial research, but serious
  microstructure research should later use WebSocket order-book streams.
- The strategy is single-leg statistical trading, not risk-free arbitrage.
- Rare events require a long history and a genuinely untouched final test set.
- Parameters must be frozen before evaluating the final holdout period.
