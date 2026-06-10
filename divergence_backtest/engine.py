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
    minimum_futures_repair_share: float = 0.60
    max_confirmation_ms: int = 5 * 60 * 1000
    entry_latency_ms: int = 1_000
    target_reversion_fraction: float = 0.70
    stop_expansion_fraction: float = 0.50
    max_holding_ms: int = 60 * 60 * 1000
    cooldown_ms: int = 10 * 60 * 1000
    fee_bps_per_side: float = 5.0
    slippage_bps_per_side: float = 1.0
    minimum_edge_after_cost_bps: float = 2.0
    max_spread_bps: float = 12.0


@dataclass
class Candidate:
    event_id: int
    trigger_index: int
    trigger_time_ms: int
    direction: int
    center: float
    initial_residual: float
    trigger_spot_mid: float
    trigger_futures_mid: float


@dataclass
class Position:
    event_id: int
    direction: int
    entry_index: int
    entry_time_ms: int
    entry_price: float
    center: float
    entry_residual: float
    trigger_time_ms: int


@dataclass(frozen=True)
class Trade:
    event_id: int
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


@dataclass(frozen=True)
class SignalMark:
    event_id: int
    timestamp_ms: int
    mark: str
    direction: str
    reason: str
    spot_mid: float
    futures_mid: float
    basis_bps: float
    residual_bps: float


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list[Trade]
    signals: list[SignalMark]
    candidates_seen: int
    candidates_rejected_not_spot_led: int
    candidates_expired: int

    def summary(self) -> dict:
        returns = [trade.net_return for trade in self.trades]
        marks_by_type: dict[str, int] = {}
        rejections_by_reason: dict[str, int] = {}
        for signal in self.signals:
            marks_by_type[signal.mark] = marks_by_type.get(signal.mark, 0) + 1
            if signal.mark == "rejected":
                rejections_by_reason[signal.reason] = rejections_by_reason.get(signal.reason, 0) + 1
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
            "signal_marks": len(self.signals),
            "confirmed_signals": sum(signal.mark == "confirmed" for signal in self.signals),
            "marks_by_type": marks_by_type,
            "rejections_by_reason": rejections_by_reason,
        }

    def to_dict(self) -> dict:
        return {
            "config": asdict(self.config),
            "summary": self.summary(),
            "trades": [asdict(trade) for trade in self.trades],
            "signals": [asdict(signal) for signal in self.signals],
        }

    def write_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    def write_signals_csv(self, path: str | Path) -> None:
        fields = list(SignalMark.__dataclass_fields__)
        with Path(path).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(asdict(signal) for signal in self.signals)


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


def spot_lead_assessment(
    quotes: list[Quote], index: int, direction: int, config: BacktestConfig
) -> tuple[bool, str]:
    prior_index = historical_index_at_or_before(
        quotes, index - 1, quotes[index].timestamp_ms - config.move_lookback_ms
    )
    if prior_index is None:
        return False, "insufficient_move_history"
    spot_move = math.log(quotes[index].spot_mid / quotes[prior_index].spot_mid)
    futures_move = math.log(quotes[index].futures_mid / quotes[prior_index].futures_mid)
    minimum_move = config.minimum_spot_move_bps / 10_000.0
    directed_spot_move = direction * spot_move
    directed_futures_move = direction * futures_move
    if directed_spot_move < minimum_move:
        return False, "spot_move_below_minimum"
    if directed_spot_move < config.spot_lead_ratio * max(directed_futures_move, 0.0):
        return False, "spot_not_leading_futures"
    return True, "spot_led_divergence"


def direction_name(direction: int) -> str:
    return "long" if direction > 0 else "short"


def mark_signal(
    signals: list[SignalMark],
    event_id: int,
    quote: Quote,
    mark: str,
    direction: int,
    reason: str,
    center: float,
) -> None:
    signals.append(
        SignalMark(
            event_id=event_id,
            timestamp_ms=quote.timestamp_ms,
            mark=mark,
            direction=direction_name(direction),
            reason=reason,
            spot_mid=quote.spot_mid,
            futures_mid=quote.futures_mid,
            basis_bps=quote.basis * 10_000.0,
            residual_bps=(quote.basis - center) * 10_000.0,
        )
    )


