"""Provider-independent contracts for Market Regime Stabilization V1.2."""

from dataclasses import dataclass, replace
from datetime import date
from enum import Enum
from statistics import fmean, median

from private_quant.backtest.regime_evaluation import (
    EvaluationAvailability,
    EvaluationPoint,
    EvaluationStrategy,
    HISTORICAL_REGIME_WINDOWS,
    InvalidEvaluationDataError,
    PerformanceMetrics,
    _align_evaluation_history,
    _performance_metrics,
    _simulate_intervals,
)
from private_quant.risk.market_regime import (
    MarketRegime,
    MarketRegimeEngine,
    _canonical_trading_date,
)


ALLOWED_EXPOSURES = (0.0, 0.3, 0.7, 1.0)
MARGINS = (0, 5, 10)
CONFIRMATION_SESSIONS = (1, 2, 3, 5)

DEVELOPMENT_START = date(2007, 10, 1)
DEVELOPMENT_END = date(2014, 12, 31)
VALIDATION_START = date(2015, 1, 1)
SELECTION_END = date(2020, 12, 31)
LOCKED_START = date(2021, 1, 1)

PRIMARY_COST_BPS = 5.0
SPLIT_CAGR_ALLOWANCE = 0.005
WINNER_CAGR_TIE_BAND = 0.0005
LOCKED_CAGR_IMPROVEMENT = 0.0025
TURNOVER_REDUCTION = 0.15
WHIPSAW_REDUCTION = 0.20
POST_SELECTION_COST_BPS = (0.0, 2.0, 5.0, 10.0)


@dataclass(frozen=True, slots=True)
class StabilizationCandidate:
    margin: int
    confirmation_sessions: int

    def __post_init__(self) -> None:
        if (
            type(self.margin) is not int
            or type(self.confirmation_sessions) is not int
            or self.margin not in MARGINS
            or self.confirmation_sessions not in CONFIRMATION_SESSIONS
        ):
            raise ValueError("candidate is outside the fixed V1.2 grid")


FIXED_STABILIZATION_CANDIDATES = tuple(
    StabilizationCandidate(margin, confirmations)
    for margin in MARGINS
    for confirmations in CONFIRMATION_SESSIONS
)


@dataclass(frozen=True, slots=True)
class BoundaryConfirmationState:
    to_30: int = 0
    to_70: int = 0
    to_100: int = 0

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (self.to_30, self.to_70, self.to_100)
        ):
            raise ValueError("confirmation counters must be non-negative integers")


class StabilizationTransition(str, Enum):
    HOLD = "hold"
    DE_RISK = "de_risk"
    RE_ENTRY = "re_entry"


@dataclass(frozen=True, slots=True)
class StabilizationSignalPoint:
    signal_date: date
    v1_score: int
    v1_regime: MarketRegime
    v1_maximum_long_exposure: float
    prior_overlay_exposure: float
    overlay_exposure: float
    confirmations: BoundaryConfirmationState
    transition: StabilizationTransition


@dataclass(frozen=True, slots=True)
class _V1Signal:
    signal_date: date
    score: int
    regime: MarketRegime
    maximum_long_exposure: float


def _build_v1_signals(spy_history, *, final_signal_date, engine=None):
    classifier = engine or MarketRegimeEngine()
    dated = tuple((_canonical_trading_date(bar), bar) for bar in spy_history)
    visible = tuple(bar for day, bar in dated if day <= final_signal_date)
    if len(visible) < 252:
        raise InvalidEvaluationDataError("SPY history has insufficient V1 warm-up")

    output = []
    for index in range(251, len(visible)):
        as_of = _canonical_trading_date(visible[index])
        result = classifier.evaluate(
            visible[: index + 1],
            as_of=as_of,
            qqq_bars=None,
        )
        if result.maximum_long_exposure not in ALLOWED_EXPOSURES:
            raise InvalidEvaluationDataError("V1 exposure mapping is invalid")
        output.append(
            _V1Signal(
                as_of,
                result.score,
                result.regime,
                result.maximum_long_exposure,
            )
        )
    return tuple(output)


def _measured_state_points(state_points, signal_dates):
    points_by_date = {point.signal_date: point for point in state_points}
    try:
        return tuple(points_by_date[signal_date] for signal_date in signal_dates)
    except KeyError:
        raise InvalidEvaluationDataError(
            "stabilization state is missing a measured signal date"
        ) from None


