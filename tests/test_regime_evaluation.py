from dataclasses import FrozenInstanceError
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.backtest.regime_evaluation import (
    HISTORICAL_REGIME_WINDOWS,
    RegimeBucketStats,
    RegimeComparison,
    RegimeEquityPoint,
    RegimeEvaluationResult,
    RegimeObservation,
    evaluate_regime_history,
)
from private_quant.data import PriceBar
from private_quant.risk import (
    ConfirmationStatus,
    InsufficientRegimeHistoryError,
    InvalidRegimeDataError,
    MarketRegime,
    RegimeConfidence,
    RegimeConfidenceEvidence,
    RegimeDataQuality,
    RegimeResult,
    StrategyPermission,
)


def make_bars(count: int, prices: list[float] | None = None) -> list[PriceBar]:
    closes = prices or [100.0 + index for index in range(count)]
    return [
        PriceBar(
            symbol="SPY",
            trading_date=date(2020, 1, 1) + timedelta(days=index),
            open=close,
            high=close,
            low=close,
            close=close,
            adjusted_close=close,
            volume=1_000_000,
        )
        for index, close in enumerate(closes)
    ]


def regime_result(
    trading_date: date,
    regime: MarketRegime,
    exposure: float,
) -> RegimeResult:
    return RegimeResult(
        evaluation_date=trading_date,
        regime=regime,
        score=0,
        confidence=RegimeConfidence.LOW,
        confidence_evidence=RegimeConfidenceEvidence(
            boundary_distance=0,
            agreeing_components=0,
            qqq_status=ConfirmationStatus.UNAVAILABLE,
        ),
        maximum_long_exposure=exposure,
        strategy_permission=StrategyPermission.NORMAL,
        components=(),
        reasons=("test result",),
        data_quality=RegimeDataQuality(
            requested_date=trading_date,
            latest_spy_date=trading_date,
            data_age_days=0,
            observations_used=252,
            required_observations=252,
            is_valid=True,
            qqq_status=ConfirmationStatus.UNAVAILABLE,
            warnings=(),
        ),
    )


class RecordingEngine:
    def __init__(self, selector=None) -> None:
        self.calls: list[tuple[date, tuple[PriceBar, ...], tuple[PriceBar, ...] | None]] = []
        self.selector = selector or (lambda as_of, bars: (MarketRegime.BULL, 1.0))

    def evaluate(self, spy_bars, *, as_of, qqq_bars=None) -> RegimeResult:
        spy_history = tuple(spy_bars)
        qqq_history = tuple(qqq_bars) if qqq_bars is not None else None
        if any(bar.trading_date > as_of for bar in spy_history):
            raise AssertionError("SPY future bar entered classifier")
        if qqq_history and any(bar.trading_date > as_of for bar in qqq_history):
            raise AssertionError("QQQ future bar entered classifier")
        self.calls.append((as_of, spy_history, qqq_history))
        regime, exposure = self.selector(as_of, spy_history)
        return regime_result(as_of, regime, exposure)


