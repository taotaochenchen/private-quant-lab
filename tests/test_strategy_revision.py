from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.domain import empty_pre_market_report
from private_quant_lab.domain.calendar import TradingCalendar
from private_quant_lab.domain.strategy_revision import build_decision_context, compare_strategy


def plan(symbol, maximum="4%"):
    return {"symbol": symbol, "name": "测试标的", "side": "buy", "first_position": "2%",
            "max_position": maximum, "buy_conditions": []}


class StrategyRevisionTests(unittest.TestCase):
    def setUp(self):
        self.previous = empty_pre_market_report("2026-09-11").to_dict()
        self.previous["trade_plan"] = [plan("UNCHANGED"), plan("CHANGED"), plan("REMOVED")]
        self.today = empty_pre_market_report("2026-09-14").to_dict()
        self.today["risk_review"]["status"] = "manual_review"
        self.today["trade_plan"] = [plan("UNCHANGED"), plan("CHANGED", "3%"), plan("NEW")]

    def context(self, **kwargs):
        return build_decision_context(self.previous, "2026-09-11", "2026-09-14", **kwargs)

    def test_weekend_gap_and_all_change_types(self):
        context = self.context()
        self.assertFalse(context["calendar_verified"])
        revision = compare_strategy(context, self.today)
        statuses = {item["symbol"]: item["status"] for item in revision["changes"]}
        self.assertEqual(statuses, {"UNCHANGED": "retained", "CHANGED": "adjusted",
                                   "REMOVED": "withdrawn", "NEW": "added"})
        changed = next(item for item in revision["changes"] if item["symbol"] == "CHANGED")
        self.assertEqual(changed["changed_fields"], ["max_position"])
        self.assertEqual(revision["execution_status"], "unknown")

    def test_risk_block_is_suspension_not_sell(self):
        self.today["risk_review"]["status"] = "blocked"
        self.today["trade_plan"] = []
        revision = compare_strategy(self.context(), self.today)
        self.assertTrue(all(item["status"] == "suspended" and item["after"] is None
                            for item in revision["changes"]))

    def test_no_baseline_is_initial_not_daily_addition(self):
        context = build_decision_context(None, None, "2026-09-14")
        revision = compare_strategy(context, self.today)
        self.assertEqual(revision["baseline_status"], "missing")
        self.assertTrue(all(item["status"] == "initial" for item in revision["changes"]))

    def test_dates_require_explicit_previous_trading_day(self):
        for previous_date in (None, "2026-09-10", "2026-09-14", "2026-09-15", "invalid"):
            with self.assertRaises(ValueError):
                build_decision_context(self.previous, previous_date, "2026-09-14")

    def test_duplicate_symbols_and_invalid_feedback_rejected(self):
        self.previous["trade_plan"].append(plan("UNCHANGED"))
        with self.assertRaises(ValueError):
            self.context()
        for feedback in ({}, "x" * 4001):
            with self.assertRaises(ValueError):
                build_decision_context(None, None, "2026-09-14", feedback)

    def test_no_mutation_or_recursive_history(self):
        self.previous["strategy_revision"] = {"old_history": "not forwarded"}
        original = deepcopy(self.previous)
        context = self.context(execution_feedback="未买入")
        self.assertNotIn("strategy_revision", context["previous_report"])
        result = compare_strategy(context, self.today)
        result["changes"][0]["before"]["max_position"] = "0%"
        self.assertEqual(self.previous, original)
        self.assertEqual(context["execution_status"], "user_reported_unverified")

    def _authoritative_calendar(self):
        # 2026-09-14 的上一交易日为 2026-09-11。
        return TradingCalendar.from_trading_dates(["2026-09-10", "2026-09-11", "2026-09-14"], source="fixture")

    def test_auto_derive_previous_trade_date_with_verified_calendar(self):
        context = build_decision_context(self.previous, None, "2026-09-14", calendar=self._authoritative_calendar())
        self.assertTrue(context["calendar_verified"])
        self.assertEqual(context["previous_trade_date"], "2026-09-11")
        self.assertEqual(context["calendar_source"], "fixture")

    def test_mismatch_with_calendar_rejected(self):
        with self.assertRaises(ValueError):
            build_decision_context(self.previous, "2026-09-10", "2026-09-14", calendar=self._authoritative_calendar())

    def test_unverified_calendar_still_requires_explicit_date(self):
        with self.assertRaises(ValueError):
            build_decision_context(self.previous, None, "2026-09-14", calendar=TradingCalendar.weekday_only())

    def test_revision_reflects_calendar_verification(self):
        context = build_decision_context(self.previous, "2026-09-11", "2026-09-14", calendar=self._authoritative_calendar())
        revision = compare_strategy(context, self.today)
        self.assertTrue(revision["calendar_verified"])
        self.assertTrue(any("交易日历推算" in note for note in revision["limitations"]))

    def test_execution_items_embedded_and_annotated(self):
        context = build_decision_context(self.previous, "2026-09-11", "2026-09-14",
                                         execution_items=[
                                             {"symbol": "UNCHANGED", "execution_status": "executed", "filled_quantity": 100},
                                             {"symbol": "CHANGED", "execution_status": "partial"},
                                         ])
        self.assertEqual(context["execution_status"], "user_reported_unverified")
        self.assertEqual(context["execution_items"][0]["execution_status"], "executed")
        self.assertEqual(context["execution_items"][0]["filled_quantity"], 100.0)
        revision = compare_strategy(context, self.today)
        by_symbol = {item["symbol"]: item for item in revision["changes"]}
        self.assertEqual(by_symbol["UNCHANGED"]["execution_status"], "executed")
        self.assertEqual(by_symbol["CHANGED"]["execution_status"], "partial")
        self.assertEqual(by_symbol["REMOVED"]["execution_status"], "unknown")

    def test_invalid_execution_items_rejected(self):
        for bad in ("x",
                    [{"symbol": ""}],
                    [{"symbol": "A", "execution_status": "bogus"}],
                    [{"symbol": "A", "execution_status": "executed", "filled_quantity": "abc"}]):
            with self.assertRaises(ValueError):
                build_decision_context(self.previous, "2026-09-11", "2026-09-14", execution_items=bad)


if __name__ == "__main__":
    unittest.main()