def _update_confirmations(
    score: int,
    candidate: StabilizationCandidate,
    prior: BoundaryConfirmationState,
) -> BoundaryConfirmationState:
    def update(threshold: int, value: int) -> int:
        if score >= threshold + candidate.margin:
            return min(candidate.confirmation_sessions, value + 1)
        return 0

    return BoundaryConfirmationState(
        to_30=update(-20, prior.to_30),
        to_70=update(15, prior.to_70),
        to_100=update(45, prior.to_100),
    )


def _next_overlay_exposure(
    v1_cap: float,
    prior_overlay: float,
    confirmations: BoundaryConfirmationState,
    candidate: StabilizationCandidate,
) -> tuple[float, StabilizationTransition]:
    if v1_cap < prior_overlay:
        return v1_cap, StabilizationTransition.DE_RISK

    if (
        prior_overlay == 0.0
        and v1_cap >= 0.3
        and confirmations.to_30 >= candidate.confirmation_sessions
    ):
        return 0.3, StabilizationTransition.RE_ENTRY
    if (
        prior_overlay == 0.3
        and v1_cap >= 0.7
        and confirmations.to_70 >= candidate.confirmation_sessions
    ):
        return 0.7, StabilizationTransition.RE_ENTRY
    if (
        prior_overlay == 0.7
        and v1_cap >= 1.0
        and confirmations.to_100 >= candidate.confirmation_sessions
    ):
        return 1.0, StabilizationTransition.RE_ENTRY
    return prior_overlay, StabilizationTransition.HOLD


def _run_stabilization_state_machine(
    signals: tuple[_V1Signal, ...], candidate: StabilizationCandidate
) -> tuple[StabilizationSignalPoint, ...]:
    prior_overlay = 0.0
    prior_confirmations = BoundaryConfirmationState()
    points = []

    for signal in signals:
        confirmations = _update_confirmations(
            signal.score, candidate, prior_confirmations
        )
        overlay, transition = _next_overlay_exposure(
            signal.maximum_long_exposure,
            prior_overlay,
            confirmations,
            candidate,
        )
        points.append(
            StabilizationSignalPoint(
                signal_date=signal.signal_date,
                v1_score=signal.score,
                v1_regime=signal.regime,
                v1_maximum_long_exposure=signal.maximum_long_exposure,
                prior_overlay_exposure=prior_overlay,
                overlay_exposure=overlay,
                confirmations=confirmations,
                transition=transition,
            )
        )
        prior_overlay = overlay
        prior_confirmations = confirmations

    return tuple(points)


def _simulate_bil_cash_schedule(
    aligned, exposures, *, cost_bps=5.0, initial_capital=100_000.0
):
    return _simulate_intervals(
        aligned.intervals,
        exposures,
        strategy=EvaluationStrategy.REGIME_BIL_CASH_PROXY,
        initial_capital=initial_capital,
        transaction_cost_bps=cost_bps,
    )


def _slice_period_points(points, *, start, end):
    return tuple(
        point
        for point in points
        if point.signal_date >= start and point.return_end_date <= end
    )


def _rebased_period_metrics(points):
    scale = 100.0 / points[0].starting_value
    rebased_points = tuple(
        replace(
            point,
            starting_value=point.starting_value * scale,
            ending_value=point.ending_value * scale,
            transaction_cost=point.transaction_cost * scale,
        )
        for point in points
    )
    return _performance_metrics(
        100.0,
        rebased_points,
        applicable_exposures=ALLOWED_EXPOSURES,
    )


@dataclass(frozen=True, slots=True)
class StabilizationDiagnostics:
    schedule_exposure_changes: int
    whipsaw_pairs: int
    whipsaw_rate: float | None
    delayed_below_cap_sessions: int
    reentry_lags: tuple[int, ...]
    mean_reentry_lag: float | None
    median_reentry_lag: float | None
    recovery_durations: tuple[int, ...]
    mean_recovery_duration: float | None
    median_recovery_duration: float | None
    incomplete_recovery_episodes: int


