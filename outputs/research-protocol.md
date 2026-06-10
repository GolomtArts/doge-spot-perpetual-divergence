# DOGE Spot/Perpetual Divergence Research Protocol

## Hypothesis

When Binance Spot `DOGEUSDT` and Binance Futures `DOGEUSDT` enter an unusual
price relationship, a subset of events is repaired primarily by the perpetual
market. Those events may predict a tradeable future return in the perpetual.

This is a single-leg statistical trading hypothesis, not risk-free arbitrage.

## Required real data

Collect synchronized exchange-timestamped snapshots containing:

```text
timestamp_ms
spot_best_bid
spot_best_ask
futures_best_bid
futures_best_ask
```

Recommended additional fields:

```text
spot bid/ask depth at several levels
futures bid/ask depth at several levels
spot and futures trades with aggressor side
futures mark price
futures index price
funding rate
liquidation events
```

Candles and last-trade prices are not sufficient.

## Frozen first hypothesis

Only investigate events satisfying all conditions:

1. The current basis enters a tail estimated only from earlier observations.
2. The divergence-forming price move is led by spot.
3. Both spot and futures quoted spreads remain below a fixed safety limit.
4. The divergence persists and futures begins closing it before entry.
5. Futures contributes the configured minimum share of the observed convergence;
   spot retreat alone cannot confirm a signal.
6. Entry occurs after a simulated execution delay at the futures bid or ask.
7. Remaining expected movement exceeds fees, slippage, and a safety margin.

Exit on:

1. A fixed fraction of basis convergence.
2. Adverse basis expansion.
3. Maximum holding time.

Never add to a losing position.

## Scientific acceptance criteria

Parameters must be frozen before evaluating the final untouched holdout sample.
The model is accepted only if:

```text
out-of-sample net expectation > 0
win-rate confidence lower bound exceeds the chosen minimum
results survive realistic fee, slippage, and latency stress tests
tail losses do not erase a large share of prior gains
enough independent events exist for a meaningful conclusion
```

Compare at minimum:

```text
Model A: spot-led divergence plus futures convergence confirmation
Model B: trade every extreme basis event
Null: randomized event directions and timestamps
```

The strategy earns further development only when Model A beats both alternatives
on untouched data.
