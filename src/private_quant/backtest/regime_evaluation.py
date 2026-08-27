"""Point-in-time evaluation utilities for the deterministic market-regime engine."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
import math
from statistics import fmean, median
from types import MappingProxyType

from private_quant.data import PriceBar
from private_quant.risk import (
    InvalidRegimeDataError,
    MarketRegime,
    MarketRegimeEngine,
    RegimeResult,
)
from private_quant.risk.market_regime import _canonical_trading_date, _validated_history


HISTORICAL_REGIME_WINDOWS: Mapping[str, tuple[date, date]] = MappingProxyType(
    {
        "2008 financial crisis": (date(2007, 10, 1), date(2009, 6, 30)),
        "2020 COVID crash and recovery": (date(2020, 1, 1), date(2020, 12, 31)),
        "2022 bear market": (date(2022, 1, 1), date(2022, 12, 31)),
        "2023-2025 recovery and bull period": (date(2023, 1, 1), date(2025, 12, 31)),
    }
)


class InvalidEvaluationDataError(ValueError):
    """Raised when Evaluation V1.1 cannot build a safe common history."""


class EvaluationStrategy(str, Enum):
    SPY_BUY_AND_HOLD = "spy_buy_and_hold"
    TREND_200 = "trend_200"
    REGIME_ZERO_YIELD_CASH = "regime_v1_zero_yield_cash"
    REGIME_BIL_CASH_PROXY = "regime_v1_bil_cash_proxy"


class EvaluationAvailability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


EVALUATION_TRANSACTION_COST_BPS = (0.0, 2.0, 5.0, 10.0)


@dataclass(frozen=True, slots=True)
class ExposureBucketPercentage:
    exposure: float
    percent_sessions: float


@dataclass(frozen=True, slots=True)
class EvaluationPoint:
    signal_date: date
    return_end_date: date
    starting_value: float
    ending_value: float
    target_spy_exposure: float
    spy_return: float
    residual_cash_return: float
    net_return: float
    exposure_change: float
    transaction_cost: float


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    initial_capital: float
    final_value: float
    total_return: float
    cagr: float | None
    max_drawdown: float
    annualized_volatility: float | None
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    total_transaction_cost: float
    annualized_turnover: float | None
    exposure_changes: int
    average_spy_exposure: float | None
    exposure_buckets: tuple[ExposureBucketPercentage, ...]


@dataclass(frozen=True, slots=True)
class StrategyScenarioResult:
    strategy: EvaluationStrategy
    transaction_cost_bps: float
    first_signal_date: date
    final_return_end_date: date
    metrics: PerformanceMetrics
    points: tuple[EvaluationPoint, ...]


@dataclass(frozen=True, slots=True)
class HistoricalWindowResult:
    window_name: str
    requested_start: date
    requested_end: date
    strategy: EvaluationStrategy
    transaction_cost_bps: float
    availability: EvaluationAvailability
    effective_signal_date: date | None
    effective_return_end_date: date | None
    interval_count: int
    normalized_start_value: float | None
    normalized_end_value: float | None
    strategy_return: float | None
    max_drawdown: float | None
    exposure_changes: int | None
    average_spy_exposure: float | None
    transaction_cost: float | None


@dataclass(frozen=True, slots=True)
class RegimeEvaluationV11Result:
    common_intervals: tuple[tuple[date, date], ...]
    scenarios: tuple[StrategyScenarioResult, ...]
    windows: tuple[HistoricalWindowResult, ...]


@dataclass(frozen=True, slots=True)
class _PriceInterval:
    signal_date: date
    return_end_date: date
    spy_return: float
    bil_return: float


@dataclass(frozen=True, slots=True)
class _AlignedEvaluationHistory:
    spy_history: tuple[PriceBar, ...]
    intervals: tuple[_PriceInterval, ...]


@dataclass(frozen=True, slots=True)
class RegimeObservation:
    trading_date: date
    result: RegimeResult
    spy_adjusted_close: float
    forward_return_20: float | None
    forward_return_60: float | None


@dataclass(frozen=True, slots=True)
class RegimeBucketStats:
    regime: MarketRegime
    sessions: int
    percent_sessions: float
    mean_forward_return_20: float | None
    mean_forward_return_60: float | None
    episode_count: int
    mean_duration: float
    median_duration: float
    max_duration: int
    worst_episode_drawdown: float


@dataclass(frozen=True, slots=True)
class RegimeEquityPoint:
    trading_date: date
    value: float


@dataclass(frozen=True, slots=True)
class RegimeComparison:
    initial_capital: float
    final_value: float
    max_drawdown: float
    transaction_cost: float
    equity_curve: tuple[RegimeEquityPoint, ...]


@dataclass(frozen=True, slots=True)
class RegimeEvaluationResult:
    observations: tuple[RegimeObservation, ...]
    bucket_stats: tuple[RegimeBucketStats, ...]
    transition_count: int
    annualized_transitions: float
    whipsaw_count: int
    whipsaw_rate: float
    buy_and_hold: RegimeComparison
    regime_capped: RegimeComparison


@dataclass(frozen=True, slots=True)
class _Episode:
    regime: MarketRegime
    observations: tuple[RegimeObservation, ...]


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be finite")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{field_name} must be finite")
    return numeric


def _evaluation_date(value: date | None, field_name: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, date) or isinstance(value, datetime):
        raise InvalidEvaluationDataError(f"{field_name} must be a date")
    return value


def _date_bars(
    bars: Sequence[PriceBar],
    *,
    series_name: str,
) -> tuple[tuple[date, PriceBar], ...]:
    """Read only canonical dates, failing when temporal placement is impossible."""
    try:
        dated = tuple((_canonical_trading_date(bar), bar) for bar in bars)
        return tuple(sorted(dated, key=lambda item: item[0]))
    except (AttributeError, InvalidRegimeDataError, TypeError, ValueError, OverflowError):
        raise InvalidEvaluationDataError(f"{series_name} trading date is invalid") from None


def _validate_active_bars(
    dated_bars: Sequence[tuple[date, PriceBar]],
    *,
    symbol: str,
    start: date | None,
    end: date,
) -> tuple[tuple[date, PriceBar], ...]:
    """Validate symbol/date/adjusted close only inside the active boundary."""
    active_bars = tuple(
        (trading_date, bar)
        for trading_date, bar in dated_bars
        if (start is None or start <= trading_date) and trading_date <= end
    )
    dates = tuple(trading_date for trading_date, _ in active_bars)
    if any(current == previous for previous, current in zip(dates, dates[1:])):
        raise InvalidEvaluationDataError(f"{symbol} has duplicate active trading dates")

    for _, bar in active_bars:
        try:
            bar_symbol = bar.symbol
        except AttributeError:
            raise InvalidEvaluationDataError(f"{symbol} history contains the wrong symbol") from None
        if not isinstance(bar_symbol, str) or bar_symbol.strip().upper() != symbol:
            raise InvalidEvaluationDataError(f"{symbol} history contains the wrong symbol")
        try:
            adjusted_close = _finite_number(bar.adjusted_close, "adjusted_close")
        except (AttributeError, TypeError, ValueError, OverflowError):
            raise InvalidEvaluationDataError(f"{symbol} adjusted close must be finite and positive") from None
        if adjusted_close <= 0:
            raise InvalidEvaluationDataError(f"{symbol} adjusted close must be finite and positive")
    return active_bars


def _align_evaluation_history(
    spy_bars: Sequence[PriceBar],
    bil_bars: Sequence[PriceBar],
    *,
    evaluation_start: date | None = None,
    evaluation_end: date | None = None,
) -> _AlignedEvaluationHistory:
    """Build one exact SPY/BIL interval sequence after 252-session warm-up."""
    requested_start = _evaluation_date(evaluation_start, "evaluation_start")
    requested_end = _evaluation_date(evaluation_end, "evaluation_end")
    dated_spy = _date_bars(spy_bars, series_name="SPY")
    dated_bil = _date_bars(bil_bars, series_name="BIL")
    if not dated_spy:
        raise InvalidEvaluationDataError("SPY history has no observations")
    if not dated_bil:
        raise InvalidEvaluationDataError("BIL history has no observations")

    outer_return_end = min(
        dated_spy[-1][0],
        dated_bil[-1][0],
        requested_end if requested_end is not None else date.max,
    )
    active_spy = _validate_active_bars(
        dated_spy,
        symbol="SPY",
        start=None,
        end=outer_return_end,
    )
    if len(active_spy) < 253:
        raise InvalidEvaluationDataError("SPY history has no complete evaluation intervals")

    first_eligible_signal = active_spy[251][0]
    common_signal_start = max(
        first_eligible_signal,
        dated_bil[0][0],
        requested_start if requested_start is not None else date.min,
    )
    first_signal_index = next(
        (
            index
            for index, (trading_date, _) in enumerate(active_spy)
            if index >= 251 and trading_date >= common_signal_start
        ),
        None,
    )
    if first_signal_index is None or first_signal_index >= len(active_spy) - 1:
        raise InvalidEvaluationDataError("SPY history has no complete evaluation intervals")

    active_bil = _validate_active_bars(
        dated_bil,
        symbol="BIL",
        start=active_spy[first_signal_index][0],
        end=outer_return_end,
    )
    bil_by_date = {trading_date: bar for trading_date, bar in active_bil}

    intervals: list[_PriceInterval] = []
    for index in range(first_signal_index, len(active_spy) - 1):
        signal_date, signal_spy = active_spy[index]
        return_end_date, return_end_spy = active_spy[index + 1]
        signal_bil = bil_by_date.get(signal_date)
        return_end_bil = bil_by_date.get(return_end_date)
        if signal_bil is None or return_end_bil is None:
            raise InvalidEvaluationDataError("BIL history is missing an active SPY trading date")
        intervals.append(
            _PriceInterval(
                signal_date=signal_date,
                return_end_date=return_end_date,
                spy_return=return_end_spy.adjusted_close / signal_spy.adjusted_close - 1.0,
                bil_return=return_end_bil.adjusted_close / signal_bil.adjusted_close - 1.0,
            )
        )

    return _AlignedEvaluationHistory(
        spy_history=tuple(bar for _, bar in active_spy),
        intervals=tuple(intervals),
    )


def _target_exposures(
    aligned: _AlignedEvaluationHistory,
    *,
    qqq_bars: Sequence[PriceBar] | None = None,
    engine: MarketRegimeEngine | None = None,
) -> Mapping[EvaluationStrategy, tuple[float, ...]]:
    """Derive each strategy's target exposure from signal-date information only."""
    classifier = engine or MarketRegimeEngine()
    spy_indices = {
        _canonical_trading_date(bar): index
        for index, bar in enumerate(aligned.spy_history)
    }
    buy_and_hold: list[float] = []
    trend: list[float] = []
    regime: list[float] = []

    for interval in aligned.intervals:
        signal_index = spy_indices[interval.signal_date]
        visible_spy = aligned.spy_history[: signal_index + 1]
        visible_qqq = (
            tuple(
                bar
                for bar in qqq_bars
                if _canonical_trading_date(bar) <= interval.signal_date
            )
            if qqq_bars is not None
            else None
        )
        result = classifier.evaluate(
            visible_spy,
            as_of=interval.signal_date,
            qqq_bars=visible_qqq,
        )
        exposure = result.maximum_long_exposure
        if exposure not in (0.0, 0.3, 0.7, 1.0):
            raise InvalidEvaluationDataError("Regime exposure mapping is invalid")

        buy_and_hold.append(1.0)
        trend.append(
            1.0
            if visible_spy[-1].adjusted_close
            >= fmean(bar.adjusted_close for bar in visible_spy[-200:])
            else 0.0
        )
        regime.append(exposure)

    schedule = tuple(regime)
    return MappingProxyType(
        {
            EvaluationStrategy.SPY_BUY_AND_HOLD: tuple(buy_and_hold),
            EvaluationStrategy.TREND_200: tuple(trend),
            EvaluationStrategy.REGIME_ZERO_YIELD_CASH: schedule,
            EvaluationStrategy.REGIME_BIL_CASH_PROXY: schedule,
        }
    )