def _stabilization_diagnostics(
    state_points, *, start, end, include_reentry_detail
):
    points = tuple(
        point for point in state_points if start <= point.signal_date <= end
    )
    context_points = tuple(
        point for point in state_points if point.signal_date <= end
    )
    targets = tuple(point.overlay_exposure for point in points)
    change_indices = tuple(
        index
        for index in range(1, len(targets))
        if targets[index] != targets[index - 1]
    )

    whipsaw_pairs = 0
    change_position = 0
    while change_position < len(change_indices):
        opener = change_indices[change_position]
        before_opener = targets[opener - 1]
        downward = targets[opener] < before_opener
        closer_position = None
        for candidate_position in range(change_position + 1, len(change_indices)):
            closer = change_indices[candidate_position]
            if closer > opener + 5:
                break
            if downward:
                closes_pair = (
                    targets[closer] > targets[closer - 1]
                    and targets[closer] >= before_opener
                )
            else:
                closes_pair = (
                    targets[closer] < targets[closer - 1]
                    and targets[closer] <= before_opener
                )
            if closes_pair:
                closer_position = candidate_position
                break
        if closer_position is None:
            change_position += 1
        else:
            whipsaw_pairs += 1
            change_position = closer_position + 1

    delayed_below_cap_sessions = sum(
        point.overlay_exposure < point.v1_maximum_long_exposure for point in points
    )
    reentry_lags = []
    recovery_durations = []
    incomplete_recovery_episodes = 0

    if include_reentry_detail:
        boundary_counters = (
            (0.3, "to_30"),
            (0.7, "to_70"),
            (1.0, "to_100"),
        )
        qualifying_starts = {boundary: None for boundary, _ in boundary_counters}
        context_targets = tuple(
            point.overlay_exposure for point in context_points
        )
        for index, point in enumerate(context_points):
            for boundary, counter_name in boundary_counters:
                counter = getattr(point.confirmations, counter_name)
                crossed = (
                    index > 0
                    and context_targets[index - 1]
                    < boundary
                    <= context_targets[index]
                )
                if counter == 0:
                    qualifying_starts[boundary] = None
                elif qualifying_starts[boundary] is None and (
                    point.overlay_exposure < boundary or crossed
                ):
                    qualifying_starts[boundary] = index

                qualifying_start = qualifying_starts[boundary]
                if crossed and qualifying_start is not None:
                    if point.signal_date >= start:
                        reentry_lags.append(index - qualifying_start + 1)
                    qualifying_starts[boundary] = None

        recovery_start = None
        for index in range(1, len(context_targets)):
            if (
                recovery_start is None
                and context_targets[index - 1] == 1.0 > context_targets[index]
            ):
                recovery_start = index
            elif recovery_start is not None and context_targets[index] == 1.0:
                if context_points[index].signal_date >= start:
                    recovery_durations.append(index - recovery_start)
                recovery_start = None
        incomplete_recovery_episodes = int(
            recovery_start is not None and bool(points)
        )

    reentry_lags = tuple(reentry_lags)
    recovery_durations = tuple(recovery_durations)
    schedule_exposure_changes = len(change_indices)
    return StabilizationDiagnostics(
        schedule_exposure_changes=schedule_exposure_changes,
        whipsaw_pairs=whipsaw_pairs,
        whipsaw_rate=(
            whipsaw_pairs / schedule_exposure_changes
            if schedule_exposure_changes
            else None
        ),
        delayed_below_cap_sessions=delayed_below_cap_sessions,
        reentry_lags=reentry_lags,
        mean_reentry_lag=fmean(reentry_lags) if reentry_lags else None,
        median_reentry_lag=float(median(reentry_lags)) if reentry_lags else None,
        recovery_durations=recovery_durations,
        mean_recovery_duration=(
            fmean(recovery_durations) if recovery_durations else None
        ),
        median_recovery_duration=(
            float(median(recovery_durations)) if recovery_durations else None
        ),
        incomplete_recovery_episodes=incomplete_recovery_episodes,
    )


class ResearchPeriod(str, Enum):
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    COMBINED_SELECTION = "combined_selection"
    LOCKED = "locked"


class GateStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_EVALUABLE = "not_evaluable"


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    status: GateStatus
    actual: float | int | None
    required: float | int | None


@dataclass(frozen=True, slots=True)
class CandidatePeriodResult:
    candidate: StabilizationCandidate | None
    period: ResearchPeriod
    metrics: PerformanceMetrics
    diagnostics: StabilizationDiagnostics
    points: tuple[EvaluationPoint, ...]


@dataclass(frozen=True, slots=True)
class CandidateQualification:
    candidate: StabilizationCandidate
    periods: tuple[CandidatePeriodResult, ...]
    gates: tuple[GateResult, ...]
    qualified: bool


class SelectionStatus(str, Enum):
    SELECTED = "selected"
    NO_QUALIFIED_CANDIDATE = "no_qualified_candidate"


@dataclass(frozen=True, slots=True)
class CandidateSelectionResult:
    common_intervals: tuple[tuple[date, date], ...]
    baseline_periods: tuple[CandidatePeriodResult, ...]
    candidates: tuple[CandidateQualification, ...]
    ranking_order: tuple[StabilizationCandidate, ...]
    status: SelectionStatus
    winner: StabilizationCandidate | None


