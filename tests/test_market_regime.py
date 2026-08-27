import math
import copy
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import private_quant.risk as risk
from private_quant.data import PriceBar
from private_quant.risk.market_regime import (
    ConfirmationStatus,
    InsufficientRegimeHistoryError,
    InvalidRegimeDataError,
    MarketRegimeEngine,
    MarketRegime,
    RegimeComponent,
    RegimeConfidence,
    RegimeConfidenceEvidence,
    RegimeDataQuality,
    RegimeEngineError,
    RegimeMetric,
    RegimeResult,
    StaleRegimeDataError,
    StrategyPermission,
    _validated_history,
    regime_from_score,
    risk_mapping_for,
    score_drawdown,
    score_realized_volatility,
)


def make_bars(
    symbol: str = "SPY",
    *,
    count: int = 252,
    end: date = date(2026, 8, 26),
    start_price: float = 100.0,
    daily_return: float = 0.001,
) -> tuple[PriceBar, ...]:
    trading_days: list[date] = []
    day = end
    while len(trading_days) < count:
        if day.weekday() < 5:
            trading_days.append(day)
        day -= timedelta(days=1)
    trading_days.reverse()

    bars: list[PriceBar] = []
    price = start_price
    for trading_day in trading_days:
        price *= 1.0 + daily_return
        bars.append(
            PriceBar(
                symbol=symbol,
                trading_date=trading_day,
                open=price,
                high=price,
                low=price,
                close=price,
                adjusted_close=price,
                volume=1_000_000,
            )
        )
    return tuple(bars)


def make_return_bars(
    returns: tuple[float, ...],
    *,
    symbol: str = "SPY",
    end: date = date(2026, 8, 26),
) -> tuple[PriceBar, ...]:
    trading_days: list[date] = []
    day = end
    while len(trading_days) < len(returns):
        if day.weekday() < 5:
            trading_days.append(day)
        day -= timedelta(days=1)
    trading_days.reverse()
    price = 100.0
    bars: list[PriceBar] = []
    for trading_day, daily_return in zip(trading_days, returns):
        price *= 1.0 + daily_return
        bars.append(
            PriceBar(
                symbol=symbol,
                trading_date=trading_day,
                open=price,
                high=price,
                low=price,
                close=price,
                adjusted_close=price,
                volume=1_000_000,
            )
        )
    return tuple(bars)