def _simulate_intervals(
    intervals: Sequence[_PriceInterval],
    exposures: Sequence[float],
    *,
    strategy: EvaluationStrategy,
    initial_capital: float,
    transaction_cost_bps: float,
) -> tuple[EvaluationPoint, ...]:
    """Apply D0 cost before the target exposure earns the D0-to-D1 return."""
    if len(intervals) != len(exposures):
        raise ValueError("intervals and exposures must have equal length")
    if not isinstance(strategy, EvaluationStrategy):
        raise ValueError("strategy is invalid")

    starting_value = _finite_number(initial_capital, "initial_capital")
    costs_bps = _finite_number(transaction_cost_bps, "transaction_cost_bps")
    if starting_value <= 0:
        raise ValueError("initial_capital must be positive")
    if costs_bps < 0:
        raise ValueError("transaction_cost_bps cannot be negative")

    points: list[EvaluationPoint] = []
    prior_exposure = 0.0
    prior_return_end_date: date | None = None
    for interval, raw_exposure in zip(intervals, exposures):
        if (
            not isinstance(interval.signal_date, date)
            or isinstance(interval.signal_date, datetime)
            or not isinstance(interval.return_end_date, date)
            or isinstance(interval.return_end_date, datetime)
            or interval.signal_date >= interval.return_end_date
            or (
                prior_return_end_date is not None
                and interval.signal_date != prior_return_end_date
            )
        ):
            raise ValueError("evaluation interval boundaries must be consecutive")

        exposure = _finite_number(raw_exposure, "target_spy_exposure")
        spy_return = _finite_number(interval.spy_return, "spy_return")
        if exposure < 0.0 or exposure > 1.0:
            raise ValueError("target_spy_exposure must be between zero and one")

        cash_return = 0.0
        if strategy is EvaluationStrategy.REGIME_BIL_CASH_PROXY:
            cash_return = _finite_number(interval.bil_return, "bil_return")
        gross_return = exposure * spy_return + (1.0 - exposure) * cash_return
        exposure_change = abs(exposure - prior_exposure)
        transaction_cost = starting_value * exposure_change * costs_bps / 10_000.0
        ending_value = (starting_value - transaction_cost) * (1.0 + gross_return)
        net_return = ending_value / starting_value - 1.0
        if (
            not math.isfinite(gross_return)
            or not math.isfinite(transaction_cost)
            or not math.isfinite(ending_value)
            or not math.isfinite(net_return)
            or ending_value <= 0.0
        ):
            raise ValueError("evaluation interval calculation is invalid")

        points.append(
            EvaluationPoint(
                signal_date=interval.signal_date,
                return_end_date=interval.return_end_date,
                starting_value=starting_value,
                ending_value=ending_value,
                target_spy_exposure=exposure,
                spy_return=spy_return,
                residual_cash_return=cash_return,
                net_return=net_return,
                exposure_change=exposure_change,
                transaction_cost=transaction_cost,
            )
        )
        starting_value = ending_value
        prior_exposure = exposure
        prior_return_end_date = interval.return_end_date

    return tuple(points)