class PromotionStatus(str, Enum):
    PROMOTE_V1_2_RESEARCH = "promote_v1_2_research"
    NO_V1_2_PROMOTION = "no_v1_2_promotion"


@dataclass(frozen=True, slots=True)
class LockedEvaluationResult:
    frozen_candidate: StabilizationCandidate
    common_intervals: tuple[tuple[date, date], ...]
    baseline: CandidatePeriodResult
    candidate: CandidatePeriodResult
    gates: tuple[GateResult, ...]
    status: PromotionStatus


@dataclass(frozen=True, slots=True)
class PostSelectionPathResult:
    metrics: PerformanceMetrics
    diagnostics: StabilizationDiagnostics
    points: tuple[EvaluationPoint, ...]


@dataclass(frozen=True, slots=True)
class PostSelectionCostComparison:
    transaction_cost_bps: float
    baseline: PostSelectionPathResult
    candidate: PostSelectionPathResult


@dataclass(frozen=True, slots=True)
class PostSelectionWindowComparison:
    window_name: str
    requested_start: date
    requested_end: date
    transaction_cost_bps: float
    availability: EvaluationAvailability
    baseline: PostSelectionPathResult | None
    candidate: PostSelectionPathResult | None


@dataclass(frozen=True, slots=True)
class StabilizationPostSelectionResult:
    frozen_candidate: StabilizationCandidate
    common_intervals: tuple[tuple[date, date], ...]
    full_period_comparisons: tuple[PostSelectionCostComparison, ...]
    window_comparisons: tuple[PostSelectionWindowComparison, ...]


def _period_result(periods, period):
    matches = tuple(item for item in periods if item.period is period)
    if len(matches) != 1:
        raise ValueError("candidate results must contain each selection period once")
    return matches[0]


def _comparison_gate(name, actual, required, predicate):
    if actual is None or required is None:
        status = GateStatus.NOT_EVALUABLE
    else:
        status = GateStatus.PASS if predicate(actual, required) else GateStatus.FAIL
    return GateResult(name, status, actual, required)


def _locked_promotion_decision(baseline, candidate):
    baseline_cagr = baseline.metrics.cagr
    cagr_floor = (
        baseline_cagr + LOCKED_CAGR_IMPROVEMENT
        if baseline_cagr is not None
        else None
    )
    baseline_turnover = baseline.metrics.annualized_turnover
    turnover_limit = (
        baseline_turnover * (1.0 - TURNOVER_REDUCTION)
        if baseline_turnover is not None and baseline_turnover > 0.0
        else None
    )
    baseline_whipsaws = baseline.diagnostics.whipsaw_pairs
    whipsaw_limit = (
        baseline_whipsaws * (1.0 - WHIPSAW_REDUCTION)
        if baseline_whipsaws > 0
        else None
    )

    gates = (
        _comparison_gate(
            "locked_max_drawdown",
            candidate.metrics.max_drawdown,
            -0.20,
            lambda actual, required: actual >= required,
        ),
        _comparison_gate(
            "locked_cagr_improvement",
            candidate.metrics.cagr,
            cagr_floor,
            lambda actual, required: actual >= required,
        ),
        _comparison_gate(
            "locked_turnover_reduction",
            candidate.metrics.annualized_turnover,
            turnover_limit,
            lambda actual, required: actual <= required,
        ),
        _comparison_gate(
            "locked_whipsaw_reduction",
            candidate.diagnostics.whipsaw_pairs,
            whipsaw_limit,
            lambda actual, required: actual <= required,
        ),
    )
    status = (
        PromotionStatus.PROMOTE_V1_2_RESEARCH
        if all(gate.status is GateStatus.PASS for gate in gates)
        else PromotionStatus.NO_V1_2_PROMOTION
    )
    return gates, status