class RegimeContractTests(unittest.TestCase):
    def test_enums_have_stable_string_values(self) -> None:
        self.assertEqual(MarketRegime.BULL.value, "BULL")
        self.assertEqual(MarketRegime.CAUTIOUS_BULL.value, "CAUTIOUS_BULL")
        self.assertEqual(MarketRegime.RISK_OFF.value, "RISK_OFF")
        self.assertEqual(MarketRegime.BEAR.value, "BEAR")
        self.assertEqual(RegimeConfidence.HIGH.value, "HIGH")
        self.assertEqual(RegimeConfidence.MEDIUM.value, "MEDIUM")
        self.assertEqual(RegimeConfidence.LOW.value, "LOW")
        self.assertEqual(StrategyPermission.NORMAL.value, "NORMAL")
        self.assertEqual(StrategyPermission.REDUCED.value, "REDUCED")
        self.assertEqual(StrategyPermission.DEFENSIVE.value, "DEFENSIVE")
        self.assertEqual(StrategyPermission.BLOCKED.value, "BLOCKED")
        self.assertEqual(ConfirmationStatus.CONFIRMS_POSITIVE.value, "CONFIRMS_POSITIVE")
        self.assertEqual(ConfirmationStatus.CONFIRMS_NEGATIVE.value, "CONFIRMS_NEGATIVE")
        self.assertEqual(ConfirmationStatus.MIXED.value, "MIXED")
        self.assertEqual(ConfirmationStatus.UNAVAILABLE.value, "UNAVAILABLE")

    def test_result_models_reject_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            RegimeMetric("", 1.0, "ratio", "reference")
        with self.assertRaises(ValueError):
            RegimeMetric("metric", math.nan, "ratio", "reference")
        with self.assertRaises(ValueError):
            RegimeComponent("component", 11, 10, (), "explanation")
        with self.assertRaises(ValueError):
            RegimeComponent("component", 1, 0, (), "explanation")
        with self.assertRaises(ValueError):
            RegimeComponent("component", 1, 10, (), "")
        with self.assertRaises(ValueError):
            RegimeConfidenceEvidence(-1, 0, ConfirmationStatus.UNAVAILABLE)
        with self.assertRaises(ValueError):
            RegimeConfidenceEvidence(1, 5, ConfirmationStatus.UNAVAILABLE)
        with self.assertRaises(ValueError):
            RegimeDataQuality(
                date(2026, 8, 26),
                date(2026, 8, 26),
                -1,
                252,
                252,
                True,
                ConfirmationStatus.UNAVAILABLE,
                (),
            )
        with self.assertRaises(ValueError):
            RegimeResult(
                date(2026, 8, 26),
                MarketRegime.BULL,
                101,
                RegimeConfidence.HIGH,
                RegimeConfidenceEvidence(10, 3, ConfirmationStatus.CONFIRMS_POSITIVE),
                1.0,
                StrategyPermission.NORMAL,
                (),
                (),
                RegimeDataQuality(
                    date(2026, 8, 26),
                    date(2026, 8, 26),
                    0,
                    252,
                    252,
                    True,
                    ConfirmationStatus.UNAVAILABLE,
                    (),
                ),
            )
        with self.assertRaises(ValueError):
            RegimeResult(
                date(2026, 8, 26),
                MarketRegime.BULL,
                10,
                RegimeConfidence.HIGH,
                RegimeConfidenceEvidence(10, 3, ConfirmationStatus.CONFIRMS_POSITIVE),
                1.1,
                StrategyPermission.NORMAL,
                (),
                (),
                RegimeDataQuality(
                    date(2026, 8, 26),
                    date(2026, 8, 26),
                    0,
                    252,
                    252,
                    True,
                    ConfirmationStatus.UNAVAILABLE,
                    (),
                ),
            )

    def test_result_models_are_frozen(self) -> None:
        metric = RegimeMetric("metric", 1.0, "ratio", "reference")
        with self.assertRaises(FrozenInstanceError):
            metric.value = 2.0

        component = RegimeComponent("component", 1, 10, (metric,), "explanation")
        with self.assertRaises(FrozenInstanceError):
            component.score = 2

        evidence = RegimeConfidenceEvidence(10, 3, ConfirmationStatus.UNAVAILABLE)
        with self.assertRaises(FrozenInstanceError):
            evidence.boundary_distance = 9

    def test_models_are_slotted(self) -> None:
        self.assertFalse(hasattr(RegimeMetric("m", 1.0, "u", "r"), "__dict__"))