def _episodes(observations: Sequence[RegimeObservation]) -> tuple[_Episode, ...]:
    if not observations:
        return ()

    episodes: list[_Episode] = []
    current: list[RegimeObservation] = [observations[0]]
    for observation in observations[1:]:
        if observation.result.regime == current[-1].result.regime:
            current.append(observation)
            continue
        episodes.append(_Episode(current[-1].result.regime, tuple(current)))
        current = [observation]
    episodes.append(_Episode(current[-1].result.regime, tuple(current)))
    return tuple(episodes)


def _max_drawdown(points: Sequence[RegimeEquityPoint]) -> float:
    if not points:
        return 0.0
    peak = points[0].value
    drawdown = 0.0
    for point in points:
        peak = max(peak, point.value)
        if peak > 0:
            drawdown = min(drawdown, point.value / peak - 1.0)
    return drawdown


def _episode_drawdown(episode: _Episode) -> float:
    peak = episode.observations[0].spy_adjusted_close
    drawdown = 0.0
    for observation in episode.observations:
        peak = max(peak, observation.spy_adjusted_close)
        drawdown = min(drawdown, observation.spy_adjusted_close / peak - 1.0)
    return drawdown


def _bucket_stats(
    observations: Sequence[RegimeObservation],
    episodes: Sequence[_Episode],
) -> tuple[RegimeBucketStats, ...]:
    total_sessions = len(observations)
    result: list[RegimeBucketStats] = []
    for regime in MarketRegime:
        regime_observations = [
            observation for observation in observations if observation.result.regime is regime
        ]
        regime_episodes = [episode for episode in episodes if episode.regime is regime]
        durations = [len(episode.observations) for episode in regime_episodes]
        returns_20 = [
            observation.forward_return_20
            for observation in regime_observations
            if observation.forward_return_20 is not None
        ]
        returns_60 = [
            observation.forward_return_60
            for observation in regime_observations
            if observation.forward_return_60 is not None
        ]
        result.append(
            RegimeBucketStats(
                regime=regime,
                sessions=len(regime_observations),
                percent_sessions=(len(regime_observations) / total_sessions * 100.0)
                if total_sessions
                else 0.0,
                mean_forward_return_20=fmean(returns_20) if returns_20 else None,
                mean_forward_return_60=fmean(returns_60) if returns_60 else None,
                episode_count=len(regime_episodes),
                mean_duration=fmean(durations) if durations else 0.0,
                median_duration=float(median(durations)) if durations else 0.0,
                max_duration=max(durations, default=0),
                worst_episode_drawdown=min(
                    (_episode_drawdown(episode) for episode in regime_episodes),
                    default=0.0,
                ),
            )
        )
    return tuple(result)