def _qualify_candidate(candidate, baseline_periods, candidate_periods):
    baseline_development = _period_result(
        baseline_periods, ResearchPeriod.DEVELOPMENT
    )
    baseline_validation = _period_result(baseline_periods, ResearchPeriod.VALIDATION)
    baseline_combined = _period_result(
        baseline_periods, ResearchPeriod.COMBINED_SELECTION
    )
    candidate_development = _period_result(
        candidate_periods, ResearchPeriod.DEVELOPMENT
    )
    candidate_validation = _period_result(
        candidate_periods, ResearchPeriod.VALIDATION
    )
    candidate_combined = _period_result(
        candidate_periods, ResearchPeriod.COMBINED_SELECTION
    )

    development_floor = (
        baseline_development.metrics.cagr - SPLIT_CAGR_ALLOWANCE
        if baseline_development.metrics.cagr is not None
        else None
    )
    validation_floor = (
        baseline_validation.metrics.cagr - SPLIT_CAGR_ALLOWANCE
        if baseline_validation.metrics.cagr is not None
        else None
    )
    baseline_turnover = baseline_combined.metrics.annualized_turnover
    turnover_limit = (
        baseline_turnover * (1.0 - TURNOVER_REDUCTION)
        if baseline_turnover is not None and baseline_turnover > 0.0
        else None
    )
    baseline_whipsaws = baseline_combined.diagnostics.whipsaw_pairs
    whipsaw_limit = (
        baseline_whipsaws * (1.0 - WHIPSAW_REDUCTION)
        if baseline_whipsaws > 0
        else None
    )

    gates = (
        _comparison_gate(
            "development_max_drawdown",
            candidate_development.metrics.max_drawdown,
            -0.20,
            lambda actual, required: actual >= required,
        ),
        _comparison_gate(
            "validation_max_drawdown",
            candidate_validation.metrics.max_drawdown,
            -0.20,
            lambda actual, required: actual >= required,
        ),
        _comparison_gate(
            "combined_cagr_above_baseline",
            candidate_combined.metrics.cagr,
            baseline_combined.metrics.cagr,
            lambda actual, required: actual > required,
        ),
        _comparison_gate(
            "development_cagr_floor",
            candidate_development.metrics.cagr,
            development_floor,
            lambda actual, required: actual >= required,
        ),
        _comparison_gate(
            "validation_cagr_floor",
            candidate_validation.metrics.cagr,
            validation_floor,
            lambda actual, required: actual >= required,
        ),
        _comparison_gate(
            "combined_turnover_reduction",
            candidate_combined.metrics.annualized_turnover,
            turnover_limit,
            lambda actual, required: actual <= required,
        ),
        _comparison_gate(
            "combined_whipsaw_reduction",
            candidate_combined.diagnostics.whipsaw_pairs,
            whipsaw_limit,
            lambda actual, required: actual <= required,
        ),
    )
    return CandidateQualification(
        candidate=candidate,
        periods=tuple(candidate_periods),
        gates=gates,
        qualified=all(gate.status is GateStatus.PASS for gate in gates),
    )


def _ranking_values(qualification):
    combined = _period_result(
        qualification.periods, ResearchPeriod.COMBINED_SELECTION
    )
    return (
        combined.metrics.cagr,
        combined.diagnostics.whipsaw_pairs,
        abs(combined.metrics.max_drawdown),
        qualification.candidate.confirmation_sessions,
        qualification.candidate.margin,
    )


def _rank_qualified_candidates(qualifications):
    eligible = tuple(item for item in qualifications if item.qualified)
    if not eligible:
        return ()
    top_cagr = max(_ranking_values(item)[0] for item in eligible)
    tied = tuple(
        item
        for item in eligible
        if _ranking_values(item)[0] >= top_cagr - WINNER_CAGR_TIE_BAND
    )
    outside = tuple(item for item in eligible if item not in tied)
    tied = tuple(sorted(tied, key=lambda item: _ranking_values(item)[1:]))
    outside = tuple(
        sorted(
            outside,
            key=lambda item: (
                -_ranking_values(item)[0],
                *_ranking_values(item)[1:],
            ),
        )
    )
    return tied + outside


def _baseline_state_points(signals):
    points = []
    prior_exposure = 0.0
    for signal in signals:
        exposure = signal.maximum_long_exposure
        if exposure < prior_exposure:
            transition = StabilizationTransition.DE_RISK
        elif exposure > prior_exposure:
            transition = StabilizationTransition.RE_ENTRY
        else:
            transition = StabilizationTransition.HOLD
        points.append(
            StabilizationSignalPoint(
                signal_date=signal.signal_date,
                v1_score=signal.score,
                v1_regime=signal.regime,
                v1_maximum_long_exposure=exposure,
                prior_overlay_exposure=prior_exposure,
                overlay_exposure=exposure,
                confirmations=BoundaryConfirmationState(),
                transition=transition,
            )
        )
        prior_exposure = exposure
    return tuple(points)


