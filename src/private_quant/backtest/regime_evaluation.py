"""Point-in-time evaluation utilities for the deterministic market-regime engine."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import math
from statistics import fmean, median
from types import MappingProxyType

from private_quant.data import PriceBar
from private_quant.risk import (
    InsufficientRegimeHistoryError,
    InvalidRegimeDataError,
    MarketRegime,
    MarketRegimeEngine,
    RegimeResult,
    StaleRegimeDataError,
)
from private_quant.risk.market_regime import _validated_history


HISTORICAL_REGIME_WINDOWS: Mapping[str, tuple[date, date]] = MappingProxyType(
    {
        "2008 financial crisis": (date(2007, 10, 1), date(2009, 6, 30)),
        "2020 COVID crash and recovery": (date(2020, 1, 1), date(2020, 12, 31)),
        "2022 bear market": (date(2022, 1, 1), date(2022, 12, 31)),
        "2023-2025 recovery and bull period": (date(2023, 1, 1), date(2025, 12, 31)),
    }
)


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
    ordered_qqq: tuple[PriceBar, ...] | None = None
    if qqq_bars is not None:
        try:
            ordered_qqq = _validated_history(
                qqq_bars,
                symbol="QQQ",
                as_of=date.max,
                minimum_observations=1,
                enforce_staleness=False,
            )
        except (
            InsufficientRegimeHistoryError,
            InvalidRegimeDataError,
            StaleRegimeDataError,
        ):
            ordered_qqq = None
    classifier = engine or MarketRegimeEngine()
    classified: list[tuple[PriceBar, RegimeResult]] = []

    for index, bar in enumerate(ordered_spy):
        if index < 251:
            continue
        qqq_history = (
            tuple(qqq_bar for qqq_bar in ordered_qqq if qqq_bar.trading_date <= bar.trading_date)
            if ordered_qqq is not None
            else None
        )
        result = classifier.evaluate(
            tuple(ordered_spy[: index + 1]),
            as_of=bar.trading_date,
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
    "HISTORICAL_REGIME_WINDOWS",
    "RegimeBucketStats",
    "RegimeComparison",
    "RegimeEquityPoint",
    "RegimeEvaluationResult",
    "RegimeObservation",
    "evaluate_regime_history",
]