class HistoryValidationTests(unittest.TestCase):
    def assert_fixed_message(self, error_type: type[Exception], bars: tuple[PriceBar, ...], **kwargs: object) -> None:
        with self.assertRaises(error_type) as context:
            _validated_history(bars, **kwargs)
        message = str(context.exception)
        self.assertTrue(message)
        self.assertNotIn(repr(bars), message)

    def test_requires_252_spy_observations(self) -> None:
        bars = make_bars(count=251)
        self.assert_fixed_message(
            InsufficientRegimeHistoryError,
            bars,
            symbol="SPY",
            as_of=date(2026, 8, 26),
            minimum_observations=252,
            enforce_staleness=True,
        )

    def test_empty_history_uses_same_fixed_error(self) -> None:
        first = make_bars(count=251)
        second = make_bars(count=0)
        with self.assertRaises(InsufficientRegimeHistoryError) as first_error:
            _validated_history(first, symbol="SPY", as_of=date(2026, 8, 26), minimum_observations=252, enforce_staleness=True)
        with self.assertRaises(InsufficientRegimeHistoryError) as second_error:
            _validated_history(second, symbol="SPY", as_of=date(2026, 8, 26), minimum_observations=252, enforce_staleness=True)
        self.assertEqual(str(first_error.exception), str(second_error.exception))

    def test_rejects_non_spy_symbol(self) -> None:
        self.assert_fixed_message(
            InvalidRegimeDataError,
            make_bars(symbol="QQQ"),
            symbol="SPY",
            as_of=date(2026, 8, 26),
            minimum_observations=252,
            enforce_staleness=True,
        )

    def test_rejects_duplicate_dates(self) -> None:
        bars = make_bars()
        self.assert_fixed_message(
            InvalidRegimeDataError,
            bars[:-1] + (bars[-2], bars[-1]),
            symbol="SPY",
            as_of=date(2026, 8, 26),
            minimum_observations=252,
            enforce_staleness=True,
        )

    def test_rejects_nonfinite_or_nonpositive_adjusted_close(self) -> None:
        bars = make_bars()
        for value in (math.nan, math.inf, 0.0, -1.0):
            with self.subTest(value=value):
                invalid = copy.copy(bars[-1])
                object.__setattr__(invalid, "adjusted_close", value)
                self.assert_fixed_message(
                    InvalidRegimeDataError,
                    bars[:-1] + (invalid,),
                    symbol="SPY",
                    as_of=date(2026, 8, 26),
                    minimum_observations=252,
                    enforce_staleness=True,
                )

    def test_rejects_large_gap_in_trailing_window(self) -> None:
        bars = list(make_bars(count=260))
        gap_bar = replace(bars[100], trading_date=bars[99].trading_date + timedelta(days=11))
        bars[100:109] = [gap_bar]
        self.assertEqual(len({bar.trading_date for bar in bars}), len(bars))
        self.assert_fixed_message(
            InvalidRegimeDataError,
            tuple(bars),
            symbol="SPY",
            as_of=date(2026, 8, 26),
            minimum_observations=252,
            enforce_staleness=True,
        )

    def test_filters_future_observations_before_validation(self) -> None:
        historical = make_bars()
        future = replace(historical[-1], trading_date=date(2026, 8, 27), symbol="QQQ")
        validated = _validated_history(
            historical + (future,),
            symbol="SPY",
            as_of=date(2026, 8, 26),
            minimum_observations=252,
            enforce_staleness=True,
        )
        self.assertEqual(len(validated), 252)
        self.assertEqual(validated[-1].trading_date, date(2026, 8, 26))

    def test_rejects_stale_latest_observation(self) -> None:
        bars = make_bars(end=date(2026, 8, 20))
        self.assert_fixed_message(
            StaleRegimeDataError,
            bars,
            symbol="SPY",
            as_of=date(2026, 8, 26),
            minimum_observations=252,
            enforce_staleness=True,
        )

    def test_can_disable_staleness_enforcement(self) -> None:
        bars = make_bars(end=date(2026, 8, 20))
        validated = _validated_history(
            bars,
            symbol="SPY",
            as_of=date(2026, 8, 26),
            minimum_observations=252,
            enforce_staleness=False,
        )
        self.assertEqual(len(validated), 252)