def _selection_period_results(candidate, full_points, state_points):
    boundaries = (
        (ResearchPeriod.DEVELOPMENT, DEVELOPMENT_START, DEVELOPMENT_END),
        (ResearchPeriod.VALIDATION, VALIDATION_START, SELECTION_END),
        (ResearchPeriod.COMBINED_SELECTION, DEVELOPMENT_START, SELECTION_END),
    )
    results = []
    for period, start, end in boundaries:
        period_points = _slice_period_points(full_points, start=start, end=end)
        if not period_points:
            raise InvalidEvaluationDataError(
                f"selection history has no complete {period.value} intervals"
            )
        results.append(
            CandidatePeriodResult(
                candidate=candidate,
                period=period,
                metrics=_rebased_period_metrics(period_points),
                diagnostics=_stabilization_diagnostics(
                    state_points,
                    start=start,
                    end=end,
                    include_reentry_detail=False,
                ),
                points=period_points,
            )
        )
    return tuple(results)


def select_regime_stabilization_candidate(
    spy_bars,
    bil_bars,
    *,
    engine=None,
    initial_capital=100_000.0,
):
    """Select at most one fixed-grid V1.2 candidate using data through 2020."""
    aligned = _align_evaluation_history(
        spy_bars,
        bil_bars,
        evaluation_start=DEVELOPMENT_START,
        evaluation_end=SELECTION_END,
    )
    if (
        aligned.intervals[0].signal_date != DEVELOPMENT_START
        or aligned.intervals[-1].return_end_date != SELECTION_END
    ):
        raise InvalidEvaluationDataError(
            "selection history does not cover the fixed boundaries"
        )

    measured_dates = tuple(interval.signal_date for interval in aligned.intervals)
    v1_signals = _build_v1_signals(
        aligned.spy_history,
        final_signal_date=measured_dates[-1],
        engine=engine,
    )
    common_intervals = tuple(
        (interval.signal_date, interval.return_end_date)
        for interval in aligned.intervals
    )

    baseline_state = _baseline_state_points(v1_signals)
    measured_baseline = _measured_state_points(baseline_state, measured_dates)
    baseline_points = _simulate_bil_cash_schedule(
        aligned,
        tuple(point.overlay_exposure for point in measured_baseline),
        cost_bps=PRIMARY_COST_BPS,
        initial_capital=initial_capital,
    )
    baseline_periods = _selection_period_results(
        None, baseline_points, baseline_state
    )

    qualifications = []
    for candidate in FIXED_STABILIZATION_CANDIDATES:
        candidate_state = _run_stabilization_state_machine(v1_signals, candidate)
        measured_candidate = _measured_state_points(candidate_state, measured_dates)
        candidate_points = _simulate_bil_cash_schedule(
            aligned,
            tuple(point.overlay_exposure for point in measured_candidate),
            cost_bps=PRIMARY_COST_BPS,
            initial_capital=initial_capital,
        )
        periods = _selection_period_results(
            candidate, candidate_points, candidate_state
        )
        qualifications.append(
            _qualify_candidate(candidate, baseline_periods, periods)
        )

    qualifications = tuple(qualifications)
    ranked = _rank_qualified_candidates(qualifications)
    winner = ranked[0].candidate if ranked else None
    return CandidateSelectionResult(
        common_intervals=common_intervals,
        baseline_periods=baseline_periods,
        candidates=qualifications,
        ranking_order=tuple(item.candidate for item in ranked),
        status=(
            SelectionStatus.SELECTED
            if winner is not None
            else SelectionStatus.NO_QUALIFIED_CANDIDATE
        ),
        winner=winner,
    )


def _prelocked_target(state_points, first_measured_date):
    prior_points = tuple(
        point
        for point in state_points
        if point.signal_date < first_measured_date
    )
    if not prior_points:
        return 0.0
    return prior_points[-1].overlay_exposure


def _is_frozen_candidate(candidate):
    return (
        type(candidate) is StabilizationCandidate
        and type(candidate.margin) is int
        and type(candidate.confirmation_sessions) is int
        and candidate.margin in MARGINS
        and candidate.confirmation_sessions in CONFIRMATION_SESSIONS
    )


def _simulate_locked_bil_cash_schedule(
    aligned,
    exposures,
    *,
    prior_exposure,
    cost_bps=5.0,
    initial_capital=100_000.0,
):
    points = _simulate_bil_cash_schedule(
        aligned,
        exposures,
        cost_bps=cost_bps,
        initial_capital=initial_capital,
    )
    first = points[0]
    exposure_change = abs(first.target_spy_exposure - prior_exposure)
    transaction_cost = (
        first.starting_value * exposure_change * cost_bps / 10_000.0
    )
    gross_return = (
        first.target_spy_exposure * first.spy_return
        + (1.0 - first.target_spy_exposure) * first.residual_cash_return
    )
    ending_value = (first.starting_value - transaction_cost) * (
        1.0 + gross_return
    )
    scale = ending_value / first.ending_value
    adjusted = [
        replace(
            first,
            ending_value=ending_value,
            net_return=ending_value / first.starting_value - 1.0,
            exposure_change=exposure_change,
            transaction_cost=transaction_cost,
        )
    ]
    adjusted.extend(
        replace(
            point,
            starting_value=point.starting_value * scale,
            ending_value=point.ending_value * scale,
            transaction_cost=point.transaction_cost * scale,
        )
        for point in points[1:]
    )
    return tuple(adjusted)