class RegimeEvaluationContractTests(unittest.TestCase):
    def test_models_are_frozen_slotted_outputs(self) -> None:
        result = regime_result(date(2021, 1, 1), MarketRegime.BULL, 1.0)
        observation = RegimeObservation(date(2021, 1, 1), result, 100.0, None, None)
        bucket = RegimeBucketStats(MarketRegime.BULL, 1, 100.0, None, None, 1, 1.0, 1.0, 1, 0.0)
        comparison = RegimeComparison(100.0, 100.0, 0.0, 0.0, (RegimeEquityPoint(date(2021, 1, 1), 100.0),))
        outcome = RegimeEvaluationResult((observation,), (bucket,), 0, 0.0, 0, 0.0, comparison, comparison)

        self.assertTrue(hasattr(outcome, "__slots__"))
        with self.assertRaises(FrozenInstanceError):
            observation.spy_adjusted_close = 101.0

    def test_evaluates_each_eligible_day_without_future_bars_affecting_prior_result(self) -> None:
        base = make_bars(255)
        qqq = [
            PriceBar("QQQ", bar.trading_date, bar.open, bar.high, bar.low, bar.close, bar.adjusted_close, bar.volume)
            for bar in base
        ]
        future_changed = base + [
            PriceBar("SPY", base[-1].trading_date + timedelta(days=index), 10_000.0, 10_000.0, 10_000.0, 10_000.0, 10_000.0, 1_000_000)
            for index in range(1, 8)
        ]

        selector = lambda as_of, visible: (
            MarketRegime.BEAR if max(bar.adjusted_close for bar in visible) >= 10_000.0 else MarketRegime.BULL,
            0.0,
        )
        base_engine = RecordingEngine(selector)
        changed_engine = RecordingEngine(selector)

        base_result = evaluate_regime_history(base, qqq_bars=qqq, engine=base_engine)
        changed_result = evaluate_regime_history(future_changed, qqq_bars=qqq, engine=changed_engine)

        self.assertEqual(len(base_engine.calls), len(base) - 251)
        self.assertEqual(base_engine.calls[0][0], base[251].trading_date)
        self.assertEqual(base_result.observations[0].result.regime, MarketRegime.BULL)
        self.assertEqual(changed_result.observations[0].result.regime, MarketRegime.BULL)
        self.assertEqual(
            [observation.trading_date for observation in base_result.observations],
            [bar.trading_date for bar in base[251:]],
        )

    def test_future_qqq_availability_and_validity_cannot_change_earlier_results(self) -> None:
        spy = make_bars(255)
        qqq = [
            PriceBar(
                "QQQ",
                bar.trading_date,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.adjusted_close,
                bar.volume,
            )
            for bar in spy
        ]
        future_index = 253
        future_date = spy[future_index].trading_date

        def future_bar() -> PriceBar:
            return PriceBar("QQQ", future_date, 400.0, 400.0, 400.0, 400.0, 400.0, 1_000_000)

        nan_future = future_bar()
        object.__setattr__(nan_future, "adjusted_close", float("nan"))
        malformed_future = future_bar()
        object.__setattr__(malformed_future, "adjusted_close", "not-a-number")
        wrong_symbol = future_bar()
        object.__setattr__(wrong_symbol, "symbol", "SPY")
        missing_value = object.__new__(PriceBar)
        for field, value in (
            ("symbol", "QQQ"),
            ("trading_date", future_date),
            ("open", 400.0),
            ("high", 400.0),
            ("low", 400.0),
            ("close", 400.0),
            ("volume", 1_000_000),
        ):
            object.__setattr__(missing_value, field, value)

        expected = evaluate_regime_history(spy, qqq_bars=qqq)
        cases = (
            ("missing future observation", qqq[:future_index] + qqq[future_index + 1 :], False),
            ("future NaN", qqq[:future_index] + [nan_future] + qqq[future_index + 1 :], True),
            (
                "future malformed value",
                qqq[:future_index] + [malformed_future] + qqq[future_index + 1 :],
                True,
            ),
            (
                "future missing value",
                qqq[:future_index] + [missing_value] + qqq[future_index + 1 :],
                True,
            ),
            (
                "future wrong symbol",
                qqq[:future_index] + [wrong_symbol] + qqq[future_index + 1 :],
                True,
            ),
            ("future duplicate date", qqq + [future_bar()], True),
        )

        expected_earlier = tuple(
            observation for observation in expected.observations if observation.trading_date < future_date
        )
        for label, changed_qqq, becomes_unavailable in cases:
            with self.subTest(case=label):
                changed = evaluate_regime_history(spy, qqq_bars=changed_qqq)
                changed_earlier = tuple(
                    observation
                    for observation in changed.observations
                    if observation.trading_date < future_date
                )
                self.assertEqual(changed_earlier, expected_earlier)
                if becomes_unavailable:
                    affected = next(
                        observation
                        for observation in changed.observations
                        if observation.trading_date == future_date
                    )
                    self.assertIs(
                        affected.result.confidence_evidence.qqq_status,
                        ConfirmationStatus.UNAVAILABLE,
                    )

    def test_preflights_mandatory_spy_history_before_iteration(self) -> None:
        malformed_date = make_bars(252)
        object.__setattr__(malformed_date[0], "trading_date", "not-a-date")
        wrong_symbol = make_bars(252)
        object.__setattr__(wrong_symbol[0], "symbol", "QQQ")
        duplicate_date = make_bars(252)
        object.__setattr__(duplicate_date[1], "trading_date", duplicate_date[0].trading_date)
        cases = (
            ([], InsufficientRegimeHistoryError, "Insufficient SPY history for regime evaluation."),
            (make_bars(251), InsufficientRegimeHistoryError, "Insufficient SPY history for regime evaluation."),
            (malformed_date, InvalidRegimeDataError, "Invalid market regime data."),
            (wrong_symbol, InvalidRegimeDataError, "Invalid market regime data."),
            (duplicate_date, InvalidRegimeDataError, "Invalid market regime data."),
        )

        for bars, error_type, expected_message in cases:
            with self.subTest(error=error_type.__name__, bars=len(bars)):
                engine = RecordingEngine()
                with self.assertRaises(error_type) as raised:
                    evaluate_regime_history(bars, engine=engine)
                self.assertEqual(str(raised.exception), expected_message)
                self.assertEqual(engine.calls, [])

    def test_malformed_optional_qqq_degrades_to_unavailable(self) -> None:
        spy = make_bars(253)
        malformed_qqq = [
            PriceBar(
                "QQQ",
                bar.trading_date,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.adjusted_close,
                bar.volume,
            )
            for bar in spy
        ]
        object.__setattr__(malformed_qqq[0], "trading_date", "not-a-date")
        engine = RecordingEngine()

        result = evaluate_regime_history(spy, qqq_bars=malformed_qqq, engine=engine)

        self.assertEqual(len(result.observations), 2)
        self.assertEqual(len(engine.calls), 2)
        self.assertTrue(all(qqq_history is None for _, _, qqq_history in engine.calls))

    def test_bucket_metrics_use_complete_horizons_and_contiguous_episodes(self) -> None:
        regimes = (
            [MarketRegime.BULL] * 15
            + [MarketRegime.CAUTIOUS_BULL] * 5
            + [MarketRegime.BULL] * 10
            + [MarketRegime.RISK_OFF] * 14
            + [MarketRegime.BEAR] * 20
        )
        prices = [100.0] * 315
        prices[251:315] = [200.0] * 15 + [100.0, 80.0, 90.0, 100.0, 100.0] + [100.0] * 44
        bars = make_bars(315, prices)
        by_date = {bar.trading_date: regimes[index - 251] for index, bar in enumerate(bars[251:], 251)}
        engine = RecordingEngine(lambda as_of, visible: (by_date[as_of], 1.0))

        result = evaluate_regime_history(bars, engine=engine)
        buckets = {bucket.regime: bucket for bucket in result.bucket_stats}

        self.assertEqual(sum(bucket.sessions for bucket in result.bucket_stats), len(result.observations))
        self.assertAlmostEqual(sum(bucket.percent_sessions for bucket in result.bucket_stats), 100.0)
        self.assertIsNone(result.observations[-1].forward_return_20)
        self.assertIsNone(result.observations[-1].forward_return_60)
        self.assertEqual(buckets[MarketRegime.BULL].sessions, 25)
        self.assertEqual(buckets[MarketRegime.BULL].episode_count, 2)
        self.assertEqual(buckets[MarketRegime.BULL].mean_duration, 12.5)
        self.assertEqual(buckets[MarketRegime.CAUTIOUS_BULL].max_duration, 5)
        self.assertAlmostEqual(buckets[MarketRegime.CAUTIOUS_BULL].worst_episode_drawdown, -0.2)
        self.assertAlmostEqual(buckets[MarketRegime.BULL].mean_forward_return_20, -0.3)
        self.assertAlmostEqual(buckets[MarketRegime.BULL].mean_forward_return_60, -0.5)
        self.assertAlmostEqual(
            buckets[MarketRegime.CAUTIOUS_BULL].mean_forward_return_20,
            0.07222222222222223,
        )
        self.assertIsNone(buckets[MarketRegime.CAUTIOUS_BULL].mean_forward_return_60)
        self.assertEqual(buckets[MarketRegime.RISK_OFF].mean_forward_return_20, 0.0)
        self.assertIsNone(buckets[MarketRegime.RISK_OFF].mean_forward_return_60)
        self.assertIsNone(buckets[MarketRegime.BEAR].mean_forward_return_20)
        self.assertIsNone(buckets[MarketRegime.BEAR].mean_forward_return_60)
        self.assertEqual(result.whipsaw_count, 1)
        self.assertAlmostEqual(result.whipsaw_rate, 0.25)
        self.assertEqual(result.transition_count, 4)
        self.assertAlmostEqual(result.annualized_transitions, 4 / 64 * 252)
        self.assertEqual(set(buckets), set(MarketRegime))

    def test_zero_session_regimes_are_retained_in_bucket_stats(self) -> None:
        bars = make_bars(253)
        result = evaluate_regime_history(bars, engine=RecordingEngine())

        buckets = {bucket.regime: bucket for bucket in result.bucket_stats}
        self.assertEqual(len(buckets), 4)
        self.assertEqual(buckets[MarketRegime.BEAR].sessions, 0)
        self.assertIsNone(buckets[MarketRegime.BEAR].mean_forward_return_20)

    def test_comparison_uses_prior_day_exposure_costs_and_independent_drawdowns(self) -> None:
        prices = [100.0] * 256
        prices[251:] = [100.0, 110.0, 99.0, 99.0, 80.0]
        bars = make_bars(256, prices)
        exposures = [1.0, 0.3, 0.0, 0.0, 0.0]
        engine = RecordingEngine(
            lambda as_of, visible: (MarketRegime.BULL, exposures[len(visible) - 252])
        )

        result = evaluate_regime_history(
            bars,
            engine=engine,
            initial_capital=100_000.0,
            transaction_cost_bps=100.0,
        )

        buy_and_hold = result.buy_and_hold
        capped = result.regime_capped
        self.assertEqual(buy_and_hold.equity_curve[0], RegimeEquityPoint(bars[251].trading_date, 100_000.0))
        self.assertEqual(capped.equity_curve[0], buy_and_hold.equity_curve[0])
        self.assertAlmostEqual(capped.equity_curve[1].value, 108_900.0)
        self.assertAlmostEqual(capped.equity_curve[2].value, 104_893.569)
        self.assertAlmostEqual(capped.equity_curve[3].value, 104_578.888293)
        self.assertAlmostEqual(capped.equity_curve[4].value, capped.equity_curve[3].value)
        self.assertAlmostEqual(capped.transaction_cost, 2_076.980707)
        self.assertAlmostEqual(buy_and_hold.max_drawdown, 80_000.0 / 110_000.0 - 1.0)
        self.assertAlmostEqual(capped.max_drawdown, 104_578.888293 / 108_900.0 - 1.0)

    def test_rejects_invalid_numeric_inputs_and_exposes_fixed_windows(self) -> None:
        bars = make_bars(252)
        for kwargs in (
            {"initial_capital": True},
            {"initial_capital": 0.0},
            {"transaction_cost_bps": True},
            {"transaction_cost_bps": -0.1},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    evaluate_regime_history(bars, engine=RecordingEngine(), **kwargs)

        self.assertEqual(
            HISTORICAL_REGIME_WINDOWS["2008 financial crisis"],
            (date(2007, 10, 1), date(2009, 6, 30)),
        )
        with self.assertRaises(TypeError):
            HISTORICAL_REGIME_WINDOWS["new"] = (date(2026, 1, 1), date(2026, 1, 2))


if __name__ == "__main__":
    unittest.main()
