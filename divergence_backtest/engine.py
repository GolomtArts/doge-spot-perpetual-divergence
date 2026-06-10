from __future__ import annotations

import csv
import json
import math
from bisect import bisect_left, insort
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Quote:
    timestamp_ms: int
    spot_bid: float
    spot_ask: float
    futures_bid: float
    futures_ask: float

    @property
    def spot_mid(self) -> float:
        return (self.spot_bid + self.spot_ask) / 2.0

    @property
    def futures_mid(self) -> float:
        return (self.futures_bid + self.futures_ask) / 2.0

    @property
    def basis(self) -> float:
        return math.log(self.futures_mid / self.spot_mid)


@dataclass(frozen=True)
class BacktestConfig:
    history_ms: int = 6 * 60 * 60 * 1000
    minimum_history: int = 1_000
    tail_quantile: float = 0.999
    move_lookback_ms: int = 60_000
    spot_lead_ratio: float = 1.5
    minimum_spot_move_bps: float = 4.0
    confirmation_fraction: float = 0.15
    max_confirmation_ms: int = 5 * 60 * 1000
    entry_latency_ms: int = 1_000
    target_reversion_fraction: float = 0.70
    stop_expansion_fraction: float = 0.50
    max_holding_ms: int = 60 * 60 * 1000
    cooldown_ms: int = 10 * 60 * 1000
    fee_bps_per_side: float = 5.0
    slippage_bps_per_side: float = 1.0
    max_spread_bps: float = 12.0


@dataclass
class Candidate:
    trigger_index: int
    trigger_time_ms: int
    direction: int
    center: float
    initial_residual: float


@dataclass
class Position:
    direction: int
    entry_index: int
    entry_time_ms: int
    entry_price: float
    center: float
    entry_residual: float
    trigger_time_ms: int


@dataclass(frozen=True)
class Trade:
    direction: str
    trigger_time_ms: int
    entry_time_ms: int
    exit_time_ms: int
    entry_price: float
    exit_price: float
    gross_return: float
    net_return: float
    holding_ms: int
    exit_reason: str
    entry_residual_bps: float
    exit_residual_bps: float


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list[Trade]
    candidates_seen: int
    candidates_rejected_not_spot_led: int
    candidates_expired: int

    def summary(self) -> dict:
        returns = [trade.net_return for trade in self.trades]
        wins = sum(value > 0 for value in returns)
        losses = sum(value <= 0 for value in returns)
        n = len(returns)
        win_rate = wins / n if n else 0.0
        mean_return = sum(returns) / n if n else 0.0
        gross_profit = sum(value for value in returns if value > 0)
        gross_loss = -sum(value for value in returns if value < 0)
        profit_factor = gross_profit / gross_loss if gross_loss else None
        lower, upper = wilson_interval(wins, n)
        return {
            "trades": n,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "win_rate_wilson_95_lower": lower,
            "win_rate_wilson_95_upper": upper,
            "mean_net_return": mean_return,
            "total_net_return_uncompounded": sum(returns),
            "profit_factor": profit_factor,
            "candidates_seen": self.candidates_seen,
            "candidates_rejected_not_spot_led": self.candidates_rejected_not_spot_led,
            "candidates_expired": self.candidates_expired,
        }

    def to_dict(self) -> dict:
        return {
            "config": asdict(self.config),
            "summary": self.summary(),
            "trades": [asdict(trade) for trade in self.trades],
        }

    def write_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


class RollingBasis:
    def __init__(self, history_ms: int):
        self.history_ms = history_ms
        self.time_ordered: deque[tuple[int, float]] = deque()
        self.sorted_values: list[float] = []

    def expire(self, timestamp_ms: int) -> None:
        cutoff = timestamp_ms - self.history_ms
        while self.time_ordered and self.time_ordered[0][0] < cutoff:
            _, value = self.time_ordered.popleft()
            index = bisect_left(self.sorted_values, value)
            self.sorted_values.pop(index)

    def append(self, timestamp_ms: int, value: float) -> None:
        self.time_ordered.append((timestamp_ms, value))
        insort(self.sorted_values, value)

    def percentile(self, probability: float) -> float:
        return percentile_sorted(self.sorted_values, probability)

    def __len__(self) -> int:
        return len(self.sorted_values)