def _locked_period_result(candidate, points, state_points, *, initial_capital):
    return CandidatePeriodResult(
        candidate=candidate,
        period=ResearchPeriod.LOCKED,
        metrics=_performance_metrics(
            initial_capital,
            points,
            applicable_exposures=ALLOWED_EXPOSURES,
        ),
        diagnostics=_stabilization_diagnostics(
            state_points,
            start=LOCKED_START,
            end=points[-1].return_end_date,
            include_reentry_detail=True,
        ),
        points=points,
    )


def evaluate_locked_regime_stabilization(
    spy_bars,
    bil_bars,
    *,
    frozen_candidate,
    engine=None,
    initial_capital=100_000.0,
):
    """Evaluate one already-frozen V1.2 candidate on the locked period."""
    if not _is_frozen_candidate(frozen_candidate):
        raise ValueError("locked evaluation requires a frozen fixed-grid candidate")

    aligned = _align_evaluation_history(
        spy_bars,
        bil_bars,
        evaluation_start=LOCKED_START,
        evaluation_end=None,
    )
    measured_dates = tuple(interval.signal_date for interval in aligned.intervals)
    v1_signals = _build_v1_signals(
        aligned.spy_history,
        final_signal_date=measured_dates[-1],
        engine=engine,
    )
    first_locked_signal = next(
        (
            signal.signal_date
            for signal in v1_signals
            if signal.signal_date >= LOCKED_START
        ),
        None,
    )
    if measured_dates[0] != first_locked_signal:
        raise InvalidEvaluationDataError(
            "locked evaluation history does not cover the fixed start boundary"
        )
    common_intervals = tuple(
        (interval.signal_date, interval.return_end_date)
        for interval in aligned.intervals
    )

    baseline_state = _baseline_state_points(v1_signals)
    measured_baseline = _measured_state_points(baseline_state, measured_dates)
    baseline_points = _simulate_locked_bil_cash_schedule(
        aligned,
        tuple(point.overlay_exposure for point in measured_baseline),
        prior_exposure=_prelocked_target(baseline_state, measured_dates[0]),
        cost_bps=PRIMARY_COST_BPS,
        initial_capital=initial_capital,
    )
    baseline = _locked_period_result(
        None,
        baseline_points,
        baseline_state,
        initial_capital=initial_capital,
    )

    candidate_state = _run_stabilization_state_machine(
        v1_signals,
        frozen_candidate,
    )
    measured_candidate = _measured_state_points(candidate_state, measured_dates)
    candidate_points = _simulate_locked_bil_cash_schedule(
        aligned,
        tuple(point.overlay_exposure for point in measured_candidate),
        prior_exposure=_prelocked_target(candidate_state, measured_dates[0]),
        cost_bps=PRIMARY_COST_BPS,
        initial_capital=initial_capital,
    )
    candidate = _locked_period_result(
        frozen_candidate,
        candidate_points,
        candidate_state,
        initial_capital=initial_capital,
    )
    gates, status = _locked_promotion_decision(baseline, candidate)
    return LockedEvaluationResult(
        frozen_candidate=frozen_candidate,
        common_intervals=common_intervals,
        baseline=baseline,
        candidate=candidate,
        gates=gates,
        status=status,
    )


