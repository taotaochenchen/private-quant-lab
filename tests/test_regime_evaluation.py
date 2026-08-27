import ast
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta
import inspect
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.backtest.regime_evaluation import (
    EVALUATION_TRANSACTION_COST_BPS,
    EvaluationAvailability,
    EvaluationPoint,
    EvaluationStrategy,
    HISTORICAL_REGIME_WINDOWS,
    InvalidEvaluationDataError,
    RegimeBucketStats,
    RegimeComparison,
    RegimeEquityPoint,
    RegimeEvaluationResult,
    RegimeObservation,
    StrategyScenarioResult,
    _PriceInterval,
    _align_evaluation_history,
    _historical_window_result,
    _performance_metrics,
    _simulate_intervals,
    _target_exposures,
    evaluate_regime_history,
    evaluate_regime_v1_1,
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


def make_symbol_bars(
    symbol: str,
    dates: list[date],
    prices: list[float] | None = None,
) -> list[PriceBar]:
    closes = prices or [100.0 + index for index in range(len(dates))]
    return [
        PriceBar(symbol, day, close, close, close, close, close, 1_000_000)
        for day, close in zip(dates, closes)
    ]


def replace_field(bar: PriceBar, field: str, value: object) -> PriceBar:
    changed = object.__new__(PriceBar)
    for name in (
        "symbol", "trading_date", "open", "high", "low", "close",
        "adjusted_close", "volume",
    ):
        object.__setattr__(changed, name, value if name == field else getattr(bar, name))
    return changed


def without_field(bar: PriceBar, omitted: str) -> PriceBar:
    changed = object.__new__(PriceBar)
    for name in (
        "symbol", "trading_date", "open", "high", "low", "close",
        "adjusted_close", "volume",
    ):
        if name != omitted:
            object.__setattr__(changed, name, getattr(bar, name))
    return changed


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

    def test_complete_historical_evaluation_is_deterministic(self) -> None:
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

        first = evaluate_regime_history(spy, qqq_bars=qqq)
        second = evaluate_regime_history(spy, qqq_bars=qqq)

        self.assertEqual(first, second)

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
        missing_symbol = object.__new__(PriceBar)
        for field, value in (
            ("trading_date", future_date),
            ("open", 400.0),
            ("high", 400.0),
            ("low", 400.0),
            ("close", 400.0),
            ("adjusted_close", 400.0),
            ("volume", 1_000_000),
        ):
            object.__setattr__(missing_symbol, field, value)
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
        date_subclass_future = future_bar()

        class TradingDate(date):
            pass

        object.__setattr__(
            date_subclass_future,
            "trading_date",
            TradingDate(future_date.year, future_date.month, future_date.day),
        )
        unhashable_date_future = future_bar()

        class UnhashableDate(date):
            __hash__ = None

        object.__setattr__(
            unhashable_date_future,
            "trading_date",
            UnhashableDate(future_date.year, future_date.month, future_date.day),
        )
        explosive_date_future = future_bar()

        class ExplosiveDate(date):
            def __lt__(self, other):
                raise RuntimeError("comparison must not run")

            def __le__(self, other):
                raise RuntimeError("comparison must not run")

        object.__setattr__(
            explosive_date_future,
            "trading_date",
            ExplosiveDate(future_date.year, future_date.month, future_date.day),
        )
        huge_value_future = future_bar()
        object.__setattr__(huge_value_future, "adjusted_close", 10**10_000)

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
            (
                "future missing symbol",
                qqq[:future_index] + [missing_symbol] + qqq[future_index + 1 :],
                True,
            ),
            ("future duplicate date", qqq + [future_bar()], True),
            (
                "future date subclass",
                qqq[:future_index] + [date_subclass_future] + qqq[future_index + 1 :],
                False,
            ),
            (
                "future unhashable date subclass",
                qqq[:future_index] + [unhashable_date_future] + qqq[future_index + 1 :],
                False,
            ),
            (
                "future date subclass with explosive comparison",
                qqq[:future_index] + [explosive_date_future] + qqq[future_index + 1 :],
                False,
            ),
            (
                "future huge numeric value",
                qqq[:future_index] + [huge_value_future] + qqq[future_index + 1 :],
                True,
            ),
        )

        self.assertTrue(expected.observations)
        self.assertTrue(
            all(
                observation.result.confidence_evidence.qqq_status
                is ConfirmationStatus.CONFIRMS_POSITIVE
                for observation in expected.observations
            )
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
                    affected = tuple(
                        observation
                        for observation in changed.observations
                        if observation.trading_date >= future_date
                    )
                    self.assertTrue(affected)
                    self.assertTrue(
                        all(
                            observation.result.confidence_evidence.qqq_status
                            is ConfirmationStatus.UNAVAILABLE
                            for observation in affected
                        )
                    )
                    expected_by_date = {
                        observation.trading_date: observation for observation in expected.observations
                    }
                    for observation in affected:
                        baseline = expected_by_date[observation.trading_date]
                        self.assertIs(observation.result.regime, baseline.result.regime)
                        self.assertEqual(observation.result.score, baseline.result.score)
                        self.assertEqual(
                            observation.result.maximum_long_exposure,
                            baseline.result.maximum_long_exposure,
                        )
                else:
                    self.assertEqual(changed, expected)

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
        malformed_date = list(qqq)
        object.__setattr__(malformed_date[0], "trading_date", "not-a-date")
        datetime_date = list(qqq)
        object.__setattr__(datetime_date[0], "trading_date", datetime(2020, 1, 1))
        missing_date_bar = object.__new__(PriceBar)
        for field, value in (
            ("symbol", "QQQ"),
            ("open", 100.0),
            ("high", 100.0),
            ("low", 100.0),
            ("close", 100.0),
            ("adjusted_close", 100.0),
            ("volume", 1_000_000),
        ):
            object.__setattr__(missing_date_bar, field, value)
        missing_date = [missing_date_bar, *qqq[1:]]

        for label, malformed_qqq in (
            ("malformed date", malformed_date),
            ("datetime", datetime_date),
            ("missing date", missing_date),
        ):
            with self.subTest(case=label):
                result = evaluate_regime_history(spy, qqq_bars=malformed_qqq)
                self.assertEqual(len(result.observations), 2)
                self.assertTrue(
                    all(
                        observation.result.confidence_evidence.qqq_status
                        is ConfirmationStatus.UNAVAILABLE
                        for observation in result.observations
                    )
                )

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


class RegimeEvaluationV11ContractTests(unittest.TestCase):
    def test_evaluation_point_has_explicit_interval_dates_and_is_immutable(self) -> None:
        point = EvaluationPoint(
            signal_date=date(2024, 1, 2),
            return_end_date=date(2024, 1, 3),
            starting_value=100.0,
            ending_value=101.0,
            target_spy_exposure=1.0,
            spy_return=0.01,
            residual_cash_return=0.0,
            net_return=0.01,
            exposure_change=1.0,
            transaction_cost=0.0,
        )

        self.assertFalse(hasattr(point, "trading_date"))
        self.assertEqual(point.signal_date, date(2024, 1, 2))
        self.assertEqual(point.return_end_date, date(2024, 1, 3))
        with self.assertRaises(FrozenInstanceError):
            point.ending_value = 102.0

    def test_v11_constants_and_strategy_names_are_fixed(self) -> None:
        self.assertEqual(EVALUATION_TRANSACTION_COST_BPS, (0.0, 2.0, 5.0, 10.0))
        self.assertEqual(
            tuple(strategy.value for strategy in EvaluationStrategy),
            (
                "spy_buy_and_hold",
                "trend_200",
                "regime_v1_zero_yield_cash",
                "regime_v1_bil_cash_proxy",
            ),
        )


class RegimeEvaluationV11AlignmentTests(unittest.TestCase):
    def test_bil_late_start_truncates_to_one_exact_common_interval_sequence(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(260)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates[254:])

        aligned = _align_evaluation_history(spy, bil)

        self.assertEqual(aligned.intervals[0].signal_date, dates[254])
        self.assertEqual(aligned.intervals[0].return_end_date, dates[255])
        self.assertEqual(aligned.intervals[-1].return_end_date, dates[-1])
        self.assertEqual(
            tuple((item.signal_date, item.return_end_date) for item in aligned.intervals),
            tuple(zip(dates[254:-1], dates[255:])),
        )

    def test_missing_internal_bil_date_fails_instead_of_intersecting_it_away(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(258)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates[251:254] + dates[255:])

        with self.assertRaisesRegex(
            InvalidEvaluationDataError,
            "BIL history is missing an active SPY trading date",
        ):
            _align_evaluation_history(spy, bil)

    def test_explicit_start_and_end_select_complete_interval_boundaries(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(260)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)

        aligned = _align_evaluation_history(
            spy,
            bil,
            evaluation_start=dates[253],
            evaluation_end=dates[257],
        )

        self.assertEqual(
            tuple((item.signal_date, item.return_end_date) for item in aligned.intervals),
            tuple(zip(dates[253:257], dates[254:258])),
        )

    def test_future_invalid_bil_content_cannot_change_earlier_alignment(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(260)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)
        cutoff = dates[257]
        baseline = _align_evaluation_history(spy, bil, evaluation_end=cutoff)

        for field, value in (
            ("adjusted_close", float("nan")),
            ("adjusted_close", float("inf")),
            ("adjusted_close", 0.0),
            ("adjusted_close", -1.0),
            ("adjusted_close", "malformed"),
            ("symbol", "SPY"),
        ):
            with self.subTest(field=field, value=value):
                changed = bil[:-1] + [replace_field(bil[-1], field, value)]
                self.assertEqual(
                    _align_evaluation_history(spy, changed, evaluation_end=cutoff),
                    baseline,
                )
        self.assertEqual(
            _align_evaluation_history(
                spy,
                bil[:-1] + [without_field(bil[-1], "adjusted_close")],
                evaluation_end=cutoff,
            ),
            baseline,
        )
        self.assertEqual(
            _align_evaluation_history(spy, bil + [bil[-1]], evaluation_end=cutoff),
            baseline,
        )

    def test_future_invalid_spy_content_cannot_change_earlier_alignment(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(260)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)
        cutoff = dates[257]
        baseline = _align_evaluation_history(spy, bil, evaluation_end=cutoff)

        for field, value in (
            ("adjusted_close", float("nan")),
            ("adjusted_close", float("inf")),
            ("adjusted_close", 0.0),
            ("adjusted_close", -1.0),
            ("adjusted_close", "malformed"),
            ("symbol", "QQQ"),
        ):
            with self.subTest(field=field, value=value):
                changed = spy[:-1] + [replace_field(spy[-1], field, value)]
                self.assertEqual(
                    _align_evaluation_history(changed, bil, evaluation_end=cutoff),
                    baseline,
                )
        self.assertEqual(
            _align_evaluation_history(
                spy[:-1] + [without_field(spy[-1], "adjusted_close")],
                bil,
                evaluation_end=cutoff,
            ),
            baseline,
        )

    def test_invalid_active_bil_values_fail_with_fixed_message(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(258)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)

        for value in (float("nan"), float("inf"), 0.0, -1.0, "malformed", 10 ** 1000):
            with self.subTest(value=value), self.assertRaisesRegex(
                InvalidEvaluationDataError,
                "BIL adjusted close must be finite and positive",
            ):
                changed = bil[:253] + [replace_field(bil[253], "adjusted_close", value)] + bil[254:]
                _align_evaluation_history(spy, changed)
        with self.assertRaisesRegex(
            InvalidEvaluationDataError,
            "BIL adjusted close must be finite and positive",
        ):
            changed = bil[:253] + [without_field(bil[253], "adjusted_close")] + bil[254:]
            _align_evaluation_history(spy, changed)

    def test_invalid_active_spy_value_fails_at_the_v11_boundary(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(258)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)
        changed = spy[:253] + [replace_field(spy[253], "adjusted_close", float("nan"))] + spy[254:]

        with self.assertRaisesRegex(
            InvalidEvaluationDataError,
            "SPY adjusted close must be finite and positive",
        ):
            _align_evaluation_history(changed, bil)

    def test_missing_or_unparseable_date_fails_because_temporal_position_is_unknown(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(258)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)
        changed = bil[:-1] + [replace_field(bil[-1], "trading_date", "not-a-date")]

        with self.assertRaisesRegex(InvalidEvaluationDataError, "BIL trading date is invalid"):
            _align_evaluation_history(spy, changed, evaluation_end=dates[-2])

    def test_active_duplicate_dates_fail_with_fixed_messages(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(258)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)
        duplicate_spy = spy + [spy[-1]]
        duplicate_bil = bil + [bil[-1]]

        with self.assertRaisesRegex(InvalidEvaluationDataError, "SPY has duplicate active trading dates"):
            _align_evaluation_history(duplicate_spy, bil)
        with self.assertRaisesRegex(InvalidEvaluationDataError, "BIL has duplicate active trading dates"):
            _align_evaluation_history(spy, duplicate_bil)

    def test_active_wrong_symbols_fail_with_fixed_messages(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(258)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)
        wrong_spy = spy[:253] + [replace_field(spy[253], "symbol", "QQQ")] + spy[254:]
        wrong_bil = bil[:253] + [replace_field(bil[253], "symbol", "SPY")] + bil[254:]

        with self.assertRaisesRegex(InvalidEvaluationDataError, "SPY history contains the wrong symbol"):
            _align_evaluation_history(wrong_spy, bil)
        with self.assertRaisesRegex(InvalidEvaluationDataError, "BIL history contains the wrong symbol"):
            _align_evaluation_history(spy, wrong_bil)


class RegimeEvaluationV11ExposureTests(unittest.TestCase):
    def test_target_exposures_use_signal_date_data_and_preserve_v1_mapping(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(255)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)
        qqq = make_symbol_bars("QQQ", dates)
        aligned = _align_evaluation_history(spy, bil)
        expected = (1.0, 0.7, 0.3)
        engine = RecordingEngine(
            lambda as_of, visible: (
                (MarketRegime.BULL, 1.0),
                (MarketRegime.CAUTIOUS_BULL, 0.7),
                (MarketRegime.RISK_OFF, 0.3),
            )[dates[251:254].index(as_of)]
        )

        exposures = _target_exposures(aligned, qqq_bars=qqq, engine=engine)

        self.assertEqual(exposures[EvaluationStrategy.SPY_BUY_AND_HOLD], (1.0, 1.0, 1.0))
        self.assertEqual(exposures[EvaluationStrategy.REGIME_ZERO_YIELD_CASH], expected)
        self.assertEqual(exposures[EvaluationStrategy.REGIME_BIL_CASH_PROXY], expected)
        self.assertEqual(tuple(call[0] for call in engine.calls), tuple(dates[251:254]))
        for signal_date, visible, visible_qqq in engine.calls:
            self.assertLessEqual(max(bar.trading_date for bar in visible), signal_date)
            self.assertIsNotNone(visible_qqq)
            self.assertLessEqual(max(bar.trading_date for bar in visible_qqq), signal_date)

    def test_target_exposures_uses_canonical_dates_for_active_unhashable_date_subclasses(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(255)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)

        class UnhashableDate(date):
            __hash__ = None

        spy[252] = replace_field(
            spy[252],
            "trading_date",
            UnhashableDate(dates[252].year, dates[252].month, dates[252].day),
        )
        aligned = _align_evaluation_history(spy, bil)

        exposures = _target_exposures(aligned, engine=RecordingEngine())

        self.assertEqual(exposures[EvaluationStrategy.SPY_BUY_AND_HOLD], (1.0, 1.0, 1.0))

    def test_trend_signal_uses_200_closes_through_signal_date_and_equality_is_risk_on(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(254)]
        prices = [100.0] * 252 + [90.0, 90.0]
        spy = make_symbol_bars("SPY", dates, prices)
        bil = make_symbol_bars("BIL", dates)
        aligned = _align_evaluation_history(spy, bil)

        exposures = _target_exposures(aligned, engine=RecordingEngine())

        self.assertEqual(exposures[EvaluationStrategy.TREND_200], (1.0, 0.0))


class RegimeEvaluationV11SimulationTests(unittest.TestCase):
    def test_first_point_charges_opening_cost_at_d0_and_dates_ending_value_d1(self) -> None:
        interval = _PriceInterval(date(2024, 1, 2), date(2024, 1, 3), 0.10, 0.01)

        points = _simulate_intervals(
            (interval,),
            (1.0,),
            strategy=EvaluationStrategy.SPY_BUY_AND_HOLD,
            initial_capital=100.0,
            transaction_cost_bps=10.0,
        )

        point = points[0]
        self.assertEqual(point.signal_date, date(2024, 1, 2))
        self.assertEqual(point.return_end_date, date(2024, 1, 3))
        self.assertAlmostEqual(point.starting_value, 100.0)
        self.assertAlmostEqual(point.exposure_change, 1.0)
        self.assertAlmostEqual(point.transaction_cost, 0.1)
        self.assertAlmostEqual(point.ending_value, 109.89)
        self.assertAlmostEqual(point.net_return, 0.0989)

    def test_bil_proxy_applies_only_to_residual_weight_without_second_cost_leg(self) -> None:
        interval = _PriceInterval(date(2024, 1, 2), date(2024, 1, 3), 0.10, 0.01)

        zero_cash = _simulate_intervals(
            (interval,),
            (0.3,),
            strategy=EvaluationStrategy.REGIME_ZERO_YIELD_CASH,
            initial_capital=100.0,
            transaction_cost_bps=0.0,
        )[0]
        bil_cash = _simulate_intervals(
            (interval,),
            (0.3,),
            strategy=EvaluationStrategy.REGIME_BIL_CASH_PROXY,
            initial_capital=100.0,
            transaction_cost_bps=0.0,
        )[0]

        self.assertAlmostEqual(zero_cash.ending_value, 103.0)
        self.assertAlmostEqual(zero_cash.residual_cash_return, 0.0)
        self.assertAlmostEqual(bil_cash.ending_value, 103.7)
        self.assertAlmostEqual(bil_cash.residual_cash_return, 0.01)
        self.assertEqual(bil_cash.transaction_cost, 0.0)

    def test_unchanged_target_has_no_new_cost_and_intervals_chain_exactly(self) -> None:
        intervals = (
            _PriceInterval(date(2024, 1, 2), date(2024, 1, 3), 0.01, 0.001),
            _PriceInterval(date(2024, 1, 3), date(2024, 1, 4), 0.02, 0.001),
        )

        points = _simulate_intervals(
            intervals,
            (0.7, 0.7),
            strategy=EvaluationStrategy.REGIME_ZERO_YIELD_CASH,
            initial_capital=100.0,
            transaction_cost_bps=5.0,
        )

        self.assertGreater(points[0].transaction_cost, 0.0)
        self.assertEqual(points[1].transaction_cost, 0.0)
        self.assertEqual(points[0].return_end_date, points[1].signal_date)
        self.assertEqual(points[0].ending_value, points[1].starting_value)

    def test_invalid_capital_and_cost_inputs_fail_closed(self) -> None:
        interval = _PriceInterval(date(2024, 1, 2), date(2024, 1, 3), 0.01, 0.001)
        for capital in (True, 0.0, -1.0, float("nan"), float("inf")):
            with self.subTest(capital=capital), self.assertRaises(ValueError):
                _simulate_intervals(
                    (interval,),
                    (1.0,),
                    strategy=EvaluationStrategy.SPY_BUY_AND_HOLD,
                    initial_capital=capital,
                    transaction_cost_bps=0.0,
                )
        for cost in (True, -1.0, float("nan"), float("inf")):
            with self.subTest(cost=cost), self.assertRaises(ValueError):
                _simulate_intervals(
                    (interval,),
                    (1.0,),
                    strategy=EvaluationStrategy.SPY_BUY_AND_HOLD,
                    initial_capital=100.0,
                    transaction_cost_bps=cost,
                )


def metric_fixture_points() -> tuple[EvaluationPoint, ...]:
    return (
        EvaluationPoint(
            date(2024, 1, 1), date(2024, 1, 2),
            100.0, 110.0, 0.3, 1.0 / 3.0, 0.0, 0.10, 0.3, 0.0,
        ),
        EvaluationPoint(
            date(2024, 1, 2), date(2024, 1, 3),
            110.0, 99.0, 0.7, -1.0 / 7.0, 0.0, -0.10, 0.4, 0.0,
        ),
    )


class RegimeEvaluationV11PerformanceMetricTests(unittest.TestCase):
    def test_metrics_match_deterministic_two_interval_fixture(self) -> None:
        metrics = _performance_metrics(
            100.0,
            metric_fixture_points(),
            applicable_exposures=(0.0, 0.3, 0.7, 1.0),
        )

        expected_cagr = (99.0 / 100.0) ** (365.25 / 2.0) - 1.0
        self.assertEqual(metrics.initial_capital, 100.0)
        self.assertEqual(metrics.final_value, 99.0)
        self.assertAlmostEqual(metrics.total_return, -0.01)
        self.assertAlmostEqual(metrics.cagr, expected_cagr)
        self.assertAlmostEqual(metrics.max_drawdown, -0.10)
        self.assertAlmostEqual(
            metrics.annualized_volatility,
            0.1 * math.sqrt(252.0),
        )
        self.assertAlmostEqual(metrics.sharpe, 0.0)
        self.assertAlmostEqual(metrics.sortino, 0.0)
        self.assertAlmostEqual(metrics.calmar, expected_cagr / 0.10)
        self.assertEqual(metrics.total_transaction_cost, 0.0)
        self.assertAlmostEqual(metrics.annualized_turnover, 88.8)
        self.assertEqual(metrics.exposure_changes, 2)
        self.assertAlmostEqual(metrics.average_spy_exposure, 0.5)
        self.assertEqual(
            tuple(
                (bucket.exposure, bucket.percent_sessions)
                for bucket in metrics.exposure_buckets
            ),
            ((0.0, 0.0), (0.3, 50.0), (0.7, 50.0), (1.0, 0.0)),
        )
        self.assertAlmostEqual(
            sum(bucket.percent_sessions for bucket in metrics.exposure_buckets),
            100.0,
        )

    def test_zero_denominators_are_none_instead_of_invented_ratios(self) -> None:
        point = EvaluationPoint(
            date(2024, 1, 2), date(2024, 1, 3),
            100.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        )

        metrics = _performance_metrics(
            100.0,
            (point,),
            applicable_exposures=(0.0, 1.0),
        )

        self.assertIsNone(metrics.annualized_volatility)
        self.assertIsNone(metrics.sharpe)
        self.assertIsNone(metrics.sortino)
        self.assertIsNone(metrics.calmar)

    def test_sharpe_and_sortino_match_mixed_sign_population_fixture(self) -> None:
        returns = (0.02, -0.01, 0.01)
        points = (
            EvaluationPoint(
                date(2024, 1, 1), date(2024, 1, 2),
                100.0, 102.0, 1.0, 0.02, 0.0, returns[0], 1.0, 0.0,
            ),
            EvaluationPoint(
                date(2024, 1, 2), date(2024, 1, 3),
                102.0, 100.98, 1.0, -0.01, 0.0, returns[1], 0.0, 0.0,
            ),
            EvaluationPoint(
                date(2024, 1, 3), date(2024, 1, 4),
                100.98, 101.9898, 1.0, 0.01, 0.0, returns[2], 0.0, 0.0,
            ),
        )

        metrics = _performance_metrics(
            100.0,
            points,
            applicable_exposures=(1.0,),
        )

        mean_return = sum(returns) / len(returns)
        population_deviation = math.sqrt(
            sum((value - mean_return) ** 2 for value in returns) / len(returns)
        )
        downside_deviation = math.sqrt(
            sum(min(value, 0.0) ** 2 for value in returns) / len(returns)
        )
        self.assertAlmostEqual(
            metrics.sharpe,
            mean_return / population_deviation * math.sqrt(252.0),
        )
        self.assertAlmostEqual(
            metrics.sortino,
            mean_return / downside_deviation * math.sqrt(252.0),
        )

    def test_two_constant_returns_have_zero_volatility_and_undefined_ratios(self) -> None:
        points = (
            EvaluationPoint(
                date(2024, 1, 1), date(2024, 1, 2),
                100.0, 101.0, 1.0, 0.01, 0.0, 0.01, 1.0, 0.0,
            ),
            EvaluationPoint(
                date(2024, 1, 2), date(2024, 1, 3),
                101.0, 102.01, 1.0, 0.01, 0.0, 0.01, 0.0, 0.0,
            ),
        )

        metrics = _performance_metrics(
            100.0,
            points,
            applicable_exposures=(1.0,),
        )

        self.assertEqual(metrics.annualized_volatility, 0.0)
        self.assertIsNone(metrics.sharpe)
        self.assertIsNone(metrics.sortino)

    def test_total_transaction_cost_sums_nonzero_interval_costs(self) -> None:
        points = _simulate_intervals(
            (
                _PriceInterval(date(2024, 1, 1), date(2024, 1, 2), 0.10, 0.0),
                _PriceInterval(date(2024, 1, 2), date(2024, 1, 3), -0.05, 0.0),
            ),
            (0.3, 0.7),
            strategy=EvaluationStrategy.REGIME_ZERO_YIELD_CASH,
            initial_capital=100.0,
            transaction_cost_bps=10.0,
        )

        metrics = _performance_metrics(
            100.0,
            points,
            applicable_exposures=(0.0, 0.3, 0.7, 1.0),
        )

        self.assertGreater(points[0].transaction_cost, 0.0)
        self.assertGreater(points[1].transaction_cost, 0.0)
        self.assertAlmostEqual(metrics.total_transaction_cost, 0.07118764)

    def test_applicable_exposure_buckets_are_not_invented(self) -> None:
        buy_hold_point = EvaluationPoint(
            date(2024, 1, 1), date(2024, 1, 2),
            100.0, 101.0, 1.0, 0.01, 0.0, 0.01, 1.0, 0.0,
        )
        buy_hold = _performance_metrics(
            100.0,
            (buy_hold_point,),
            applicable_exposures=(1.0,),
        )
        trend = _performance_metrics(
            100.0,
            (
                EvaluationPoint(
                    date(2024, 1, 1), date(2024, 1, 2),
                    100.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                ),
                EvaluationPoint(
                    date(2024, 1, 2), date(2024, 1, 3),
                    100.0, 101.0, 1.0, 0.01, 0.0, 0.01, 1.0, 0.0,
                ),
            ),
            applicable_exposures=(0.0, 1.0),
        )

        self.assertEqual(
            tuple(bucket.exposure for bucket in buy_hold.exposure_buckets),
            (1.0,),
        )
        self.assertEqual(
            tuple(bucket.exposure for bucket in trend.exposure_buckets),
            (0.0, 1.0),
        )
        self.assertAlmostEqual(
            sum(bucket.percent_sessions for bucket in trend.exposure_buckets),
            100.0,
        )


def window_fixture_scenario() -> StrategyScenarioResult:
    first_included_spy_return = 121.0 / (110.0 - 1.10) - 1.0
    final_spy_return = (108.9 / (121.0 - 0.363) - 1.0) / 0.7
    points = _simulate_intervals(
        (
            _PriceInterval(
                date(2019, 12, 31), date(2020, 1, 2), 0.0, 0.10,
            ),
            _PriceInterval(
                date(2020, 1, 2), date(2020, 1, 3),
                first_included_spy_return, 0.0,
            ),
            _PriceInterval(
                date(2020, 1, 3), date(2020, 1, 6),
                final_spy_return, 0.0,
            ),
        ),
        (0.0, 1.0, 0.7),
        strategy=EvaluationStrategy.REGIME_BIL_CASH_PROXY,
        initial_capital=100.0,
        transaction_cost_bps=100.0,
    )
    return StrategyScenarioResult(
        strategy=EvaluationStrategy.REGIME_BIL_CASH_PROXY,
        transaction_cost_bps=100.0,
        first_signal_date=points[0].signal_date,
        final_return_end_date=points[-1].return_end_date,
        metrics=_performance_metrics(
            100.0,
            points,
            applicable_exposures=(0.0, 0.3, 0.7, 1.0),
        ),
        points=points,
    )


class RegimeEvaluationV11WindowTests(unittest.TestCase):
    def test_window_uses_complete_intervals_and_rebases_pre_cost_start_to_100(self) -> None:
        scenario = window_fixture_scenario()

        result = _historical_window_result(
            scenario,
            window_name="Calendar 2020",
            requested_start=date(2020, 1, 1),
            requested_end=date(2020, 12, 31),
        )

        self.assertIs(result.availability, EvaluationAvailability.AVAILABLE)
        self.assertEqual(result.effective_signal_date, date(2020, 1, 2))
        self.assertEqual(result.effective_return_end_date, date(2020, 1, 6))
        self.assertEqual(result.normalized_start_value, 100.0)
        self.assertAlmostEqual(scenario.points[1].transaction_cost, 1.10)
        self.assertAlmostEqual(
            result.normalized_end_value,
            scenario.points[-1].ending_value / 110.0 * 100.0,
        )
        self.assertAlmostEqual(
            result.transaction_cost,
            sum(point.transaction_cost for point in scenario.points[1:])
            / 110.0
            * 100.0,
        )
        self.assertEqual(
            result.exposure_changes,
            sum(point.exposure_change > 1e-12 for point in scenario.points[1:]),
        )
        self.assertAlmostEqual(result.strategy_return, 108.9 / 110.0 - 1.0)
        self.assertAlmostEqual(result.max_drawdown, 108.9 / 121.0 - 1.0)
        self.assertAlmostEqual(result.average_spy_exposure, 0.85)

    def test_window_does_not_include_interval_that_only_ends_inside_window(self) -> None:
        result = _historical_window_result(
            window_fixture_scenario(),
            window_name="Calendar 2020",
            requested_start=date(2020, 1, 1),
            requested_end=date(2020, 12, 31),
        )

        self.assertNotEqual(result.effective_signal_date, date(2019, 12, 31))
        self.assertEqual(result.interval_count, 2)

    def test_window_without_complete_interval_is_explicitly_unavailable(self) -> None:
        result = _historical_window_result(
            window_fixture_scenario(),
            window_name="Calendar 2022",
            requested_start=date(2022, 1, 1),
            requested_end=date(2022, 12, 31),
        )

        self.assertIs(result.availability, EvaluationAvailability.UNAVAILABLE)
        self.assertIsNone(result.effective_signal_date)
        self.assertIsNone(result.effective_return_end_date)
        self.assertEqual(result.interval_count, 0)
        self.assertIsNone(result.normalized_start_value)
        self.assertIsNone(result.normalized_end_value)
        self.assertIsNone(result.strategy_return)
        self.assertIsNone(result.max_drawdown)
        self.assertIsNone(result.exposure_changes)
        self.assertIsNone(result.average_spy_exposure)
        self.assertIsNone(result.transaction_cost)


class RegimeEvaluationV11IntegrationTests(unittest.TestCase):
    def test_all_strategies_and_costs_share_exact_interval_pairs(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(260)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars(
            "BIL",
            dates,
            [100.0 + index * 0.01 for index in range(260)],
        )

        result = evaluate_regime_v1_1(spy, bil, engine=RecordingEngine())

        self.assertEqual(len(result.scenarios), 16)
        self.assertEqual(
            {scenario.transaction_cost_bps for scenario in result.scenarios},
            {0.0, 2.0, 5.0, 10.0},
        )
        self.assertEqual(
            {scenario.strategy for scenario in result.scenarios},
            set(EvaluationStrategy),
        )
        for scenario in result.scenarios:
            self.assertEqual(
                tuple(
                    (point.signal_date, point.return_end_date)
                    for point in scenario.points
                ),
                result.common_intervals,
            )

        self.assertEqual(
            len(result.windows),
            16 * len(HISTORICAL_REGIME_WINDOWS),
        )
        for window_name in HISTORICAL_REGIME_WINDOWS:
            rows = [
                row for row in result.windows if row.window_name == window_name
            ]
            self.assertEqual(len(rows), 16)
            self.assertEqual(
                len(
                    {
                        (row.effective_signal_date, row.effective_return_end_date)
                        for row in rows
                    }
                ),
                1,
            )

    def test_repeated_evaluation_is_deterministic(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(260)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)

        first = evaluate_regime_v1_1(spy, bil, engine=RecordingEngine())
        second = evaluate_regime_v1_1(spy, bil, engine=RecordingEngine())

        self.assertEqual(first, second)

    def test_cost_sensitivity_changes_values_not_dates_or_exposure(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(260)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)
        result = evaluate_regime_v1_1(spy, bil, engine=RecordingEngine())
        buy_hold = [
            scenario
            for scenario in result.scenarios
            if scenario.strategy is EvaluationStrategy.SPY_BUY_AND_HOLD
        ]

        self.assertEqual(
            len(
                {
                    tuple(
                        (point.signal_date, point.return_end_date)
                        for point in scenario.points
                    )
                    for scenario in buy_hold
                }
            ),
            1,
        )
        self.assertEqual(
            len(
                {
                    tuple(point.target_spy_exposure for point in scenario.points)
                    for scenario in buy_hold
                }
            ),
            1,
        )
        self.assertGreater(
            buy_hold[0].metrics.final_value,
            buy_hold[-1].metrics.final_value,
        )


class RegimeEvaluationV11SourceSafetyTests(unittest.TestCase):
    def test_v11_source_has_no_ui_provider_broker_order_or_env_dependency(self) -> None:
        source_path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "private_quant"
            / "backtest"
            / "regime_evaluation.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        forbidden_import_prefixes = (
            "streamlit",
            "private_quant.broker",
            "ibapi",
            "dotenv",
        )
        for forbidden in forbidden_import_prefixes:
            with self.subTest(forbidden=forbidden):
                self.assertFalse(
                    any(
                        module == forbidden or module.startswith(f"{forbidden}.")
                        for module in imported_modules
                    )
                )

        referenced_names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        } | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        self.assertNotIn("placeOrder", referenced_names)
        self.assertNotIn("build_market_data_provider", referenced_names)
        self.assertFalse(
            any(
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and ".env" in node.value
                for node in ast.walk(tree)
            )
        )
        self.assertEqual(
            tuple(inspect.signature(evaluate_regime_v1_1).parameters),
            (
                "spy_bars",
                "bil_bars",
                "qqq_bars",
                "engine",
                "initial_capital",
                "evaluation_start",
                "evaluation_end",
            ),
        )


if __name__ == "__main__":
    unittest.main()