def load_quotes(path: str | Path) -> list[Quote]:
    quotes: list[Quote] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp_ms", "spot_bid", "spot_ask", "futures_bid", "futures_ask"}
        if not required.issubset(reader.fieldnames or []):
            missing = sorted(required - set(reader.fieldnames or []))
            raise ValueError(f"Missing CSV columns: {', '.join(missing)}")
        for row in reader:
            quote = Quote(
                timestamp_ms=int(row["timestamp_ms"]),
                spot_bid=float(row["spot_bid"]),
                spot_ask=float(row["spot_ask"]),
                futures_bid=float(row["futures_bid"]),
                futures_ask=float(row["futures_ask"]),
            )
            validate_quote(quote, quotes[-1] if quotes else None)
            quotes.append(quote)
    return quotes


def validate_quote(quote: Quote, previous: Quote | None = None) -> None:
    prices = (quote.spot_bid, quote.spot_ask, quote.futures_bid, quote.futures_ask)
    if any(not math.isfinite(price) or price <= 0 for price in prices):
        raise ValueError(f"Invalid non-positive price at {quote.timestamp_ms}")
    if quote.spot_ask < quote.spot_bid or quote.futures_ask < quote.futures_bid:
        raise ValueError(f"Ask below bid at {quote.timestamp_ms}")
    if previous and quote.timestamp_ms <= previous.timestamp_ms:
        raise ValueError("Timestamps must be strictly increasing")


def percentile(values: Iterable[float], probability: float) -> float:
    ordered = sorted(values)
    return percentile_sorted(ordered, probability)


def percentile_sorted(ordered: list[float], probability: float) -> float:
    if not ordered:
        raise ValueError("Cannot compute percentile of empty values")
    index = probability * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def wilson_interval(successes: int, trials: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if trials == 0:
        return 0.0, 0.0
    p = successes / trials
    denominator = 1.0 + z * z / trials
    center = (p + z * z / (2.0 * trials)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * trials)) / trials) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def spread_bps(bid: float, ask: float) -> float:
    return (ask - bid) / ((ask + bid) / 2.0) * 10_000.0


def price_at_or_after(quotes: list[Quote], start_index: int, timestamp_ms: int) -> int | None:
    for index in range(start_index, len(quotes)):
        if quotes[index].timestamp_ms >= timestamp_ms:
            return index
    return None


def historical_index_at_or_before(quotes: list[Quote], current_index: int, timestamp_ms: int) -> int | None:
    for index in range(current_index, -1, -1):
        if quotes[index].timestamp_ms <= timestamp_ms:
            return index
    return None


def is_spot_led(quotes: list[Quote], index: int, direction: int, config: BacktestConfig) -> bool:
    prior_index = historical_index_at_or_before(
        quotes, index - 1, quotes[index].timestamp_ms - config.move_lookback_ms
    )
    if prior_index is None:
        return False
    spot_move = math.log(quotes[index].spot_mid / quotes[prior_index].spot_mid)
    futures_move = math.log(quotes[index].futures_mid / quotes[prior_index].futures_mid)
    minimum_move = config.minimum_spot_move_bps / 10_000.0
    return (
        direction * spot_move >= minimum_move
        and direction * spot_move >= config.spot_lead_ratio * max(direction * futures_move, 0.0)
    )


