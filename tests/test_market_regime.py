import math
import copy
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.data import PriceBar
from private_quant.risk.market_regime import (
    ConfirmationStatus,
    InsufficientRegimeHistoryError,
    InvalidRegimeDataError,
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


if __name__ == "__main__":
    unittest.main()
