"""Provider-independent contracts for Market Regime V1.4 diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from enum import Enum
import math
from numbers import Real
from math import prod
from statistics import fmean, median

from private_quant.backtest.regime_evaluation import (
    EvaluationStrategy,
    InvalidEvaluationDataError,
    _align_evaluation_history,
    _date_bars,
    _performance_metrics,
    _simulate_intervals,
)
from private_quant.backtest.regime_stabilization import (
    ALLOWED_EXPOSURES,
    _V1Signal,
    _build_v1_signals,
)
from private_quant.risk.market_regime import MarketRegime, _canonical_trading_date


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


def _extract_v14_retries(
    events, pairs
) -> tuple[V14RetryEvent, ...]:
    events = tuple(events)
    pairs = tuple(pairs)
    retries = []
    for pair_index, pair in enumerate(pairs):
        if not pair.failed_reentry:
            continue
        retry_limit = pair.closer.signal_index + _RETRY_WINDOW
        for event in events:
            if event.signal_index <= pair.closer.signal_index:
                continue
            if event.signal_index > retry_limit:
                break
            if (
                event.direction is not V14Direction.UP
                or event.primary_boundary is not pair.primary_boundary
            ):
                continue
            failed_again = any(
                later_index > pair_index
                and later_pair.failed_reentry
                and later_pair.opener is event
                and later_pair.opener.signal_index == event.signal_index
                for later_index, later_pair in enumerate(pairs)
            )
            retries.append(
                V14RetryEvent(
                    failed_pair_index=pair_index,
                    retry_event=event,
                    primary_boundary=pair.primary_boundary,
                    retry_latency_sessions=(
                        event.signal_index - pair.closer.signal_index
                    ),
                    failed_again=failed_again,
                )
            )
            break
    return tuple(retries)


def _build_v14_clusters(
    events, pairs
) -> tuple[V14ChurnCluster, ...]:
    events = tuple(events)
    pairs = tuple(pairs)
    if not pairs:
        return ()

    def build_cluster(pair_indices):
        first_pair = pairs[pair_indices[0]]
        last_pair = pairs[pair_indices[-1]]
        start_index = first_pair.opener.signal_index
        end_index = last_pair.closer.signal_index
        cluster_events = tuple(
            event
            for event in events
            if start_index <= event.signal_index <= end_index
        )
        boundary_counts = {
            boundary: sum(
                boundary in pairs[pair_index].crossed_boundaries
                for pair_index in pair_indices
            )
            for boundary in V14Boundary
        }
        boundaries = tuple(
            boundary for boundary in V14Boundary if boundary_counts[boundary]
        )
        maximum_count = max(boundary_counts.values(), default=0)
        dominant_boundaries = tuple(
            boundary
            for boundary in V14Boundary
            if boundary_counts[boundary] == maximum_count and maximum_count
        )
        return V14ChurnCluster(
            start_date=first_pair.opener.signal_date,
            end_date=last_pair.closer.signal_date,
            start_opener_index=start_index,
            end_closer_index=last_pair.closer.signal_index,
            pair_indices=tuple(pair_indices),
            pair_count=len(pair_indices),
            schedule_change_count=len(cluster_events),
            boundaries=boundaries,
            dominant_boundaries=dominant_boundaries,
            failed_reentry_count=sum(
                pairs[pair_index].failed_reentry for pair_index in pair_indices
            ),
            failed_derisk_count=sum(
                pairs[pair_index].failed_derisk for pair_index in pair_indices
            ),
            absolute_exposure_turnover=sum(
                abs(event.to_exposure - event.from_exposure)
                for event in cluster_events
            ),
            transaction_cost=0.0,
        )

    clusters = []
    current_indices = [0]
    for pair_index in range(1, len(pairs)):
        previous_pair = pairs[pair_index - 1]
        current_pair = pairs[pair_index]
        joins = (
            current_pair.opener.signal_index
            - previous_pair.opener.signal_index
            <= _CLUSTER_WINDOW
            and bool(
                set(current_pair.crossed_boundaries)
                & set(previous_pair.crossed_boundaries)
            )
        )
        if joins:
            current_indices.append(pair_index)
        else:
            clusters.append(build_cluster(current_indices))
            current_indices = [pair_index]
    clusters.append(build_cluster(current_indices))
    return tuple(clusters)


def _share(numerator: int | float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _pair_return_attribution(pair, points, point_indices):
    try:
        opener_index = point_indices[pair.opener.signal_date]
        closer_index = point_indices[pair.closer.signal_date]
    except KeyError:
        raise InvalidEvaluationDataError(
            "V1.4 pair is missing an evaluation point"
        ) from None
    if closer_index < opener_index:
        raise InvalidEvaluationDataError("V1.4 pair points are out of order")
    window = points[opener_index : closer_index + 1]
    spy_return = prod(1.0 + point.spy_return for point in window) - 1.0
    return V14PairReturnAttribution(
        spy_cumulative_return=spy_return,
        baseline_portfolio_return=(
            window[-1].ending_value / window[0].starting_value - 1.0
        ),
        full_spy_comparator_return=spy_return,
        transaction_cost_drag=(
            sum(point.transaction_cost for point in window)
            / window[0].starting_value
        ),
    )


def _return_summary(pairs) -> V14ReturnSummary:
    attributions = tuple(
        pair.return_attribution for pair in pairs if pair.return_attribution is not None
    )
    if not attributions:
        return V14ReturnSummary(None, None, None, None, None, None, None, None)

    spy_returns = tuple(item.spy_cumulative_return for item in attributions)
    baseline_returns = tuple(
        item.baseline_portfolio_return for item in attributions
    )
    full_spy_returns = tuple(
        item.full_spy_comparator_return for item in attributions
    )
    cost_drags = tuple(item.transaction_cost_drag for item in attributions)
    return V14ReturnSummary(
        mean_spy_return=fmean(spy_returns),
        median_spy_return=float(median(spy_returns)),
        mean_baseline_return=fmean(baseline_returns),
        median_baseline_return=float(median(baseline_returns)),
        mean_full_spy_return=fmean(full_spy_returns),
        median_full_spy_return=float(median(full_spy_returns)),
        mean_transaction_cost_drag=fmean(cost_drags),
        median_transaction_cost_drag=float(median(cost_drags)),
    )


def _coverage(symbol: str, dates) -> V14Coverage:
    dates = tuple(dates)
    if not dates:
        raise InvalidEvaluationDataError(f"{symbol} history has no active coverage")
    return V14Coverage(symbol, dates[0], dates[-1], len(dates))


def _attach_pair_accounting(pairs, points, point_indices):
    return tuple(
        replace(
            pair,
            opening_transaction_cost=points[
                point_indices[pair.opener.signal_date]
            ].transaction_cost,
            closing_transaction_cost=points[
                point_indices[pair.closer.signal_date]
            ].transaction_cost,
            pair_transaction_cost=(
                points[point_indices[pair.opener.signal_date]].transaction_cost
                + points[point_indices[pair.closer.signal_date]].transaction_cost
            ),
            return_attribution=_pair_return_attribution(
                pair, points, point_indices
            ),
        )
        for pair in pairs
    )


def _attach_cluster_accounting(clusters, events, points_by_date):
    attached = []
    for cluster in clusters:
        try:
            transaction_cost = sum(
                points_by_date[event.signal_date].transaction_cost
                for event in events
                if (
                    cluster.start_opener_index
                    <= event.signal_index
                    <= cluster.end_closer_index
                )
            )
        except KeyError:
            raise InvalidEvaluationDataError(
                "V1.4 cluster is missing an evaluation point"
            ) from None
        attached.append(replace(cluster, transaction_cost=transaction_cost))
    return tuple(attached)


def analyze_regime_churn_v1_4(
    spy_bars, bil_bars, *, engine=None
) -> V14WhipsawAnatomyReport:
    """Assemble the fixed, provider-independent V1.4 D1 anatomy report."""
    spy_bars = tuple(spy_bars)
    bil_bars = tuple(bil_bars)
    aligned = _align_evaluation_history(
        spy_bars,
        bil_bars,
        evaluation_start=_D1_START,
        evaluation_end=_D1_END,
    )
    if not aligned.intervals:
        raise InvalidEvaluationDataError("V1.4 D1 has no complete intervals")
    if aligned.intervals[0].signal_date != _D1_START:
        raise InvalidEvaluationDataError("V1.4 D1 start boundary is missing")
    if aligned.intervals[-1].return_end_date != _D1_END:
        raise InvalidEvaluationDataError("V1.4 D1 end boundary is missing")

    v1_signals = _build_v1_signals(
        aligned.spy_history,
        final_signal_date=_D1_END,
        engine=engine,
    )
    signals_by_date = {signal.signal_date: signal for signal in v1_signals}
    measured_dates = tuple(interval.signal_date for interval in aligned.intervals)
    try:
        signals = tuple(signals_by_date[signal_date] for signal_date in measured_dates)
    except KeyError:
        raise InvalidEvaluationDataError(
            "V1.4 signal is missing a measured interval date"
        ) from None
    exposures = tuple(signal.maximum_long_exposure for signal in signals)

    points = _simulate_intervals(
        aligned.intervals,
        exposures,
        strategy=EvaluationStrategy.REGIME_BIL_CASH_PROXY,
        initial_capital=_D1_INITIAL_CAPITAL,
        transaction_cost_bps=_D1_COST_BPS,
    )
    metrics = _performance_metrics(
        _D1_INITIAL_CAPITAL,
        points,
        applicable_exposures=ALLOWED_EXPOSURES,
    )

    events = _extract_change_events(signals)
    structural_pairs = _extract_v14_whipsaw_pairs(signals, events)
    retries = _extract_v14_retries(events, structural_pairs)
    structural_clusters = _build_v14_clusters(events, structural_pairs)
    point_indices = {point.signal_date: index for index, point in enumerate(points)}
    point_by_date = {point.signal_date: point for point in points}
    pairs = _attach_pair_accounting(structural_pairs, points, point_indices)
    clusters = _attach_cluster_accounting(
        structural_clusters, events, point_by_date
    )

    pair_count = len(pairs)
    primary_boundary_breakdown = tuple(
        V14BoundaryCount(
            boundary,
            sum(pair.primary_boundary is boundary for pair in pairs),
            _share(
                sum(pair.primary_boundary is boundary for pair in pairs),
                pair_count,
            ),
        )
        for boundary in V14Boundary
    )
    crossed_boundary_incidence = tuple(
        V14BoundaryCount(
            boundary,
            sum(boundary in pair.crossed_boundaries for pair in pairs),
            _share(
                sum(boundary in pair.crossed_boundaries for pair in pairs),
                pair_count,
            ),
        )
        for boundary in V14Boundary
    )
    latency_breakdown = tuple(
        V14LatencyCount(
            latency,
            sum(pair.latency_sessions == latency for pair in pairs),
            _share(
                sum(pair.latency_sessions == latency for pair in pairs),
                pair_count,
            ),
        )
        for latency in range(1, _WHIPSAW_WINDOW + 1)
    )
    direction_breakdown = tuple(
        V14DirectionCount(
            direction,
            sum(pair.opener.direction is direction for pair in pairs),
            _share(
                sum(pair.opener.direction is direction for pair in pairs),
                pair_count,
            ),
        )
        for direction in V14Direction
    )
    failed_reentry_count = sum(pair.failed_reentry for pair in pairs)
    failed_derisk_count = sum(pair.failed_derisk for pair in pairs)
    retry_count = len(retries)
    retry_failure_count = sum(retry.failed_again for retry in retries)
    retry_by_boundary = tuple(
        V14RetryBoundaryStats(
            boundary,
            sum(retry.primary_boundary is boundary for retry in retries),
            sum(
                retry.primary_boundary is boundary and retry.failed_again
                for retry in retries
            ),
            _share(
                sum(
                    retry.primary_boundary is boundary and retry.failed_again
                    for retry in retries
                ),
                sum(retry.primary_boundary is boundary for retry in retries),
            ),
        )
        for boundary in V14Boundary
    )

    cluster_count = len(clusters)
    clustered_whipsaw_count = sum(
        cluster.pair_count for cluster in clusters if cluster.pair_count > 1
    )
    cluster_dominant_boundary_incidence = tuple(
        V14BoundaryCount(
            boundary,
            sum(boundary in cluster.dominant_boundaries for cluster in clusters),
            _share(
                sum(boundary in cluster.dominant_boundaries for cluster in clusters),
                cluster_count,
            ),
        )
        for boundary in V14Boundary
    )
    cluster_transaction_cost = sum(
        (cluster.transaction_cost for cluster in clusters), 0.0
    )
    whipsaw_pair_transaction_cost = sum(
        (pair.pair_transaction_cost for pair in pairs), 0.0
    )
    spy_dates = tuple(
        _canonical_trading_date(bar) for bar in aligned.spy_history
    )
    bil_dates = tuple(
        trading_date
        for trading_date, _ in _date_bars(bil_bars, series_name="BIL")
        if _D1_START <= trading_date <= _D1_END
    )

    return V14WhipsawAnatomyReport(
        analysis_start=_D1_START,
        analysis_end=_D1_END,
        spy_coverage=_coverage("SPY", spy_dates),
        bil_coverage=_coverage("BIL", bil_dates),
        common_interval_count=len(aligned.intervals),
        initial_capital=_D1_INITIAL_CAPITAL,
        transaction_cost_bps=_D1_COST_BPS,
        schedule_change_count=len(events),
        annualized_turnover=metrics.annualized_turnover,
        total_transaction_cost=metrics.total_transaction_cost,
        whipsaw_pair_count=pair_count,
        whipsaw_rate=_share(pair_count, len(events)),
        pairs=pairs,
        primary_boundary_breakdown=primary_boundary_breakdown,
        crossed_boundary_incidence=crossed_boundary_incidence,
        latency_breakdown=latency_breakdown,
        share_within_2_sessions=_share(
            sum(pair.latency_sessions <= 2 for pair in pairs), pair_count
        ),
        share_within_3_sessions=_share(
            sum(pair.latency_sessions <= 3 for pair in pairs), pair_count
        ),
        direction_breakdown=direction_breakdown,
        failed_reentry_count=failed_reentry_count,
        failed_reentry_share=_share(failed_reentry_count, pair_count),
        failed_derisk_count=failed_derisk_count,
        failed_derisk_share=_share(failed_derisk_count, pair_count),
        retries=retries,
        retry_count=retry_count,
        retry_success_count=retry_count - retry_failure_count,
        retry_failure_count=retry_failure_count,
        retry_failure_rate=_share(retry_failure_count, retry_count),
        retry_by_boundary=retry_by_boundary,
        clusters=clusters,
        cluster_count=cluster_count,
        clustered_whipsaw_count=clustered_whipsaw_count,
        clustered_whipsaw_share=_share(clustered_whipsaw_count, pair_count),
        multi_pair_cluster_count=sum(
            cluster.pair_count > 1 for cluster in clusters
        ),
        max_pair_count_in_cluster=max(
            (cluster.pair_count for cluster in clusters), default=0
        ),
        cluster_dominant_boundary_incidence=cluster_dominant_boundary_incidence,
        cluster_absolute_exposure_turnover=sum(
            (cluster.absolute_exposure_turnover for cluster in clusters), 0.0
        ),
        cluster_transaction_cost=cluster_transaction_cost,
        cluster_transaction_cost_share=_share(
            cluster_transaction_cost, metrics.total_transaction_cost
        ),
        whipsaw_pair_transaction_cost=whipsaw_pair_transaction_cost,
        whipsaw_pair_transaction_cost_share=_share(
            whipsaw_pair_transaction_cost, metrics.total_transaction_cost
        ),
        return_summary=_return_summary(pairs),
    )


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
    "analyze_regime_churn_v1_4",
]