def build_stabilization_post_selection_diagnostics(
    spy_bars,
    bil_bars,
    *,
    frozen_candidate,
    engine=None,
    initial_capital=100_000.0,
):
    """Describe one frozen candidate over the fixed full path and windows."""
    if not _is_frozen_candidate(frozen_candidate):
        raise ValueError(
            "post-selection diagnostics require a frozen fixed-grid candidate"
        )

    aligned = _align_evaluation_history(
        spy_bars,
        bil_bars,
        evaluation_start=DEVELOPMENT_START,
        evaluation_end=None,
    )
    if aligned.intervals[0].signal_date != DEVELOPMENT_START:
        raise InvalidEvaluationDataError(
            "post-selection history does not cover the fixed start boundary"
        )

    measured_dates = tuple(interval.signal_date for interval in aligned.intervals)
    v1_signals = _build_v1_signals(
        aligned.spy_history,
        final_signal_date=measured_dates[-1],
        engine=engine,
    )
    baseline_state = _baseline_state_points(v1_signals)
    candidate_state = _run_stabilization_state_machine(
        v1_signals,
        frozen_candidate,
    )
    measured_baseline = _measured_state_points(baseline_state, measured_dates)
    measured_candidate = _measured_state_points(candidate_state, measured_dates)
    baseline_exposures = tuple(
        point.overlay_exposure for point in measured_baseline
    )
    candidate_exposures = tuple(
        point.overlay_exposure for point in measured_candidate
    )
    common_intervals = tuple(
        (interval.signal_date, interval.return_end_date)
        for interval in aligned.intervals
    )
    full_end = aligned.intervals[-1].return_end_date

    full_period_comparisons = []
    window_comparisons = []
    for transaction_cost_bps in POST_SELECTION_COST_BPS:
        baseline_points = _simulate_bil_cash_schedule(
            aligned,
            baseline_exposures,
            cost_bps=transaction_cost_bps,
            initial_capital=initial_capital,
        )
        candidate_points = _simulate_bil_cash_schedule(
            aligned,
            candidate_exposures,
            cost_bps=transaction_cost_bps,
            initial_capital=initial_capital,
        )
        full_period_comparisons.append(
            PostSelectionCostComparison(
                transaction_cost_bps=transaction_cost_bps,
                baseline=PostSelectionPathResult(
                    metrics=_performance_metrics(
                        initial_capital,
                        baseline_points,
                        applicable_exposures=ALLOWED_EXPOSURES,
                    ),
                    diagnostics=_stabilization_diagnostics(
                        baseline_state,
                        start=DEVELOPMENT_START,
                        end=full_end,
                        include_reentry_detail=True,
                    ),
                    points=baseline_points,
                ),
                candidate=PostSelectionPathResult(
                    metrics=_performance_metrics(
                        initial_capital,
                        candidate_points,
                        applicable_exposures=ALLOWED_EXPOSURES,
                    ),
                    diagnostics=_stabilization_diagnostics(
                        candidate_state,
                        start=DEVELOPMENT_START,
                        end=full_end,
                        include_reentry_detail=True,
                    ),
                    points=candidate_points,
                ),
            )
        )

        for window_name, (
            requested_start,
            requested_end,
        ) in HISTORICAL_REGIME_WINDOWS.items():
            baseline_window_points = _slice_period_points(
                baseline_points,
                start=requested_start,
                end=requested_end,
            )
            candidate_window_points = _slice_period_points(
                candidate_points,
                start=requested_start,
                end=requested_end,
            )
            if not baseline_window_points:
                window_comparisons.append(
                    PostSelectionWindowComparison(
                        window_name=window_name,
                        requested_start=requested_start,
                        requested_end=requested_end,
                        transaction_cost_bps=transaction_cost_bps,
                        availability=EvaluationAvailability.UNAVAILABLE,
                        baseline=None,
                        candidate=None,
                    )
                )
                continue
            effective_signal_start = baseline_window_points[0].signal_date
            effective_signal_end = baseline_window_points[-1].signal_date
            window_comparisons.append(
                PostSelectionWindowComparison(
                    window_name=window_name,
                    requested_start=requested_start,
                    requested_end=requested_end,
                    transaction_cost_bps=transaction_cost_bps,
                    availability=EvaluationAvailability.AVAILABLE,
                    baseline=PostSelectionPathResult(
                        metrics=_rebased_period_metrics(baseline_window_points),
                        diagnostics=_stabilization_diagnostics(
                            baseline_state,
                            start=effective_signal_start,
                            end=effective_signal_end,
                            include_reentry_detail=True,
                        ),
                        points=baseline_window_points,
                    ),
                    candidate=PostSelectionPathResult(
                        metrics=_rebased_period_metrics(candidate_window_points),
                        diagnostics=_stabilization_diagnostics(
                            candidate_state,
                            start=effective_signal_start,
                            end=effective_signal_end,
                            include_reentry_detail=True,
                        ),
                        points=candidate_window_points,
                    ),
                )
            )

    return StabilizationPostSelectionResult(
        frozen_candidate=frozen_candidate,
        common_intervals=common_intervals,
        full_period_comparisons=tuple(full_period_comparisons),
        window_comparisons=tuple(window_comparisons),
    )