class RegimeScoringTests(unittest.TestCase):
    def test_public_risk_package_exports_engine_and_scoring_functions(self) -> None:
        self.assertIs(risk.MarketRegimeEngine, MarketRegimeEngine)
        self.assertIs(risk.regime_from_score, regime_from_score)
        self.assertIs(risk.risk_mapping_for, risk_mapping_for)
        self.assertIs(risk.score_drawdown, score_drawdown)
        self.assertIs(risk.score_realized_volatility, score_realized_volatility)

    def test_regime_score_boundaries(self) -> None:
        self.assertIs(regime_from_score(45), MarketRegime.BULL)
        self.assertIs(regime_from_score(44), MarketRegime.CAUTIOUS_BULL)
        self.assertIs(regime_from_score(15), MarketRegime.CAUTIOUS_BULL)
        self.assertIs(regime_from_score(14), MarketRegime.RISK_OFF)
        self.assertIs(regime_from_score(-20), MarketRegime.RISK_OFF)
        self.assertIs(regime_from_score(-21), MarketRegime.BEAR)

    def test_drawdown_scores_cover_inclusive_boundaries(self) -> None:
        expected = {
            -0.05: 25,
            -0.050001: 10,
            -0.10: 10,
            -0.100001: -5,
            -0.15: -5,
            -0.150001: -15,
            -0.20: -15,
            -0.200001: -25,
        }
        for drawdown, score in expected.items():
            with self.subTest(drawdown=drawdown):
                self.assertEqual(score_drawdown(drawdown), score)

    def test_volatility_scores_cover_inclusive_boundaries(self) -> None:
        expected = {
            0.15: 15,
            0.150001: 8,
            0.20: 8,
            0.30: 0,
            0.40: -8,
            0.400001: -15,
        }
        for volatility, score in expected.items():
            with self.subTest(volatility=volatility):
                self.assertEqual(score_realized_volatility(volatility), score)

    def test_scoring_functions_reject_nonfinite_and_invalid_scores(self) -> None:
        for value in (math.nan, math.inf, -math.inf, True, "0.1"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    score_drawdown(value)
                with self.assertRaises(ValueError):
                    score_realized_volatility(value)
        for value in (-101, 101, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    regime_from_score(value)

    def test_risk_mappings_are_exact(self) -> None:
        expected = {
            MarketRegime.BULL: (1.0, StrategyPermission.NORMAL),
            MarketRegime.CAUTIOUS_BULL: (0.7, StrategyPermission.REDUCED),
            MarketRegime.RISK_OFF: (0.3, StrategyPermission.DEFENSIVE),
            MarketRegime.BEAR: (0.0, StrategyPermission.BLOCKED),
        }
        for regime, mapping in expected.items():
            with self.subTest(regime=regime):
                self.assertEqual(risk_mapping_for(regime), mapping)


class MarketRegimeEngineTests(unittest.TestCase):
    cutoff = date(2026, 8, 26)

    def setUp(self) -> None:
        self.engine = MarketRegimeEngine()

    def assert_complete_result(
        self,
        result: RegimeResult,
        *,
        expected_regime: MarketRegime,
        minimum_score: int,
        maximum_score: int,
        exposure: float,
        permission: StrategyPermission,
    ) -> None:
        self.assertIs(result.regime, expected_regime)
        self.assertGreaterEqual(result.score, minimum_score)
        self.assertLessEqual(result.score, maximum_score)
        self.assertEqual(result.maximum_long_exposure, exposure)
        self.assertIs(result.strategy_permission, permission)
        self.assertEqual(
            tuple(component.name for component in result.components),
            ("Primary trend", "Momentum", "Drawdown", "Realized volatility"),
        )
        self.assertEqual(sum(component.score for component in result.components), result.score)
        for component in result.components:
            self.assertTrue(component.metrics)
            self.assertTrue(component.explanation)

    def test_engine_classifies_deterministic_market_conditions(self) -> None:
        cases = (
            (
                make_bars(),
                MarketRegime.BULL,
                45,
                100,
                1.0,
                StrategyPermission.NORMAL,
            ),
            (
                make_return_bars((0.003,) * 217 + (-0.0025,) * 35),
                MarketRegime.CAUTIOUS_BULL,
                15,
                44,
                0.7,
                StrategyPermission.REDUCED,
            ),
            (
                make_return_bars((0.003,) * 192 + (-0.003,) * 60),
                MarketRegime.RISK_OFF,
                -20,
                14,
                0.3,
                StrategyPermission.DEFENSIVE,
            ),
            (
                make_bars(daily_return=-0.001),
                MarketRegime.BEAR,
                -100,
                -21,
                0.0,
                StrategyPermission.BLOCKED,
            ),
        )
        for history, regime, minimum, maximum, exposure, permission in cases:
            with self.subTest(regime=regime):
                result = self.engine.evaluate(history, as_of=self.cutoff)
                self.assert_complete_result(
                    result,
                    expected_regime=regime,
                    minimum_score=minimum,
                    maximum_score=maximum,
                    exposure=exposure,
                    permission=permission,
                )
                self.assertEqual(result, self.engine.evaluate(history, as_of=self.cutoff))

    def test_future_prices_cannot_change_past_result(self) -> None:
        history = make_bars()
        crash_bars = tuple(
            PriceBar(
                symbol="SPY",
                trading_date=self.cutoff + timedelta(days=offset),
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
                adjusted_close=1.0,
                volume=1_000_000,
            )
            for offset in range(1, 6)
        )
        baseline = self.engine.evaluate(history, as_of=self.cutoff)
        with_future = self.engine.evaluate(history + crash_bars, as_of=self.cutoff)
        self.assertEqual(with_future, baseline)

    def test_constant_prices_leave_comparison_components_neutral(self) -> None:
        result = self.engine.evaluate(make_bars(daily_return=0.0), as_of=self.cutoff)
        component_scores = {component.name: component.score for component in result.components}
        self.assertEqual(component_scores["Primary trend"], 0)
        self.assertEqual(component_scores["Momentum"], 0)
        self.assertEqual(component_scores["Drawdown"], 25)
        self.assertEqual(component_scores["Realized volatility"], 15)


class QQQConfirmationTests(unittest.TestCase):
    cutoff = date(2026, 8, 26)

    def setUp(self) -> None:
        self.engine = MarketRegimeEngine()

    def test_positive_qqq_can_make_well_supported_bull_high_confidence(self) -> None:
        result = self.engine.evaluate(
            make_bars(),
            as_of=self.cutoff,
            qqq_bars=make_bars(symbol="QQQ"),
        )
        self.assertIs(result.confidence, RegimeConfidence.HIGH)
        self.assertIs(result.confidence_evidence.qqq_status, ConfirmationStatus.CONFIRMS_POSITIVE)
        self.assertGreaterEqual(result.confidence_evidence.boundary_distance, 10)
        self.assertGreaterEqual(result.confidence_evidence.agreeing_components, 3)

    def test_missing_or_insufficient_qqq_is_unavailable_and_cannot_change_score(self) -> None:
        spy_history = make_bars()
        without_qqq = self.engine.evaluate(spy_history, as_of=self.cutoff)
        insufficient_qqq = self.engine.evaluate(
            spy_history,
            as_of=self.cutoff,
            qqq_bars=make_bars(symbol="QQQ", count=200),
        )
        for result in (without_qqq, insufficient_qqq):
            with self.subTest(result=result):
                self.assertIs(result.confidence_evidence.qqq_status, ConfirmationStatus.UNAVAILABLE)
                self.assertIn("QQQ confirmation unavailable.", result.data_quality.warnings)
                self.assertIsNot(result.confidence, RegimeConfidence.HIGH)
                self.assertEqual(result.score, without_qqq.score)
                self.assertIs(result.regime, without_qqq.regime)

    def test_contradictory_or_mixed_qqq_never_changes_score_or_grants_high_confidence(self) -> None:
        bear_spy = make_bars(daily_return=-0.001)
        contradictory = self.engine.evaluate(
            bear_spy,
            as_of=self.cutoff,
            qqq_bars=make_bars(symbol="QQQ"),
        )
        baseline = self.engine.evaluate(bear_spy, as_of=self.cutoff)
        mixed = self.engine.evaluate(
            make_bars(),
            as_of=self.cutoff,
            qqq_bars=make_bars(symbol="QQQ", daily_return=0.0),
        )
        self.assertIs(contradictory.confidence, RegimeConfidence.LOW)
        self.assertIs(contradictory.confidence_evidence.qqq_status, ConfirmationStatus.CONFIRMS_POSITIVE)
        self.assertEqual(contradictory.score, baseline.score)
        self.assertIs(contradictory.regime, baseline.regime)
        self.assertIs(mixed.confidence_evidence.qqq_status, ConfirmationStatus.MIXED)
        self.assertIsNot(mixed.confidence, RegimeConfidence.HIGH)

    def test_zero_score_has_no_agreeing_components_and_low_confidence(self) -> None:
        confidence, evidence = self.engine._confidence_for(
            0,
            (),
            ConfirmationStatus.CONFIRMS_POSITIVE,
        )
        self.assertIs(confidence, RegimeConfidence.LOW)
        self.assertEqual(evidence.boundary_distance, 15)
        self.assertEqual(evidence.agreeing_components, 0)


if __name__ == "__main__":
    unittest.main()
