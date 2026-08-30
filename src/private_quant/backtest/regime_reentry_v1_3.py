"""Provider-independent V1.3 recovery-episode re-entry state contracts."""

from dataclasses import dataclass
from datetime import date
from enum import Enum
import math
from numbers import Real
from statistics import fmean, median

from private_quant.backtest.regime_stabilization import (
    ALLOWED_EXPOSURES,
    _V1Signal,
    _stabilization_diagnostics,
)
from private_quant.risk.market_regime import MarketRegime


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
        or type(candidate.structure) is not V13ReentryStructure
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
