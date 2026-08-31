"""Provider-independent contracts for Market Regime V1.4 diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import math
from numbers import Real

from private_quant.backtest.regime_stabilization import (
    ALLOWED_EXPOSURES,
    _V1Signal,
)
from private_quant.risk.market_regime import MarketRegime


_D1_INITIAL_CAPITAL = 100_000.0
_D1_COST_BPS = 5.0
_D1_START = date(2007, 10, 1)
_D1_END = date(2014, 12, 31)
_WHIPSAW_WINDOW = 5
_RETRY_WINDOW = 10
_CLUSTER_WINDOW = 10


class V14Boundary(str, Enum):
    ZERO_TO_THIRTY = "zero_to_thirty"
    THIRTY_TO_SEVENTY = "thirty_to_seventy"
    SEVENTY_TO_FULL = "seventy_to_full"


class V14Direction(str, Enum):
    UP = "up"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class V14Coverage:
    symbol: str
    first_date: date
    last_date: date
    rows: int


@dataclass(frozen=True, slots=True)
class V14ExposureChangeEvent:
    signal_index: int
    signal_date: date
    from_exposure: float
    to_exposure: float
    direction: V14Direction
    primary_boundary: V14Boundary
    crossed_boundaries: tuple[V14Boundary, ...]
    v1_regime: MarketRegime
    v1_score: int | float
    v1_cap: float


@dataclass(frozen=True, slots=True)
class V14PairReturnAttribution:
    spy_cumulative_return: float
    baseline_portfolio_return: float
    full_spy_comparator_return: float
    transaction_cost_drag: float


@dataclass(frozen=True, slots=True)
class V14WhipsawPair:
    opener: V14ExposureChangeEvent
    closer: V14ExposureChangeEvent
    latency_sessions: int
    primary_boundary: V14Boundary
    crossed_boundaries: tuple[V14Boundary, ...]
    failed_reentry: bool
    failed_derisk: bool
    opening_transaction_cost: float
    closing_transaction_cost: float
    pair_transaction_cost: float
    return_attribution: V14PairReturnAttribution | None


@dataclass(frozen=True, slots=True)
class V14RetryEvent:
    failed_pair_index: int
    retry_event: V14ExposureChangeEvent
    primary_boundary: V14Boundary
    retry_latency_sessions: int
    failed_again: bool


@dataclass(frozen=True, slots=True)
class V14ChurnCluster:
    start_date: date
    end_date: date
    start_opener_index: int
    end_closer_index: int
    pair_indices: tuple[int, ...]
    pair_count: int
    schedule_change_count: int
    boundaries: tuple[V14Boundary, ...]
    dominant_boundaries: tuple[V14Boundary, ...]
    failed_reentry_count: int
    failed_derisk_count: int
    absolute_exposure_turnover: float
    transaction_cost: float


@dataclass(frozen=True, slots=True)
class V14BoundaryCount:
    boundary: V14Boundary
    count: int
    share: float | None


@dataclass(frozen=True, slots=True)
class V14LatencyCount:
    latency_sessions: int
    count: int
    share: float | None


@dataclass(frozen=True, slots=True)
class V14DirectionCount:
    direction: V14Direction
    count: int
    share: float | None


@dataclass(frozen=True, slots=True)
class V14RetryBoundaryStats:
    boundary: V14Boundary
    retry_count: int
    retry_failure_count: int
    retry_failure_rate: float | None


@dataclass(frozen=True, slots=True)
class V14ReturnSummary:
    mean_spy_return: float | None
    median_spy_return: float | None
    mean_baseline_return: float | None
    median_baseline_return: float | None
    mean_full_spy_return: float | None
    median_full_spy_return: float | None
    mean_transaction_cost_drag: float | None
    median_transaction_cost_drag: float | None


@dataclass(frozen=True, slots=True)
class V14WhipsawAnatomyReport:
    analysis_start: date
    analysis_end: date
    spy_coverage: V14Coverage
    bil_coverage: V14Coverage
    common_interval_count: int
    initial_capital: float
    transaction_cost_bps: float
    schedule_change_count: int
    annualized_turnover: float | None
    total_transaction_cost: float
    whipsaw_pair_count: int
    whipsaw_rate: float | None
    pairs: tuple[V14WhipsawPair, ...]
    primary_boundary_breakdown: tuple[V14BoundaryCount, ...]
    crossed_boundary_incidence: tuple[V14BoundaryCount, ...]
    latency_breakdown: tuple[V14LatencyCount, ...]
    share_within_2_sessions: float | None
    share_within_3_sessions: float | None
    direction_breakdown: tuple[V14DirectionCount, ...]
    failed_reentry_count: int
    failed_reentry_share: float | None
    failed_derisk_count: int
    failed_derisk_share: float | None
    retries: tuple[V14RetryEvent, ...]
    retry_count: int
    retry_success_count: int
    retry_failure_count: int
    retry_failure_rate: float | None
    retry_by_boundary: tuple[V14RetryBoundaryStats, ...]
    clusters: tuple[V14ChurnCluster, ...]
    cluster_count: int
    clustered_whipsaw_count: int
    clustered_whipsaw_share: float | None
    multi_pair_cluster_count: int
    max_pair_count_in_cluster: int
    cluster_dominant_boundary_incidence: tuple[V14BoundaryCount, ...]
    cluster_absolute_exposure_turnover: float
    cluster_transaction_cost: float
    cluster_transaction_cost_share: float | None
    whipsaw_pair_transaction_cost: float
    whipsaw_pair_transaction_cost_share: float | None
    return_summary: V14ReturnSummary


def _validate_signal(signal, prior_date: date | None) -> None:
    if type(signal) is not _V1Signal or type(signal.signal_date) is not date:
        raise ValueError("V1.4 signals require plain dated V1 signal records")
    if prior_date is not None and signal.signal_date <= prior_date:
        raise ValueError("V1.4 signal dates must be strictly increasing")
    if (
        isinstance(signal.score, bool)
        or not isinstance(signal.score, Real)
        or not math.isfinite(signal.score)
    ):
        raise ValueError("V1.4 signal score must be finite")
    if type(signal.regime) is not MarketRegime:
        raise ValueError("V1.4 signal regime is invalid")
    if (
        isinstance(signal.maximum_long_exposure, bool)
        or not isinstance(signal.maximum_long_exposure, Real)
        or not math.isfinite(signal.maximum_long_exposure)
        or float(signal.maximum_long_exposure) not in ALLOWED_EXPOSURES
    ):
        raise ValueError("V1.4 signal exposure cap is invalid")


def _crossed_boundaries(start: float, end: float) -> tuple[V14Boundary, ...]:
    boundary_by_upper_index = {
        1: V14Boundary.ZERO_TO_THIRTY,
        2: V14Boundary.THIRTY_TO_SEVENTY,
        3: V14Boundary.SEVENTY_TO_FULL,
    }
    a, b = ALLOWED_EXPOSURES.index(start), ALLOWED_EXPOSURES.index(end)
    if b > a:
        return tuple(boundary_by_upper_index[i] for i in range(a + 1, b + 1))
    return tuple(boundary_by_upper_index[i] for i in range(a, b, -1))


def _extract_change_events(signals) -> tuple[V14ExposureChangeEvent, ...]:
    signals = tuple(signals)
    prior_date = None
    for signal in signals:
        _validate_signal(signal, prior_date)
        prior_date = signal.signal_date

    events = []
    for index in range(1, len(signals)):
        prior = signals[index - 1]
        signal = signals[index]
        from_exposure = float(prior.maximum_long_exposure)
        to_exposure = float(signal.maximum_long_exposure)
        if to_exposure == from_exposure:
            continue
        crossed_boundaries = _crossed_boundaries(from_exposure, to_exposure)
        events.append(
            V14ExposureChangeEvent(
                signal_index=index,
                signal_date=signal.signal_date,
                from_exposure=from_exposure,
                to_exposure=to_exposure,
                direction=(
                    V14Direction.UP
                    if to_exposure > from_exposure
                    else V14Direction.DOWN
                ),
                primary_boundary=crossed_boundaries[0],
                crossed_boundaries=crossed_boundaries,
                v1_regime=signal.regime,
                v1_score=signal.score,
                v1_cap=to_exposure,
            )
        )
    return tuple(events)


def _extract_v14_whipsaw_pairs(
    signals, events
) -> tuple[V14WhipsawPair, ...]:
    del signals
    events = tuple(events)
    pairs = []
    position = 0
    while position < len(events):
        opener = events[position]
        closer_position = None
        for candidate_position in range(position + 1, len(events)):
            closer = events[candidate_position]
            if closer.signal_index > opener.signal_index + _WHIPSAW_WINDOW:
                break
            closes = (
                closer.direction is V14Direction.UP
                and closer.to_exposure >= opener.from_exposure
                if opener.direction is V14Direction.DOWN
                else closer.direction is V14Direction.DOWN
                and closer.to_exposure <= opener.from_exposure
            )
            if closes:
                closer_position = candidate_position
                break
        if closer_position is None:
            position += 1
        else:
            pairs.append(
                V14WhipsawPair(
                    opener=opener,
                    closer=events[closer_position],
                    latency_sessions=(
                        events[closer_position].signal_index
                        - opener.signal_index
                    ),
                    primary_boundary=opener.primary_boundary,
                    crossed_boundaries=opener.crossed_boundaries,
                    failed_reentry=opener.direction is V14Direction.UP,
                    failed_derisk=opener.direction is V14Direction.DOWN,
                    opening_transaction_cost=0.0,
                    closing_transaction_cost=0.0,
                    pair_transaction_cost=0.0,
                    return_attribution=None,
                )
            )
            position = closer_position + 1
    return tuple(pairs)


__all__ = [
    "V14Boundary",
    "V14Direction",
    "V14Coverage",
    "V14ExposureChangeEvent",
    "V14PairReturnAttribution",
    "V14WhipsawPair",
    "V14RetryEvent",
    "V14ChurnCluster",
    "V14BoundaryCount",
    "V14LatencyCount",
    "V14DirectionCount",
    "V14RetryBoundaryStats",
    "V14ReturnSummary",
    "V14WhipsawAnatomyReport",
]