def run_backtest(quotes: list[Quote], config: BacktestConfig | None = None) -> BacktestResult:
    config = config or BacktestConfig()
    for index, quote in enumerate(quotes):
        validate_quote(quote, quotes[index - 1] if index else None)
    history = RollingBasis(config.history_ms)
    candidate: Candidate | None = None
    position: Position | None = None
    trades: list[Trade] = []
    signals: list[SignalMark] = []
    candidates_seen = 0
    rejected_not_spot_led = 0
    candidates_expired = 0
    cooldown_until = -1
    was_in_tail = False
    next_event_id = 1

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
                        event_id=position.event_id,
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
                mark_signal(
                    signals,
                    position.event_id,
                    quote,
                    f"exit_{exit_reason}",
                    position.direction,
                    f"position_closed_by_{exit_reason}",
                    position.center,
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
            closure = abs(candidate.initial_residual) - abs(candidate_residual)
            futures_repair = candidate.direction * math.log(
                quote.futures_mid / candidate.trigger_futures_mid
            )
            futures_repair_share = futures_repair / closure if closure > 0 else 0.0
            if expired or crossed_center:
                candidates_expired += 1
                mark_signal(
                    signals,
                    candidate.event_id,
                    quote,
                    "rejected",
                    candidate.direction,
                    "confirmation_timeout" if expired else "crossed_center_before_entry",
                    candidate.center,
                )
                candidate = None
            elif confirmed and (
                futures_repair <= 0 or futures_repair_share < config.minimum_futures_repair_share
            ):
                candidates_expired += 1
                mark_signal(
                    signals,
                    candidate.event_id,
                    quote,
                    "rejected",
                    candidate.direction,
                    "convergence_not_repaired_by_futures",
                    candidate.center,
                )
                candidate = None
            elif confirmed:
                mark_signal(
                    signals,
                    candidate.event_id,
                    quote,
                    "confirmed",
                    candidate.direction,
                    "futures_started_closing_divergence",
                    candidate.center,
                )
                entry_index = price_at_or_after(
                    quotes, index, quote.timestamp_ms + config.entry_latency_ms
                )
                if entry_index is not None:
                    entry_quote = quotes[entry_index]
                    direction = candidate.direction
                    entry_price = entry_quote.futures_ask if direction > 0 else entry_quote.futures_bid
                    entry_residual = entry_quote.basis - candidate.center
                    expected_reversion_bps = (
                        abs(entry_residual) * config.target_reversion_fraction * 10_000.0
                    )
                    required_edge_bps = (
                        2.0 * (config.fee_bps_per_side + config.slippage_bps_per_side)
                        + config.minimum_edge_after_cost_bps
                    )
                    if (
                        entry_residual * candidate.initial_residual <= 0
                        or expected_reversion_bps <= required_edge_bps
                    ):
                        mark_signal(
                            signals,
                            candidate.event_id,
                            entry_quote,
                            "rejected",
                            direction,
                            "insufficient_remaining_edge_after_costs",
                            candidate.center,
                        )
                    else:
                        position = Position(
                            event_id=candidate.event_id,
                            direction=direction,
                            entry_index=entry_index,
                            entry_time_ms=entry_quote.timestamp_ms,
                            entry_price=entry_price,
                            center=candidate.center,
                            entry_residual=entry_residual,
                            trigger_time_ms=candidate.trigger_time_ms,
                        )
                        mark_signal(
                            signals,
                            candidate.event_id,
                            entry_quote,
                            "entry",
                            direction,
                            "entered_after_latency_with_positive_expected_edge",
                            candidate.center,
                        )
                else:
                    mark_signal(
                        signals,
                        candidate.event_id,
                        quote,
                        "rejected",
                        candidate.direction,
                        "no_quote_after_entry_latency",
                        candidate.center,
                    )
                candidate = None

        spreads_ok = (
            spread_bps(quote.spot_bid, quote.spot_ask) <= config.max_spread_bps
            and spread_bps(quote.futures_bid, quote.futures_ask) <= config.max_spread_bps
        )
        tail_started = in_tail and not was_in_tail
        if (
            position is None
            and candidate is None
            and quote.timestamp_ms >= cooldown_until
            and tail_started
        ):
            event_id = next_event_id
            next_event_id += 1
            candidates_seen += 1
            # Positive residual means futures is expensive, so trade futures short.
            direction = -1 if residual > 0 else 1
            mark_signal(signals, event_id, quote, "detected", direction, "basis_entered_historical_tail", center)
            if not spreads_ok:
                mark_signal(
                    signals, event_id, quote, "rejected", direction, "quoted_spread_above_limit", center
                )
            else:
                spot_led, reason = spot_lead_assessment(quotes, index, direction, config)
                if spot_led:
                    candidate = Candidate(
                        event_id=event_id,
                        trigger_index=index,
                        trigger_time_ms=quote.timestamp_ms,
                        direction=direction,
                        center=center,
                        initial_residual=residual,
                        trigger_spot_mid=quote.spot_mid,
                        trigger_futures_mid=quote.futures_mid,
                    )
                    mark_signal(signals, event_id, quote, "candidate", direction, reason, center)
                else:
                    rejected_not_spot_led += 1
                    mark_signal(signals, event_id, quote, "rejected", direction, reason, center)

        history.append(quote.timestamp_ms, quote.basis)
        was_in_tail = in_tail

    if candidate is not None and quotes:
        mark_signal(
            signals,
            candidate.event_id,
            quotes[-1],
            "rejected",
            candidate.direction,
            "end_of_data_before_confirmation",
            candidate.center,
        )
    if position is not None and quotes:
        mark_signal(
            signals,
            position.event_id,
            quotes[-1],
            "open_end_of_data",
            position.direction,
            "position_remained_open_at_end_of_data",
            position.center,
        )

    return BacktestResult(
        config=config,
        trades=trades,
        signals=signals,
        candidates_seen=candidates_seen,
        candidates_rejected_not_spot_led=rejected_not_spot_led,
        candidates_expired=candidates_expired,
    )
