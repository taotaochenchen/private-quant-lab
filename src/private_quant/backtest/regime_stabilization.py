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