def run_backtest(quotes: list[Quote], config: BacktestConfig | None = None) -> BacktestResult:
    config = config or BacktestConfig()
    for index, quote in enumerate(quotes):
        validate_quote(quote, quotes[index - 1] if index else None)
    history = RollingBasis(config.history_ms)
    candidate: Candidate | None = None
    position: Position | None = None
    trades: list[Trade] = []
    candidates_seen = 0
    rejected_not_spot_led = 0
    candidates_expired = 0
    cooldown_until = -1
    was_in_tail = False

    for index, quote in enumerate(quotes):
        history.expire(quote.timestamp_ms)

        if len(history) >= config.minimum_history:
            center = history.percentile(0.5)
            tail_probability = (1.0 - config.tail_quantile) / 2.0
            lower_bound = history.percentile(tail_probability)
            upper_bound = history.percentile(1.0 - tail_probability)
            residual = quote.basis - center
        else:
            center = 0.0
            lower_bound = -math.inf
            upper_bound = math.inf
            residual = 0.0
        in_tail = quote.basis < lower_bound or quote.basis > upper_bound

        if position is not None and index >= position.entry_index:
            position_residual = quote.basis - position.center
            entry_abs = abs(position.entry_residual)
            current_abs = abs(position_residual)
            target_hit = current_abs <= entry_abs * (1.0 - config.target_reversion_fraction)
            stop_hit = (
                position_residual * position.direction < 0
                and current_abs >= entry_abs * (1.0 + config.stop_expansion_fraction)
            )
            timed_out = quote.timestamp_ms - position.entry_time_ms >= config.max_holding_ms
            if target_hit or stop_hit or timed_out:
                exit_reason = "target" if target_hit else "stop" if stop_hit else "time"
                exit_price = quote.futures_bid if position.direction > 0 else quote.futures_ask
                gross_return = position.direction * math.log(exit_price / position.entry_price)
                costs = 2.0 * (config.fee_bps_per_side + config.slippage_bps_per_side) / 10_000.0
                trades.append(
                    Trade(
                        direction="long" if position.direction > 0 else "short",
                        trigger_time_ms=position.trigger_time_ms,
                        entry_time_ms=position.entry_time_ms,
                        exit_time_ms=quote.timestamp_ms,
                        entry_price=position.entry_price,
                        exit_price=exit_price,
                        gross_return=gross_return,
                        net_return=gross_return - costs,
                        holding_ms=quote.timestamp_ms - position.entry_time_ms,
                        exit_reason=exit_reason,
                        entry_residual_bps=position.entry_residual * 10_000.0,
                        exit_residual_bps=position_residual * 10_000.0,
                    )
                )
                position = None
                cooldown_until = quote.timestamp_ms + config.cooldown_ms

        if position is None and candidate is not None:
            candidate_residual = quote.basis - candidate.center
            expired = quote.timestamp_ms - candidate.trigger_time_ms > config.max_confirmation_ms
            crossed_center = candidate_residual * candidate.initial_residual <= 0
            confirmed = (
                abs(candidate_residual)
                <= abs(candidate.initial_residual) * (1.0 - config.confirmation_fraction)
                and candidate_residual * candidate.initial_residual > 0
            )
            if expired or crossed_center:
                candidates_expired += 1
                candidate = None
            elif confirmed:
                entry_index = price_at_or_after(
                    quotes, index, quote.timestamp_ms + config.entry_latency_ms
                )
                if entry_index is not None:
                    entry_quote = quotes[entry_index]
                    direction = candidate.direction
                    entry_price = entry_quote.futures_ask if direction > 0 else entry_quote.futures_bid
                    entry_residual = entry_quote.basis - candidate.center
                    position = Position(
                        direction=direction,
                        entry_index=entry_index,
                        entry_time_ms=entry_quote.timestamp_ms,
                        entry_price=entry_price,
                        center=candidate.center,
                        entry_residual=entry_residual,
                        trigger_time_ms=candidate.trigger_time_ms,
                    )
                candidate = None

        spreads_ok = (
            spread_bps(quote.spot_bid, quote.spot_ask) <= config.max_spread_bps
            and spread_bps(quote.futures_bid, quote.futures_ask) <= config.max_spread_bps
        )
        if (
            position is None
            and candidate is None
            and quote.timestamp_ms >= cooldown_until
            and in_tail
            and not was_in_tail
            and spreads_ok
        ):
            candidates_seen += 1
            # Positive residual means futures is expensive, so trade futures short.
            direction = -1 if residual > 0 else 1
            if is_spot_led(quotes, index, direction, config):
                candidate = Candidate(
                    trigger_index=index,
                    trigger_time_ms=quote.timestamp_ms,
                    direction=direction,
                    center=center,
                    initial_residual=residual,
                )
            else:
                rejected_not_spot_led += 1

        history.append(quote.timestamp_ms, quote.basis)
        was_in_tail = in_tail

    return BacktestResult(
        config=config,
        trades=trades,
        candidates_seen=candidates_seen,
        candidates_rejected_not_spot_led=rejected_not_spot_led,
        candidates_expired=candidates_expired,
    )
