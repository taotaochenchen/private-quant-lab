"""Provider-independent V1.3 recovery-episode re-entry state contracts."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
import math
from numbers import Real
from statistics import fmean, median

from private_quant.backtest.regime_stabilization import (
    ALLOWED_EXPOSURES,
    DEVELOPMENT_START, DEVELOPMENT_END, VALIDATION_START, SELECTION_END,
    LOCKED_START, PRIMARY_COST_BPS, POST_SELECTION_COST_BPS, WINNER_CAGR_TIE_BAND,
    LOCKED_CAGR_IMPROVEMENT,
    GateResult, GateStatus, ResearchPeriod, StabilizationDiagnostics,
    _build_v1_signals, _baseline_state_points, _measured_state_points,
    _simulate_bil_cash_schedule, _simulate_locked_bil_cash_schedule,
    _prelocked_target, _slice_period_points, _rebased_period_metrics,
    _qualify_candidate, _locked_promotion_decision,
    _V1Signal,
    _stabilization_diagnostics,
)
from private_quant.backtest.regime_evaluation import (
    EvaluationAvailability, EvaluationPoint, PerformanceMetrics,
    HISTORICAL_REGIME_WINDOWS, InvalidEvaluationDataError,
    _align_evaluation_history, _performance_metrics,
)
from private_quant.risk.market_regime import MarketRegime


__all__ = [
    "V13ReentryStructure",
    "V13ReentryCandidate",
    "V13RecoveryDiagnostics",
    "V13SelectionStatus",
    "V13CandidateSelectionResult",
    "V13PromotionStatus",
    "V13LockedEvaluationResult",
    "V13PostSelectionResult",
    "select_regime_reentry_v1_3_candidate",
    "evaluate_locked_regime_reentry_v1_3",
    "build_regime_reentry_v1_3_post_selection_diagnostics",
]


class V13ReentryStructure(str, Enum):
    DEEP_RECOVERY = "deep_recovery"
    DEFENSIVE_RECOVERY = "defensive_recovery"
    BROAD_BULL_CATCH_UP = "broad_bull_catch_up"


@dataclass(frozen=True, slots=True)
class V13ReentryCandidate:
    structure: V13ReentryStructure

    def __post_init__(self) -> None:
        if type(self.structure) is not V13ReentryStructure:
            raise ValueError("candidate must use a V1.3 re-entry structure")


FIXED_V13_CANDIDATES = tuple(
    V13ReentryCandidate(structure) for structure in V13ReentryStructure
)


class V13ReentryTransition(str, Enum):
    HOLD = "hold"
    DE_RISK = "de_risk"
    NORMAL_RE_ENTRY = "normal_re_entry"
    FAST_RE_ENTRY = "fast_re_entry"


@dataclass(frozen=True, slots=True)
class _RecoveryEpisodeState:
    active: bool = False
    origin_exposure: float | None = None
    minimum_v1_cap: float | None = None

    def __post_init__(self) -> None:
        inactive = (self.origin_exposure is None and self.minimum_v1_cap is None)
        if type(self.active) is not bool or (self.active != (not inactive)):
            raise ValueError("recovery episode state is inconsistent")
        if self.active and (
            self.origin_exposure not in ALLOWED_EXPOSURES
            or self.minimum_v1_cap not in ALLOWED_EXPOSURES
        ):
            raise ValueError("recovery episode state has invalid exposures")


@dataclass(frozen=True, slots=True)
class V13ReentrySignalPoint:
    signal_date: date
    v1_score: int | float
    v1_regime: MarketRegime
    v1_maximum_long_exposure: float
    prior_overlay_exposure: float
    overlay_exposure: float
    prior_episode: _RecoveryEpisodeState
    episode: _RecoveryEpisodeState
    transition: V13ReentryTransition


@dataclass(frozen=True, slots=True)
class V13RecoveryEpisode:
    opening_signal_date: date
    origin_exposure: float
    minimum_v1_cap: float
    closing_signal_date: date | None
    recovery_duration: int | None


@dataclass(frozen=True, slots=True)
class V13RecoveryDiagnostics:
    schedule_exposure_changes: int
    whipsaw_pairs: int
    whipsaw_rate: float | None
    total_recovery_episodes: int
    completed_recovery_episodes: int
    incomplete_recovery_episodes: int
    fast_path_activation_count: int
    fast_path_activation_rate: float | None
    ordinary_one_level_reentry_count: int
    fast_two_level_reentry_count: int
    delayed_below_cap_sessions: int
    reentry_lags: tuple[int, ...]
    recovery_durations: tuple[int, ...]
    mean_reentry_lag: float | None
    median_reentry_lag: float | None
    mean_recovery_duration: float | None
    median_recovery_duration: float | None
    episodes: tuple[V13RecoveryEpisode, ...]


def _validate_candidate(candidate) -> V13ReentryCandidate:
    if (
        type(candidate) is not V13ReentryCandidate
        or type(getattr(candidate, "structure", None)) is not V13ReentryStructure
    ):
        raise ValueError("candidate must be one of the fixed V1.3 candidates")
    return candidate


def _validate_signal(signal, prior_date) -> None:
    if type(signal) is not _V1Signal or type(signal.signal_date) is not date:
        raise ValueError("V1.3 signals require plain dated V1 signal records")
    if prior_date is not None and signal.signal_date <= prior_date:
        raise ValueError("V1.3 signal dates must be strictly increasing")
    if (
        isinstance(signal.score, bool)
        or not isinstance(signal.score, Real)
        or not math.isfinite(signal.score)
    ):
        raise ValueError("V1.3 signal score must be finite")
    if type(signal.regime) is not MarketRegime:
        raise ValueError("V1.3 signal regime is invalid")
    if (
        isinstance(signal.maximum_long_exposure, bool)
        or not isinstance(signal.maximum_long_exposure, Real)
        or not math.isfinite(signal.maximum_long_exposure)
        or float(signal.maximum_long_exposure) not in ALLOWED_EXPOSURES
    ):
        raise ValueError("V1.3 signal exposure cap is invalid")


def _fast_eligible(signal, episode, candidate) -> bool:
    if not (
        episode.active
        and signal.regime is MarketRegime.BULL
        and signal.score >= 45
        and signal.maximum_long_exposure == 1.0
    ):
        return False
    if candidate.structure is V13ReentryStructure.DEEP_RECOVERY:
        return episode.minimum_v1_cap == 0.0
    if candidate.structure is V13ReentryStructure.DEFENSIVE_RECOVERY:
        return episode.minimum_v1_cap <= 0.3
    return candidate.structure is V13ReentryStructure.BROAD_BULL_CATCH_UP


def _run_reentry_state_machine(signals, candidate) -> tuple[V13ReentrySignalPoint, ...]:
    candidate = _validate_candidate(candidate)
    prior_overlay = 0.0
    prior_episode = _RecoveryEpisodeState()
    prior_date = None
    points = []

    for signal in signals:
        _validate_signal(signal, prior_date)
        cap = float(signal.maximum_long_exposure)
        episode = prior_episode
        if episode.active:
            episode = _RecoveryEpisodeState(
                True, episode.origin_exposure, min(episode.minimum_v1_cap, cap)
            )

        if cap < prior_overlay:
            overlay = cap
            transition = V13ReentryTransition.DE_RISK
            if not episode.active:
                episode = _RecoveryEpisodeState(True, prior_overlay, cap)
        elif cap > prior_overlay:
            step = 2 if _fast_eligible(signal, episode, candidate) else 1
            levels = ALLOWED_EXPOSURES
            overlay = levels[
                min(levels.index(prior_overlay) + step, levels.index(cap))
            ]
            transition = (
                V13ReentryTransition.FAST_RE_ENTRY
                if step == 2
                else V13ReentryTransition.NORMAL_RE_ENTRY
            )
        else:
            overlay = prior_overlay
            transition = V13ReentryTransition.HOLD

        if episode.active and overlay >= episode.origin_exposure:
            episode = _RecoveryEpisodeState()
        points.append(
            V13ReentrySignalPoint(
                signal.signal_date, signal.score, signal.regime, cap,
                prior_overlay, overlay, prior_episode, episode, transition,
            )
        )
        prior_overlay, prior_episode, prior_date = overlay, episode, signal.signal_date
    return tuple(points)


def _recovery_diagnostics(state_points, *, start, end) -> V13RecoveryDiagnostics:
    if type(start) is not date or type(end) is not date or end < start:
        raise ValueError("diagnostic dates must be ordered plain dates")
    points = tuple(point for point in state_points if start <= point.signal_date <= end)
    context = tuple(point for point in state_points if point.signal_date <= end)
    comparable = _stabilization_diagnostics(
        context, start=start, end=end, include_reentry_detail=False
    )
    episodes = []
    opening_index = None
    opening_point = None
    for index, point in enumerate(context):
        opens = (
            point.transition is V13ReentryTransition.DE_RISK
            and not point.prior_episode.active
            and point.episode.active
        )
        if opens:
            opening_index, opening_point = index, point
        closes = (
            opening_point is not None
            and point.prior_episode.active
            and not point.episode.active
        )
        if closes:
            if opening_point.signal_date <= end and point.signal_date >= start:
                episodes.append(V13RecoveryEpisode(
                    opening_point.signal_date, opening_point.episode.origin_exposure,
                    point.prior_episode.minimum_v1_cap, point.signal_date,
                    index - opening_index,
                ))
            opening_index = opening_point = None
    if opening_point is not None and opening_point.signal_date <= end:
        episodes.append(V13RecoveryEpisode(
            opening_point.signal_date, opening_point.episode.origin_exposure,
            context[-1].episode.minimum_v1_cap, None, None,
        ))

    lags = []
    for boundary in (0.3, 0.7, 1.0):
        qualifying_start = None
        for index, point in enumerate(context):
            if point.v1_maximum_long_exposure < boundary:
                qualifying_start = None
                continue
            if point.prior_overlay_exposure >= boundary:
                qualifying_start = None
                continue
            if qualifying_start is None:
                qualifying_start = index
            if point.overlay_exposure >= boundary:
                if point.signal_date >= start:
                    lags.append(index - qualifying_start + 1)
                qualifying_start = None

    fast_points = tuple(
        point for point in points
        if point.transition is V13ReentryTransition.FAST_RE_ENTRY
    )
    completed = tuple(episode for episode in episodes if episode.closing_signal_date is not None)
    durations = tuple(episode.recovery_duration for episode in completed)
    two_level = sum(
        point.overlay_exposure - point.prior_overlay_exposure >= 0.7
        for point in fast_points
    )
    ordinary = sum(
        point.transition is V13ReentryTransition.NORMAL_RE_ENTRY for point in points
    )
    lags, durations = tuple(lags), tuple(durations)
    return V13RecoveryDiagnostics(
        comparable.schedule_exposure_changes, comparable.whipsaw_pairs,
        comparable.whipsaw_rate, len(episodes), len(completed),
        len(episodes) - len(completed), len(fast_points),
        len(fast_points) / len(episodes) if episodes else None, ordinary, two_level,
        sum(point.overlay_exposure < point.v1_maximum_long_exposure for point in points),
        lags, durations, fmean(lags) if lags else None,
        float(median(lags)) if lags else None,
        fmean(durations) if durations else None,
        float(median(durations)) if durations else None, tuple(episodes),
    )


class V13SelectionStatus(str, Enum):
    V1_3_CANDIDATE_SELECTED = "v1_3_candidate_selected"
    NO_QUALIFIED_V1_3_CANDIDATE = "no_qualified_v1_3_candidate"


class V13PromotionStatus(str, Enum):
    PROMOTE_V1_3_RESEARCH = "promote_v1_3_research"
    NO_V1_3_PROMOTION = "no_v1_3_promotion"


@dataclass(frozen=True, slots=True)
class V13CandidatePeriodResult:
    candidate: V13ReentryCandidate | None
    period: ResearchPeriod
    metrics: PerformanceMetrics
    diagnostics: V13RecoveryDiagnostics | StabilizationDiagnostics
    points: tuple[EvaluationPoint, ...]


@dataclass(frozen=True, slots=True)
class V13CandidateQualification:
    candidate: V13ReentryCandidate
    periods: tuple[V13CandidatePeriodResult, ...]
    gates: tuple[GateResult, ...]
    qualified: bool


@dataclass(frozen=True, slots=True)
class V13CandidateSelectionResult:
    common_intervals: tuple[tuple[date, date], ...]
    baseline_periods: tuple[V13CandidatePeriodResult, ...]
    candidates: tuple[V13CandidateQualification, ...]
    ranking_order: tuple[V13ReentryCandidate, ...]
    status: V13SelectionStatus
    winner: V13ReentryCandidate | None


@dataclass(frozen=True, slots=True)
class V13LockedEvaluationResult:
    frozen_candidate: V13ReentryCandidate
    common_intervals: tuple[tuple[date, date], ...]
    baseline: V13CandidatePeriodResult
    candidate: V13CandidatePeriodResult
    gates: tuple[GateResult, ...]
    status: V13PromotionStatus


@dataclass(frozen=True, slots=True)
class V13PostSelectionPathResult:
    metrics: PerformanceMetrics
    diagnostics: V13RecoveryDiagnostics | StabilizationDiagnostics
    points: tuple[EvaluationPoint, ...]


@dataclass(frozen=True, slots=True)
class V13PostSelectionCostComparison:
    transaction_cost_bps: float
    baseline: V13PostSelectionPathResult
    candidate: V13PostSelectionPathResult


@dataclass(frozen=True, slots=True)
class V13PostSelectionWindowComparison:
    window_name: str
    requested_start: date
    requested_end: date
    transaction_cost_bps: float
    availability: EvaluationAvailability
    baseline: V13PostSelectionPathResult | None
    candidate: V13PostSelectionPathResult | None


@dataclass(frozen=True, slots=True)
class V13PostSelectionResult:
    frozen_candidate: V13ReentryCandidate
    common_intervals: tuple[tuple[date, date], ...]
    full_period_comparisons: tuple[V13PostSelectionCostComparison, ...]
    window_comparisons: tuple[V13PostSelectionWindowComparison, ...]


def _qualify_v13(candidate, baseline_periods, candidate_periods):
    result = _qualify_candidate(candidate, baseline_periods, candidate_periods)
    return V13CandidateQualification(candidate, tuple(candidate_periods), result.gates, result.qualified)


def _promotion_v13(baseline, candidate):
    gates, _ = _locked_promotion_decision(baseline, candidate)
    # Preserve the frozen 25-bp boundary without binary addition rounding it up.
    if baseline.metrics.cagr is not None and candidate.metrics.cagr is not None:
        required = Decimal(str(baseline.metrics.cagr)) + Decimal(str(LOCKED_CAGR_IMPROVEMENT))
        cagr_gate = gates[1]
        gates = (gates[0], GateResult(cagr_gate.name,
                 GateStatus.PASS if Decimal(str(candidate.metrics.cagr)) >= required else GateStatus.FAIL,
                 cagr_gate.actual, float(required)), *gates[2:])
    status = (V13PromotionStatus.PROMOTE_V1_3_RESEARCH
              if all(gate.status is GateStatus.PASS for gate in gates)
              else V13PromotionStatus.NO_V1_3_PROMOTION)
    return gates, status


def _rank_v13(qualifications):
    def values(item):
        combined = next(p for p in item.periods if p.period is ResearchPeriod.COMBINED_SELECTION)
        return (combined.metrics.cagr, combined.diagnostics.whipsaw_pairs,
                -combined.metrics.max_drawdown, combined.metrics.annualized_turnover,
                FIXED_V13_CANDIDATES.index(item.candidate))
    eligible = tuple(item for item in qualifications if item.qualified)
    if not eligible:
        return ()
    floor = max(values(item)[0] for item in eligible) - WINNER_CAGR_TIE_BAND
    tied = tuple(item for item in eligible if values(item)[0] >= floor)
    outside = tuple(item for item in eligible if values(item)[0] < floor)
    return (tuple(sorted(tied, key=lambda item: values(item)[1:]))
            + tuple(sorted(outside, key=lambda item: (-values(item)[0], *values(item)[1:]))))


def _path_result(candidate, points, state, *, initial_capital=None):
    metrics = (_rebased_period_metrics(points) if initial_capital is None else
               _performance_metrics(initial_capital, points, applicable_exposures=ALLOWED_EXPOSURES))
    bounds = dict(start=points[0].signal_date, end=points[-1].signal_date)
    diagnostics = (_recovery_diagnostics(state, **bounds) if candidate is not None else
                   _stabilization_diagnostics(state, **bounds, include_reentry_detail=False))
    return V13PostSelectionPathResult(metrics, diagnostics, tuple(points))


def _selection_periods(candidate, full_points, state):
    results = []
    for period, start, end in (
        (ResearchPeriod.DEVELOPMENT, DEVELOPMENT_START, DEVELOPMENT_END),
        (ResearchPeriod.VALIDATION, VALIDATION_START, SELECTION_END),
        (ResearchPeriod.COMBINED_SELECTION, DEVELOPMENT_START, SELECTION_END),
    ):
        points = _slice_period_points(full_points, start=start, end=end)
        if not points:
            raise InvalidEvaluationDataError(f"selection history has no complete {period.value} intervals")
        path = _path_result(candidate, points, state)
        results.append(V13CandidatePeriodResult(candidate, period, path.metrics, path.diagnostics, path.points))
    return tuple(results)


def _interval_dates(aligned):
    return tuple((point.signal_date, point.return_end_date) for point in aligned.intervals)


def _simulate_state(aligned, state, *, cost_bps, initial_capital, locked=False):
    dates = tuple(point.signal_date for point in aligned.intervals)
    exposures = tuple(point.overlay_exposure for point in _measured_state_points(state, dates))
    if locked:
        return _simulate_locked_bil_cash_schedule(aligned, exposures,
            prior_exposure=_prelocked_target(state, dates[0]),
            cost_bps=cost_bps, initial_capital=initial_capital)
    return _simulate_bil_cash_schedule(aligned, exposures,
                                      cost_bps=cost_bps, initial_capital=initial_capital)


def select_regime_reentry_v1_3_candidate(spy_bars, bil_bars, *, engine=None, initial_capital=100_000.0):
    """Select at most one fixed structure using only observations through 2020."""
    aligned = _align_evaluation_history(spy_bars, bil_bars,
        evaluation_start=DEVELOPMENT_START, evaluation_end=SELECTION_END)
    if (aligned.intervals[0].signal_date != DEVELOPMENT_START
            or aligned.intervals[-1].return_end_date != SELECTION_END):
        raise InvalidEvaluationDataError("selection history does not cover the fixed boundaries")
    signals = _build_v1_signals(aligned.spy_history,
        final_signal_date=aligned.intervals[-1].signal_date, engine=engine)
    baseline_state = _baseline_state_points(signals)
    baseline_points = _simulate_state(aligned, baseline_state,
        cost_bps=PRIMARY_COST_BPS, initial_capital=initial_capital)
    baseline_periods = _selection_periods(None, baseline_points, baseline_state)
    qualifications = []
    for candidate in FIXED_V13_CANDIDATES:
        state = _run_reentry_state_machine(signals, candidate)
        points = _simulate_state(aligned, state, cost_bps=PRIMARY_COST_BPS, initial_capital=initial_capital)
        qualifications.append(_qualify_v13(candidate, baseline_periods, _selection_periods(candidate, points, state)))
    ranked = _rank_v13(qualifications)
    winner = ranked[0].candidate if ranked else None
    return V13CandidateSelectionResult(_interval_dates(aligned), baseline_periods,
        tuple(qualifications), tuple(item.candidate for item in ranked),
        V13SelectionStatus.V1_3_CANDIDATE_SELECTED if winner else V13SelectionStatus.NO_QUALIFIED_V1_3_CANDIDATE,
        winner)


def evaluate_locked_regime_reentry_v1_3(spy_bars, bil_bars, *, frozen_candidate,
                                       engine=None, initial_capital=100_000.0):
    """Evaluate one externally frozen structure without reselection."""
    frozen_candidate = _validate_candidate(frozen_candidate)
    aligned = _align_evaluation_history(spy_bars, bil_bars,
        evaluation_start=LOCKED_START, evaluation_end=None)
    signals = _build_v1_signals(aligned.spy_history,
        final_signal_date=aligned.intervals[-1].signal_date, engine=engine)
    first_locked = next((signal.signal_date for signal in signals if signal.signal_date >= LOCKED_START), None)
    if aligned.intervals[0].signal_date != first_locked:
        raise InvalidEvaluationDataError("locked evaluation history does not cover the fixed start boundary")
    results = []
    for candidate, state in ((None, _baseline_state_points(signals)),
                             (frozen_candidate, _run_reentry_state_machine(signals, frozen_candidate))):
        points = _simulate_state(aligned, state, cost_bps=PRIMARY_COST_BPS,
                                 initial_capital=initial_capital, locked=True)
        path = _path_result(candidate, points, state, initial_capital=initial_capital)
        results.append(V13CandidatePeriodResult(candidate, ResearchPeriod.LOCKED,
                                                path.metrics, path.diagnostics, path.points))
    baseline, candidate = results
    gates, status = _promotion_v13(baseline, candidate)
    return V13LockedEvaluationResult(frozen_candidate, _interval_dates(aligned), baseline, candidate, gates, status)


def build_regime_reentry_v1_3_post_selection_diagnostics(spy_bars, bil_bars, *, frozen_candidate,
                                                        engine=None, initial_capital=100_000.0):
    """Describe one fixed structure; never select, qualify, rank, or promote."""
    frozen_candidate = _validate_candidate(frozen_candidate)
    aligned = _align_evaluation_history(spy_bars, bil_bars,
        evaluation_start=DEVELOPMENT_START, evaluation_end=None)
    if aligned.intervals[0].signal_date != DEVELOPMENT_START:
        raise InvalidEvaluationDataError("post-selection history does not cover the fixed start boundary")
    signals = _build_v1_signals(aligned.spy_history,
        final_signal_date=aligned.intervals[-1].signal_date, engine=engine)
    states = (_baseline_state_points(signals), _run_reentry_state_machine(signals, frozen_candidate))
    candidates = (None, frozen_candidate)
    full, windows = [], []
    for cost in POST_SELECTION_COST_BPS:
        paths = tuple(_simulate_state(aligned, state, cost_bps=cost, initial_capital=initial_capital) for state in states)
        full.append(V13PostSelectionCostComparison(cost, *(
            _path_result(candidate, points, state, initial_capital=initial_capital)
            for candidate, points, state in zip(candidates, paths, states))))
        for name, (start, end) in HISTORICAL_REGIME_WINDOWS.items():
            slices = tuple(_slice_period_points(points, start=start, end=end) for points in paths)
            available = bool(slices[0])
            results = tuple(_path_result(candidate, points, state)
                for candidate, points, state in zip(candidates, slices, states)) if available else (None, None)
            windows.append(V13PostSelectionWindowComparison(name, start, end, cost,
                EvaluationAvailability.AVAILABLE if available else EvaluationAvailability.UNAVAILABLE, *results))
    return V13PostSelectionResult(frozen_candidate, _interval_dates(aligned), tuple(full), tuple(windows))