def _comparison_curves(
    observations: Sequence[RegimeObservation],
    initial_capital: float,
    transaction_cost_bps: float,
) -> tuple[RegimeComparison, RegimeComparison]:
    if not observations:
        empty = RegimeComparison(initial_capital, initial_capital, 0.0, 0.0, ())
        return empty, empty

    buy_and_hold_curve = [RegimeEquityPoint(observations[0].trading_date, initial_capital)]
    regime_capped_curve = [RegimeEquityPoint(observations[0].trading_date, initial_capital)]
    buy_and_hold_value = initial_capital
    regime_capped_value = initial_capital
    prior_exposure = 0.0
    transaction_cost = 0.0
    cost_rate = transaction_cost_bps / 10_000.0

    for index in range(1, len(observations)):
        prior = observations[index - 1]
        current = observations[index]
        next_return = current.spy_adjusted_close / prior.spy_adjusted_close - 1.0

        buy_and_hold_value *= 1.0 + next_return
        buy_and_hold_curve.append(RegimeEquityPoint(current.trading_date, buy_and_hold_value))

        exposure = prior.result.maximum_long_exposure
        cost = abs(exposure - prior_exposure) * regime_capped_value * cost_rate
        transaction_cost += cost
        regime_capped_value = (regime_capped_value - cost) * (1.0 + exposure * next_return)
        regime_capped_curve.append(RegimeEquityPoint(current.trading_date, regime_capped_value))
        prior_exposure = exposure

    buy_and_hold = RegimeComparison(
        initial_capital=initial_capital,
        final_value=buy_and_hold_value,
        max_drawdown=_max_drawdown(buy_and_hold_curve),
        transaction_cost=0.0,
        equity_curve=tuple(buy_and_hold_curve),
    )
    regime_capped = RegimeComparison(
        initial_capital=initial_capital,
        final_value=regime_capped_value,
        max_drawdown=_max_drawdown(regime_capped_curve),
        transaction_cost=transaction_cost,
        equity_curve=tuple(regime_capped_curve),
    )
    return buy_and_hold, regime_capped


