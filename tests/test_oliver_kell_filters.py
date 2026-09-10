import unittest
from datetime import date

from private_quant.research.oliver_kell.fundamentals import (
    FundamentalRecord,
    FundamentalThresholds,
    is_fundamentally_eligible,
    latest_available_record,
)
from private_quant.research.oliver_kell.universe import SecurityState, UniverseRules, is_universe_eligible


class FundamentalPointInTimeTests(unittest.TestCase):
    def setUp(self):
        self.thresholds = FundamentalThresholds()
        self.q1 = FundamentalRecord(
            ticker="600001.SH",
            report_period=date(2020, 3, 31),
            announcement_date=date(2020, 4, 30),
            available_from=date(2020, 4, 30),
            revenue_yoy=35.0,
            net_profit_yoy=40.0,
            roe=10.0,
            eps=0.50,
            float_market_cap_rmb=10_000_000_000.0,
        )

    def test_record_is_invisible_before_available_from(self):
        self.assertIsNone(latest_available_record([self.q1], date(2020, 4, 29)))
        self.assertFalse(is_fundamentally_eligible([self.q1], date(2020, 4, 29), self.thresholds))

    def test_threshold_boundaries_are_inclusive_except_eps(self):
        boundary = FundamentalRecord(
            ticker="600001.SH",
            report_period=date(2020, 6, 30),
            announcement_date=date(2020, 8, 1),
            available_from=date(2020, 8, 1),
            revenue_yoy=30.0,
            net_profit_yoy=30.0,
            roe=8.0,
            eps=0.01,
            float_market_cap_rmb=5_000_000_000.0,
        )
        self.assertTrue(is_fundamentally_eligible([boundary], date(2020, 8, 1), self.thresholds))

    def test_future_restatement_does_not_change_earlier_decision(self):
        restatement = FundamentalRecord(
            ticker="600001.SH",
            report_period=date(2020, 3, 31),
            announcement_date=date(2020, 6, 1),
            available_from=date(2020, 6, 1),
            revenue_yoy=-10.0,
            net_profit_yoy=-20.0,
            roe=3.0,
            eps=-0.10,
            float_market_cap_rmb=10_000_000_000.0,
        )
        decision_date = date(2020, 5, 15)
        chosen = latest_available_record([self.q1, restatement], decision_date)
        self.assertEqual(chosen, self.q1)
        self.assertTrue(is_fundamentally_eligible([self.q1, restatement], decision_date, self.thresholds))


class UniverseGuardTests(unittest.TestCase):
    def setUp(self):
        self.rules = UniverseRules(ipo_seasoning_days=60, min_average_daily_turnover_rmb=20_000_000.0)
        self.base = dict(
            ticker="600001.SH",
            as_of=date(2020, 5, 15),
            listing_date=date(2010, 1, 1),
            is_st=False,
            is_suspended=False,
            average_daily_turnover_rmb=50_000_000.0,
        )

    def test_st_and_suspension_are_excluded(self):
        self.assertFalse(is_universe_eligible(SecurityState(**{**self.base, "is_st": True}), date(2020, 5, 15), self.rules))
        self.assertFalse(is_universe_eligible(SecurityState(**{**self.base, "is_suspended": True}), date(2020, 5, 15), self.rules))

    def test_recent_ipo_and_low_liquidity_are_excluded(self):
        recent = SecurityState(**{**self.base, "listing_date": date(2020, 4, 1)})
        illiquid = SecurityState(**{**self.base, "average_daily_turnover_rmb": 10_000_000.0})
        self.assertFalse(is_universe_eligible(recent, date(2020, 5, 15), self.rules))
        self.assertFalse(is_universe_eligible(illiquid, date(2020, 5, 15), self.rules))

    def test_future_security_state_is_not_usable(self):
        future = SecurityState(**{**self.base, "as_of": date(2020, 5, 16)})
        self.assertFalse(is_universe_eligible(future, date(2020, 5, 15), self.rules))


if __name__ == "__main__":
    unittest.main()
