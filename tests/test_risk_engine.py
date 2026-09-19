"""RiskEngine 单元测试：硬否决、逐单复核、市场检查与止损止盈。"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.risk import RiskEngine


def plan(symbol, side="buy", first_position="5%", industry=None, conditions=None):
    return {"symbol": symbol, "name": symbol, "side": side,
            "first_position": first_position, "max_position": "8%",
            "buy_conditions": conditions or [], "stop_loss_conditions": [],
            "reduce_conditions": []}


def report(trade_plan, risk_status="passed", hard_limits=None, stocks=None):
    return {
        "risk_review": {"status": risk_status, "reason": "mock",
                        "hard_limits": hard_limits or {}},
        "trade_plan": trade_plan,
        "stocks": stocks or [],
    }


class GlobalBlockTests(unittest.TestCase):
    def test_emergency_stop_blocks(self):
        decision = RiskEngine().review(report([plan("600000.SH")]),
                                       account_state={"emergency_stop": True})
        self.assertTrue(decision.blocked)
        self.assertEqual(decision.events[0].type, "emergency_stop")

    def test_daily_loss_circuit_breaker(self):
        decision = RiskEngine().review(report([plan("600000.SH")]),
                                       account_state={"daily_loss_r": 0.9})
        self.assertTrue(decision.blocked)
        self.assertEqual(decision.events[0].type, "daily_loss_circuit_breaker")

    def test_account_drawdown_circuit_breaker(self):
        decision = RiskEngine().review(report([plan("600000.SH")]),
                                       account_state={"current_drawdown_pct": 10,
                                                      "max_drawdown_limit_pct": 10})
        self.assertTrue(decision.blocked)
        self.assertEqual(decision.events[0].type, "account_drawdown_circuit_breaker")

    def test_pending_risk_blocks(self):
        decision = RiskEngine().review(report([plan("600000.SH")], risk_status="pending"))
        self.assertTrue(decision.blocked)
        self.assertEqual(decision.events[0].type, "execution_blocked")

    def test_hard_limits_override_daily_loss_default(self):
        decision = RiskEngine().review(
            report([plan("600000.SH")], hard_limits={"daily_loss_limit": "0.5R"}),
            account_state={"daily_loss_r": 0.6})
        self.assertTrue(decision.blocked)


class PositionLimitTests(unittest.TestCase):
    def test_single_stock_limit(self):
        decision = RiskEngine().review(
            report([plan("600000.SH", first_position="20%")],
                   hard_limits={"single_stock_max": "12%"}))
        self.assertFalse(decision.blocked)
        self.assertEqual(decision.reviewed_plans[0].reviewed_position_pct, 12.0)
        self.assertEqual(decision.events[0].type, "single_stock_limit")

    def test_total_position_limit(self):
        decision = RiskEngine().review(
            report([plan("600000.SH", first_position="20%"), plan("000001.SZ", first_position="20%")],
                   hard_limits={"single_stock_max": "20%", "total_position_limit": "30%"}))
        self.assertEqual(decision.reviewed_plans[0].reviewed_position_pct, 20.0)
        self.assertEqual(decision.reviewed_plans[1].reviewed_position_pct, 10.0)
        self.assertIn("total_position_limit", [e.type for e in decision.events])

    def test_single_industry_limit(self):
        stocks = [{"symbol": "600000.SH", "industry": "银行"},
                  {"symbol": "601398.SH", "industry": "银行"}]
        decision = RiskEngine().review(
            report([plan("600000.SH", first_position="30%"), plan("601398.SH", first_position="30%")],
                   hard_limits={"single_stock_max": "30%", "single_industry_max": "40%",
                                "total_position_limit": "60%"}, stocks=stocks))
        self.assertEqual(decision.reviewed_plans[0].reviewed_position_pct, 30.0)
        self.assertEqual(decision.reviewed_plans[1].reviewed_position_pct, 10.0)
        self.assertIn("single_industry_limit", [e.type for e in decision.events])


class MarketCheckTests(unittest.TestCase):
    def test_liquidity_limit_skips(self):
        decision = RiskEngine().review(
            report([plan("600000.SH", first_position="5%")]),
            market_data={"600000.SH": {"last_price": 10.0, "avg_daily_value": 100.0}})
        self.assertTrue(decision.reviewed_plans[0].skip)
        self.assertIn("liquidity_limit", [e.type for e in decision.events])

    def test_liquidity_passes_when_under_threshold(self):
        decision = RiskEngine().review(
            report([plan("600000.SH", first_position="5%")]),
            market_data={"600000.SH": {"last_price": 10.0, "avg_daily_value": 100000.0}})
        self.assertFalse(decision.reviewed_plans[0].skip)
        self.assertEqual(decision.reviewed_plans[0].reviewed_position_pct, 5.0)

    def test_high_volatility_delevers(self):
        decision = RiskEngine().review(
            report([plan("600000.SH", first_position="10%")]),
            market_data={"600000.SH": {"volatility_pct": 50.0}})
        self.assertEqual(decision.reviewed_plans[0].reviewed_position_pct, 5.0)
        self.assertIn("volatility_delever", [e.type for e in decision.events])

    def test_event_window_blocks(self):
        decision = RiskEngine().review(
            report([plan("600000.SH", first_position="5%")]),
            market_data={"600000.SH": {"next_event_days": 0}})
        self.assertTrue(decision.reviewed_plans[0].skip)
        self.assertIn("event_window_block", [e.type for e in decision.events])

    def test_correlation_group_limit(self):
        decision = RiskEngine().review(
            report([plan("600000.SH", first_position="20%"), plan("601398.SH", first_position="20%")],
                   hard_limits={"single_stock_max": "20%", "total_position_limit": "60%"}),
            market_data={"600000.SH": {"correlation_group": "banks"},
                         "601398.SH": {"correlation_group": "banks"}})
        self.assertEqual(decision.reviewed_plans[1].reviewed_position_pct, 10.0)
        self.assertIn("correlation_limit", [e.type for e in decision.events])

    def test_missing_market_data_is_honest_pass(self):
        decision = RiskEngine().review(report([plan("600000.SH", first_position="5%")]))
        self.assertFalse(decision.blocked)
        self.assertEqual(decision.reviewed_plans[0].reviewed_position_pct, 5.0)
        self.assertEqual(decision.reviewed_plans[0].skip, False)


class StopLossTakeProfitTests(unittest.TestCase):
    def test_default_from_reference_price(self):
        decision = RiskEngine().review(
            report([plan("600000.SH", first_position="5%")]),
            market_data={"600000.SH": {"last_price": 10.0}})
        self.assertEqual(decision.reviewed_plans[0].stop_loss_price, 9.2)
        self.assertEqual(decision.reviewed_plans[0].take_profit_price, 12.0)

    def test_condition_price_wins_over_default(self):
        decision = RiskEngine().review(
            report([{"symbol": "600000.SH", "name": "600000.SH", "side": "buy",
                     "first_position": "5%", "max_position": "8%",
                     "buy_conditions": [],
                     "stop_loss_conditions": [{"expression": "close <= 9.10", "text": "止损"}],
                     "reduce_conditions": [{"expression": "close >= 11.50", "text": "止盈"}]}]),
            market_data={"600000.SH": {"last_price": 10.0}})
        self.assertEqual(decision.reviewed_plans[0].stop_loss_price, 9.1)
        self.assertEqual(decision.reviewed_plans[0].take_profit_price, 11.5)


class NonTradeSideTests(unittest.TestCase):
    def test_hold_side_skipped(self):
        decision = RiskEngine().review(report([plan("600000.SH", side="hold")]))
        self.assertTrue(decision.reviewed_plans[0].skip)
        self.assertEqual(decision.events[0].type, "order_skipped")


if __name__ == "__main__":
    unittest.main()