def _ordered_optional_qqq(
    qqq_bars: Sequence[PriceBar],
) -> tuple[tuple[date, PriceBar], ...] | None:
    """Order optional QQQ by date without validating future bar contents."""
    try:
        dated = tuple((_canonical_trading_date(bar), bar) for bar in qqq_bars)
        ordered = tuple(sorted(dated, key=lambda item: item[0]))
    except InvalidRegimeDataError:
        return None
    return ordered or None


def evaluate_regime_history(
    spy_bars: Sequence[PriceBar],
    *,
    qqq_bars: Sequence[PriceBar] | None = None,
    engine: MarketRegimeEngine | None = None,
    initial_capital: float = 100_000.0,
    transaction_cost_bps: float = 5.0,
) -> RegimeEvaluationResult:
    """Classify every eligible SPY session using only information available then."""
    capital = _finite_number(initial_capital, "initial_capital")
    costs_bps = _finite_number(transaction_cost_bps, "transaction_cost_bps")
    if capital <= 0:
        raise ValueError("initial_capital must be positive")
    if costs_bps < 0:
        raise ValueError("transaction_cost_bps cannot be negative")

    ordered_spy = _validated_history(
        spy_bars,
        symbol="SPY",
        as_of=date.max,
        minimum_observations=252,
        enforce_staleness=False,
    )
    ordered_qqq = _ordered_optional_qqq(qqq_bars) if qqq_bars is not None else None
    classifier = engine or MarketRegimeEngine()
    classified: list[tuple[PriceBar, RegimeResult]] = []

    for index, bar in enumerate(ordered_spy):
        if index < 251:
            continue
        evaluation_date = _canonical_trading_date(bar)
        qqq_history = (
            tuple(qqq_bar for qqq_date, qqq_bar in ordered_qqq if qqq_date <= evaluation_date)
            if ordered_qqq is not None
            else None
        )
        result = classifier.evaluate(
            tuple(ordered_spy[: index + 1]),
            as_of=evaluation_date,
            qqq_bars=qqq_history,
        )
        classified.append((bar, result))

    observations = tuple(
        RegimeObservation(
            trading_date=bar.trading_date,
            result=result,
            spy_adjusted_close=bar.adjusted_close,
            forward_return_20=(
                ordered_spy[index + 20].adjusted_close / bar.adjusted_close - 1.0
                if index + 20 < len(ordered_spy)
                else None
            ),
            forward_return_60=(
                ordered_spy[index + 60].adjusted_close / bar.adjusted_close - 1.0
                if index + 60 < len(ordered_spy)
                else None
            ),
        )
        for index, (bar, result) in enumerate(classified, 251)
    )
    episodes = _episodes(observations)
    transition_count = sum(
        current.result.regime is not previous.result.regime
        for previous, current in zip(observations, observations[1:])
    )
    whipsaw_count = sum(
        len(episode.observations) <= 10
        and prior.regime is following.regime
        for prior, episode, following in zip(episodes, episodes[1:], episodes[2:])
    )
    buy_and_hold, regime_capped = _comparison_curves(observations, capital, costs_bps)

    return RegimeEvaluationResult(
        observations=observations,
        bucket_stats=_bucket_stats(observations, episodes),
        transition_count=transition_count,
        annualized_transitions=(transition_count / len(observations) * 252.0)
        if observations
        else 0.0,
        whipsaw_count=whipsaw_count,
        whipsaw_rate=whipsaw_count / transition_count if transition_count else 0.0,
        buy_and_hold=buy_and_hold,
        regime_capped=regime_capped,
    )


__all__ = [
    "EVALUATION_TRANSACTION_COST_BPS",
    "EvaluationAvailability",
    "EvaluationPoint",
    "EvaluationStrategy",
    "ExposureBucketPercentage",
    "HISTORICAL_REGIME_WINDOWS",
    "HistoricalWindowResult",
    "InvalidEvaluationDataError",
    "PerformanceMetrics",
    "RegimeBucketStats",
    "RegimeComparison",
    "RegimeEquityPoint",
    "RegimeEvaluationResult",
    "RegimeEvaluationV11Result",
    "RegimeObservation",
    "StrategyScenarioResult",
    "evaluate_regime_history",
]
