"""TradingCalendar 单元测试：周末规则、权威列表、T-1 推算与诚实标记。"""

from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.domain.calendar import TradingCalendar, _coerce, _as_date


class WeekdayOnlyCalendarTests(unittest.TestCase):
    def setUp(self):
        self.cal = TradingCalendar.weekday_only()

    def test_verified_false_and_no_holiday_data(self):
        self.assertFalse(self.cal.verified)
        self.assertFalse(self.cal.has_holiday_data)
        self.assertEqual(self.cal.source, "weekday_only_holidays_unknown")

    def test_weekend_not_trading(self):
        self.assertTrue(self.cal.is_trading_day("2026-09-11"))  # Friday
        self.assertFalse(self.cal.is_trading_day("2026-09-12"))  # Saturday
        self.assertFalse(self.cal.is_trading_day("2026-09-13"))  # Sunday

    def test_previous_trading_day_skips_weekend(self):
        self.assertEqual(self.cal.previous_trading_day("2026-09-14"), date(2026, 9, 11))
        self.assertEqual(self.cal.previous_trading_day("2026-09-11"), date(2026, 9, 10))

    def test_next_trading_day_skips_weekend(self):
        self.assertEqual(self.cal.next_trading_day("2026-09-11"), date(2026, 9, 14))


class AuthoritativeCalendarTests(unittest.TestCase):
    def setUp(self):
        # 2026-09-10..15，其中 12/13 为周末，其余为交易日；外加一个假期 14 说明
        # 权威列表会覆盖周末规则。
        self.dates = ["2026-09-10", "2026-09-11", "2026-09-15"]
        self.cal = TradingCalendar.from_trading_dates(self.dates, source="fixture")

    def test_verified_true_and_coverage(self):
        self.assertTrue(self.cal.verified)
        self.assertTrue(self.cal.has_holiday_data)
        self.assertEqual(self.cal.coverage, (date(2026, 9, 10), date(2026, 9, 15)))
        self.assertEqual(self.cal.source, "fixture")

    def test_explicit_list_overrides_weekday_rule(self):
        # 2026-09-14 是周一，但不在权威列表里 => 视为休市（例如节假日）。
        self.assertFalse(self.cal.is_trading_day("2026-09-14"))
        self.assertTrue(self.cal.is_trading_day("2026-09-15"))

    def test_previous_trading_day_from_list(self):
        # 09-15 的上一交易日是 09-11（09-14 在权威列表里休市）。
        self.assertEqual(self.cal.previous_trading_day("2026-09-15"), date(2026, 9, 11))

    def test_out_of_coverage_rejected(self):
        with self.assertRaises(ValueError):
            self.cal.previous_trading_day("2026-09-10")
        with self.assertRaises(ValueError):
            self.cal.next_trading_day("2026-09-15")


class CoercionTests(unittest.TestCase):
    def test_coerce_accepts_date_datetime_string(self):
        self.assertEqual(_coerce("2026-09-13"), date(2026, 9, 13))
        self.assertEqual(_coerce(date(2026, 9, 13)), date(2026, 9, 13))
        self.assertEqual(_coerce(" 2026-09-13 "), date(2026, 9, 13))

    def test_coerce_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            _coerce("not-a-date")
        with self.assertRaises(TypeError):
            _coerce(123)

    def test_as_date_handles_timestamp_text(self):
        self.assertEqual(_as_date("2026-09-13 00:00:00"), date(2026, 9, 13))
        self.assertEqual(_as_date(date(2026, 9, 13)), date(2026, 9, 13))


if __name__ == "__main__":
    unittest.main()
