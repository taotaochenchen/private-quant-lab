"""Immutable contracts and input validation for market-regime evaluation."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import math
from statistics import fmean, pstdev
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


def _finite_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be finite")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{field_name} must be finite")
    return numeric


def score_drawdown(drawdown: float) -> int:
    """Return the fixed stress score for a 252-session drawdown."""
    value = _finite_float(drawdown, "drawdown")
    if value >= -0.05:
        return 25
    if value >= -0.10:
        return 10
    if value >= -0.15:
        return -5
    if value >= -0.20:
        return -15
    return -25


def score_realized_volatility(volatility: float) -> int:
    """Return the fixed score for annualized 20-session realized volatility."""
    value = _finite_float(volatility, "volatility")
    if value <= 0.15:
        return 15
    if value <= 0.20:
        return 8
    if value <= 0.30:
        return 0
    if value <= 0.40:
        return -8
    return -15


def regime_from_score(score: int) -> MarketRegime:
    """Classify a bounded integer score using inclusive regime thresholds."""
    if type(score) is not int or not -100 <= score <= 100:
        raise ValueError("score must be an integer between -100 and 100")
    if score >= 45:
        return MarketRegime.BULL
    if score >= 15:
        return MarketRegime.CAUTIOUS_BULL
    if score >= -20:
        return MarketRegime.RISK_OFF
    return MarketRegime.BEAR


def risk_mapping_for(regime: MarketRegime) -> tuple[float, StrategyPermission]:
    """Return the fixed exposure cap and permission for a regime."""
    mappings = {
        MarketRegime.BULL: (1.0, StrategyPermission.NORMAL),
        MarketRegime.CAUTIOUS_BULL: (0.7, StrategyPermission.REDUCED),
        MarketRegime.RISK_OFF: (0.3, StrategyPermission.DEFENSIVE),
        MarketRegime.BEAR: (0.0, StrategyPermission.BLOCKED),
    }
    try:
        return mappings[regime]
    except (KeyError, TypeError):
        raise ValueError("regime must be a MarketRegime") from None


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
    if normalized_symbol not in {"SPY", "QQQ"}:
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


def _mean(values: Sequence[float]) -> float:
    return fmean(values)


def _return_over(prices: Sequence[float], sessions: int) -> float:
    return prices[-1] / prices[-1 - sessions] - 1.0


def _realized_volatility(prices: Sequence[float]) -> float:
    returns = tuple(
        prices[index] / prices[index - 1] - 1.0
        for index in range(len(prices) - 20, len(prices))
    )
    return pstdev(returns) * math.sqrt(252.0)


def _comparison_score(left: float, right: float, weight: int) -> int:
    if left > right:
        return weight
    if left < right:
        return -weight
    return 0


def _component(
    name: str,
    score: int,
    max_abs_score: int,
    metrics: tuple[RegimeMetric, ...],
    explanation: str,
) -> RegimeComponent:
    return RegimeComponent(name, score, max_abs_score, metrics, explanation)


class MarketRegimeEngine:
    """Classify adjusted-close SPY history without provider or broker dependencies."""

    _SPY_REQUIRED_OBSERVATIONS = 252
    _QQQ_REQUIRED_OBSERVATIONS = 201
    _QQQ_UNAVAILABLE_WARNING = "QQQ confirmation unavailable."

    def evaluate(
        self,
        spy_bars: Sequence[PriceBar],
        *,
        as_of: date,
        qqq_bars: Sequence[PriceBar] | None = None,
    ) -> RegimeResult:
        spy_history = _validated_history(
            spy_bars,
            symbol="SPY",
            as_of=as_of,
            minimum_observations=self._SPY_REQUIRED_OBSERVATIONS,
            enforce_staleness=True,
        )
        components = self._spy_components(spy_history)
        score = sum(component.score for component in components)
        regime = regime_from_score(score)
        qqq_status = self._qqq_status(qqq_bars, as_of)
        confidence, evidence = self._confidence_for(score, components, qqq_status)
        maximum_long_exposure, strategy_permission = risk_mapping_for(regime)
        latest_spy_date = spy_history[-1].trading_date
        warnings = (
            (self._QQQ_UNAVAILABLE_WARNING,)
            if qqq_status is ConfirmationStatus.UNAVAILABLE
            else ()
        )
        reasons = tuple(component.explanation for component in components) + (
            self._qqq_reason(qqq_status),
        )
        return RegimeResult(
            evaluation_date=latest_spy_date,
            regime=regime,
            score=score,
            confidence=confidence,
            confidence_evidence=evidence,
            maximum_long_exposure=maximum_long_exposure,
            strategy_permission=strategy_permission,
            components=components,
            reasons=reasons,
            data_quality=RegimeDataQuality(
                requested_date=as_of,
                latest_spy_date=latest_spy_date,
                data_age_days=(as_of - latest_spy_date).days,
                observations_used=self._SPY_REQUIRED_OBSERVATIONS,
                required_observations=self._SPY_REQUIRED_OBSERVATIONS,
                is_valid=True,
                qqq_status=qqq_status,
                warnings=warnings,
            ),
        )

    @staticmethod
    def _spy_components(history: Sequence[PriceBar]) -> tuple[RegimeComponent, ...]:
        prices = tuple(bar.adjusted_close for bar in history[-252:])
        latest = prices[-1]
        sma50 = _mean(prices[-50:])
        sma200 = _mean(prices[-200:])
        prior_sma200 = _mean(prices[-220:-20])
        slope = sma200 / prior_sma200 - 1.0
        return20 = _return_over(prices, 20)
        return60 = _return_over(prices, 60)
        drawdown = latest / max(prices) - 1.0
        volatility = _realized_volatility(prices)

        trend_score = (
            _comparison_score(latest, sma50, 8)
            + _comparison_score(latest, sma200, 12)
            + _comparison_score(sma50, sma200, 12)
            + _comparison_score(slope, 0.0, 8)
        )
        momentum_score = _comparison_score(return20, 0.0, 8) + _comparison_score(
            return60, 0.0, 12
        )
        drawdown_score = score_drawdown(drawdown)
        volatility_score = score_realized_volatility(volatility)
        return (
            _component(
                "Primary trend",
                trend_score,
                40,
                (
                    RegimeMetric("SPY close", latest, "price", "Latest adjusted close"),
                    RegimeMetric("SMA50", sma50, "price", "Latest 50-session adjusted-close mean"),
                    RegimeMetric("SMA200", sma200, "price", "Latest 200-session adjusted-close mean"),
                    RegimeMetric("SMA200 slope", slope, "ratio", "Current versus 20-sessions-prior SMA200"),
                ),
                f"Primary trend score {trend_score:+d} from price, moving-average, and slope comparisons.",
            ),
            _component(
                "Momentum",
                momentum_score,
                20,
                (
                    RegimeMetric("20-session return", return20, "ratio", "Latest adjusted close versus 20 sessions ago"),
                    RegimeMetric("60-session return", return60, "ratio", "Latest adjusted close versus 60 sessions ago"),
                ),
                f"Momentum score {momentum_score:+d} from 20- and 60-session adjusted-close returns.",
            ),
            _component(
                "Drawdown",
                drawdown_score,
                25,
                (
                    RegimeMetric("252-session drawdown", drawdown, "ratio", "Latest close versus trailing 252-session high"),
                ),
                f"Drawdown score {drawdown_score:+d} from the trailing 252-session high.",
            ),
            _component(
                "Realized volatility",
                volatility_score,
                15,
                (
                    RegimeMetric("20-session realized volatility", volatility, "ratio", "Population volatility annualized by sqrt(252)"),
                ),
                f"Realized volatility score {volatility_score:+d} from the latest 20 daily returns.",
            ),
        )

    def _qqq_status(
        self,
        qqq_bars: Sequence[PriceBar] | None,
        as_of: date,
    ) -> ConfirmationStatus:
        if not qqq_bars:
            return ConfirmationStatus.UNAVAILABLE
        try:
            history = _validated_history(
                qqq_bars,
                symbol="QQQ",
                as_of=as_of,
                minimum_observations=self._QQQ_REQUIRED_OBSERVATIONS,
                enforce_staleness=True,
            )
        except (
            InsufficientRegimeHistoryError,
            InvalidRegimeDataError,
            StaleRegimeDataError,
        ):
            return ConfirmationStatus.UNAVAILABLE
        prices = tuple(bar.adjusted_close for bar in history)
        above_sma200 = prices[-1] > _mean(prices[-200:])
        positive_return60 = _return_over(prices, 60) > 0.0
        below_sma200 = prices[-1] < _mean(prices[-200:])
        negative_return60 = _return_over(prices, 60) < 0.0
        if above_sma200 and positive_return60:
            return ConfirmationStatus.CONFIRMS_POSITIVE
        if below_sma200 and negative_return60:
            return ConfirmationStatus.CONFIRMS_NEGATIVE
        return ConfirmationStatus.MIXED

    @staticmethod
    def _confidence_for(
        score: int,
        components: Sequence[RegimeComponent],
        qqq_status: ConfirmationStatus,
    ) -> tuple[RegimeConfidence, RegimeConfidenceEvidence]:
        boundary_distance = min(abs(score - boundary) for boundary in (-20, 15, 45))
        regime = regime_from_score(score)
        defensive_regime = regime in {MarketRegime.RISK_OFF, MarketRegime.BEAR}
        confirmation_agrees = (
            qqq_status is ConfirmationStatus.CONFIRMS_NEGATIVE
            if defensive_regime
            else qqq_status is ConfirmationStatus.CONFIRMS_POSITIVE
        )
        confirmation_contradicts = (
            qqq_status is ConfirmationStatus.CONFIRMS_POSITIVE
            if defensive_regime
            else qqq_status is ConfirmationStatus.CONFIRMS_NEGATIVE
        )
        if score > 0:
            agreeing_components = sum(component.score > 0 for component in components)
        elif score < 0:
            agreeing_components = sum(component.score < 0 for component in components)
        else:
            agreeing_components = 0
        evidence = RegimeConfidenceEvidence(
            boundary_distance=boundary_distance,
            agreeing_components=agreeing_components,
            qqq_status=qqq_status,
        )
        if score == 0:
            return RegimeConfidence.LOW, evidence
        if boundary_distance >= 10 and agreeing_components >= 3 and confirmation_agrees:
            return RegimeConfidence.HIGH, evidence
        if (
            boundary_distance >= 5
            and agreeing_components >= 2
            and not confirmation_contradicts
        ):
            return RegimeConfidence.MEDIUM, evidence
        return RegimeConfidence.LOW, evidence

    @staticmethod
    def _qqq_reason(status: ConfirmationStatus) -> str:
        explanations = {
            ConfirmationStatus.CONFIRMS_POSITIVE: "QQQ confirmation is positive.",
            ConfirmationStatus.CONFIRMS_NEGATIVE: "QQQ confirmation is negative.",
            ConfirmationStatus.MIXED: "QQQ confirmation is mixed.",
            ConfirmationStatus.UNAVAILABLE: "QQQ confirmation is unavailable.",
        }
        return explanations[status]


__all__ = [
    "ConfirmationStatus",
    "InsufficientRegimeHistoryError",
    "InvalidRegimeDataError",
    "MarketRegimeEngine",
    "MarketRegime",
    "RegimeComponent",
    "RegimeConfidence",
    "RegimeConfidenceEvidence",
    "RegimeDataQuality",
    "RegimeEngineError",
    "RegimeMetric",
    "RegimeResult",
    "regime_from_score",
    "risk_mapping_for",
    "score_drawdown",
    "score_realized_volatility",
    "StaleRegimeDataError",
    "StrategyPermission",
]
