"""Immutable contracts and input validation for market-regime evaluation."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import math
from typing import Sequence

from private_quant.data import PriceBar


class MarketRegime(StrEnum):
    BULL = "BULL"
    CAUTIOUS_BULL = "CAUTIOUS_BULL"
    RISK_OFF = "RISK_OFF"
    BEAR = "BEAR"


class RegimeConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class StrategyPermission(StrEnum):
    NORMAL = "NORMAL"
    REDUCED = "REDUCED"
    DEFENSIVE = "DEFENSIVE"
    BLOCKED = "BLOCKED"


class ConfirmationStatus(StrEnum):
    CONFIRMS_POSITIVE = "CONFIRMS_POSITIVE"
    CONFIRMS_NEGATIVE = "CONFIRMS_NEGATIVE"
    MIXED = "MIXED"
    UNAVAILABLE = "UNAVAILABLE"


class RegimeEngineError(Exception):
    """Base class for fixed-message regime-engine failures."""

    default_message = "Market regime evaluation failed."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(self.default_message)


class InsufficientRegimeHistoryError(RegimeEngineError):
    default_message = "Insufficient SPY history for regime evaluation."


class InvalidRegimeDataError(RegimeEngineError):
    default_message = "Invalid market regime data."


class StaleRegimeDataError(RegimeEngineError):
    default_message = "SPY history is stale for regime evaluation."


def _nonempty_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _finite_number(value: object, field_name: str) -> None:
    try:
        finite = math.isfinite(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        finite = False
    if not finite:
        raise ValueError(f"{field_name} must be finite")


@dataclass(frozen=True, slots=True)
class RegimeMetric:
    name: str
    value: float
    unit: str
    reference: str

    def __post_init__(self) -> None:
        _nonempty_text(self.name, "name")
        _nonempty_text(self.unit, "unit")
        _nonempty_text(self.reference, "reference")
        _finite_number(self.value, "value")


@dataclass(frozen=True, slots=True)
class RegimeComponent:
    name: str
    score: int
    max_abs_score: int
    metrics: tuple[RegimeMetric, ...]
    explanation: str

    def __post_init__(self) -> None:
        _nonempty_text(self.name, "name")
        _nonempty_text(self.explanation, "explanation")
        if type(self.max_abs_score) is not int or self.max_abs_score <= 0:
            raise ValueError("max_abs_score must be a positive integer")
        if type(self.score) is not int or abs(self.score) > self.max_abs_score:
            raise ValueError("score must be within max_abs_score")
        if not isinstance(self.metrics, tuple) or not all(
            isinstance(metric, RegimeMetric) for metric in self.metrics
        ):
            raise ValueError("metrics must contain RegimeMetric values")


@dataclass(frozen=True, slots=True)
class RegimeConfidenceEvidence:
    boundary_distance: int
    agreeing_components: int
    qqq_status: ConfirmationStatus

    def __post_init__(self) -> None:
        if type(self.boundary_distance) is not int or not 0 <= self.boundary_distance <= 100:
            raise ValueError("boundary_distance must be between 0 and 100")
        if type(self.agreeing_components) is not int or not 0 <= self.agreeing_components <= 4:
            raise ValueError("agreeing_components must be between 0 and 4")
        if not isinstance(self.qqq_status, ConfirmationStatus):
            raise ValueError("qqq_status must be a ConfirmationStatus")


@dataclass(frozen=True, slots=True)
class RegimeDataQuality:
    requested_date: date
    latest_spy_date: date
    data_age_days: int
    observations_used: int
    required_observations: int
    is_valid: bool
    qqq_status: ConfirmationStatus
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.requested_date, date) or not isinstance(self.latest_spy_date, date):
            raise ValueError("dates must be date values")
        if type(self.data_age_days) is not int or self.data_age_days < 0:
            raise ValueError("data_age_days must be non-negative")
        if type(self.observations_used) is not int or self.observations_used < 0:
            raise ValueError("observations_used must be non-negative")
        if type(self.required_observations) is not int or self.required_observations <= 0:
            raise ValueError("required_observations must be positive")
        if type(self.is_valid) is not bool:
            raise ValueError("is_valid must be boolean")
        if not isinstance(self.qqq_status, ConfirmationStatus):
            raise ValueError("qqq_status must be a ConfirmationStatus")
        if not isinstance(self.warnings, tuple) or not all(
            isinstance(warning, str) for warning in self.warnings
        ):
            raise ValueError("warnings must be a tuple of strings")


@dataclass(frozen=True, slots=True)
class RegimeResult:
    evaluation_date: date
    regime: MarketRegime
    score: int
    confidence: RegimeConfidence
    confidence_evidence: RegimeConfidenceEvidence
    maximum_long_exposure: float
    strategy_permission: StrategyPermission
    components: tuple[RegimeComponent, ...]
    reasons: tuple[str, ...]
    data_quality: RegimeDataQuality

    def __post_init__(self) -> None:
        if not isinstance(self.evaluation_date, date):
            raise ValueError("evaluation_date must be a date")
        if not isinstance(self.regime, MarketRegime):
            raise ValueError("regime must be a MarketRegime")
        if type(self.score) is not int or not -100 <= self.score <= 100:
            raise ValueError("score must be between -100 and 100")
        if not isinstance(self.confidence, RegimeConfidence):
            raise ValueError("confidence must be a RegimeConfidence")
        if not isinstance(self.confidence_evidence, RegimeConfidenceEvidence):
            raise ValueError("confidence_evidence must be RegimeConfidenceEvidence")
        _finite_number(self.maximum_long_exposure, "maximum_long_exposure")
        if not 0.0 <= self.maximum_long_exposure <= 1.0:
            raise ValueError("maximum_long_exposure must be between 0 and 1")
        if not isinstance(self.strategy_permission, StrategyPermission):
            raise ValueError("strategy_permission must be a StrategyPermission")
        if not isinstance(self.components, tuple) or not all(
            isinstance(component, RegimeComponent) for component in self.components
        ):
            raise ValueError("components must contain RegimeComponent values")
        if not isinstance(self.reasons, tuple) or not all(
            isinstance(reason, str) and reason.strip() for reason in self.reasons
        ):
            raise ValueError("reasons must be a tuple of non-empty strings")
        if not isinstance(self.data_quality, RegimeDataQuality):
            raise ValueError("data_quality must be RegimeDataQuality")


def _validated_history(
    bars: Sequence[PriceBar],
    *,
    symbol: str,
    as_of: date,
    minimum_observations: int,
    enforce_staleness: bool,
) -> tuple[PriceBar, ...]:
    """Return clean, chronologically ordered history available as of ``as_of``."""
    if type(minimum_observations) is not int or minimum_observations <= 0:
        raise ValueError("minimum_observations must be positive")

    try:
        filtered = [bar for bar in bars if bar.trading_date <= as_of]
    except (AttributeError, TypeError):
        raise InvalidRegimeDataError from None

    normalized_symbol = symbol.strip().upper() if isinstance(symbol, str) else ""
    if normalized_symbol != "SPY":
        raise InvalidRegimeDataError

    try:
        ordered = sorted(filtered, key=lambda bar: bar.trading_date)
    except (AttributeError, TypeError):
        raise InvalidRegimeDataError from None

    if any(
        not isinstance(bar.symbol, str) or bar.symbol.strip().upper() != normalized_symbol
        for bar in ordered
    ):
        raise InvalidRegimeDataError

    dates = [bar.trading_date for bar in ordered]
    if len(dates) != len(set(dates)):
        raise InvalidRegimeDataError

    for bar in ordered:
        try:
            adjusted_close = bar.adjusted_close
            if not math.isfinite(adjusted_close) or adjusted_close <= 0:
                raise InvalidRegimeDataError
        except (AttributeError, TypeError, ValueError):
            raise InvalidRegimeDataError from None

    trailing = ordered[-minimum_observations:]
    if any(
        (current.trading_date - previous.trading_date).days > 10
        for previous, current in zip(trailing, trailing[1:])
    ):
        raise InvalidRegimeDataError

    if len(ordered) < minimum_observations:
        raise InsufficientRegimeHistoryError

    latest_date = ordered[-1].trading_date
    if enforce_staleness and (as_of - latest_date).days > 4:
        raise StaleRegimeDataError

    return tuple(ordered)


__all__ = [
    "ConfirmationStatus",
    "InsufficientRegimeHistoryError",
    "InvalidRegimeDataError",
    "MarketRegime",
    "RegimeComponent",
    "RegimeConfidence",
    "RegimeConfidenceEvidence",
    "RegimeDataQuality",
    "RegimeEngineError",
    "RegimeMetric",
    "RegimeResult",
    "StaleRegimeDataError",
    "StrategyPermission",
]
