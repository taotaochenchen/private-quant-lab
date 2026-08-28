"""Provider-independent contracts for Market Regime Stabilization V1.2."""

from dataclasses import dataclass
from datetime import date
from enum import Enum

from private_quant.risk.market_regime import MarketRegime


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
            self.margin not in MARGINS
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


class SelectionStatus(str, Enum):
    SELECTED = "selected"
    NO_QUALIFIED_CANDIDATE = "no_qualified_candidate"


class PromotionStatus(str, Enum):
    PROMOTE_V1_2_RESEARCH = "promote_v1_2_research"
    NO_V1_2_PROMOTION = "no_v1_2_promotion"
