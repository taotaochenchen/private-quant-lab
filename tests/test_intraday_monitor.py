"""IntradayMonitor 单元测试：止损/止盈/观察/无持仓/风控熔断。"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.domain import OrderInstruction, PositionSnapshot, RiskEvent, utc_now
from private_quant_lab.trading import IntradayMonitor


def position(symbol, quantity=500):
    return PositionSnapshot(symbol=symbol, name=symbol, quantity=quantity,
                            market_value=5000, weight="5%", unrealized_pnl_pct=0)


def order(symbol, stop_loss=9.2, take_profit=12.0):
    return OrderInstruction(order_id="o", symbol=symbol, name=symbol, side="buy",
                            quantity=500, order_type="limit", time_in_force="day",
                            source_plan_ref="p", trigger_conditions=[],
                            stop_loss_price=stop_loss, take_profit_price=take_profit)


class IntradayMonitorTests(unittest.TestCase):
    def test_no_position_is_skipped(self):
        alerts = IntradayMonitor().evaluate([], orders=[])
        self.assertEqual(alerts[0].status, "skipped")
        self.assertEqual(alerts[0].action, "none")

    def test_stop_loss_triggered(self):
        monitor = IntradayMonitor(current_prices={"600000.SH": 9.0})
        alerts = monitor.evaluate([position("600000.SH")], orders=[order("600000.SH")])
        self.assertEqual(alerts[0].status, "triggered")
        self.assertEqual(alerts[0].action, "stop_loss")

    def test_take_profit_triggered(self):
        monitor = IntradayMonitor(current_prices={"600000.SH": 12.5})
        alerts = monitor.evaluate([position("600000.SH")], orders=[order("600000.SH")])
        self.assertEqual(alerts[0].action, "take_profit")

    def test_within_range_is_watching(self):
        monitor = IntradayMonitor(current_prices={"600000.SH": 10.0})
        alerts = monitor.evaluate([position("600000.SH")], orders=[order("600000.SH")])
        self.assertEqual(alerts[0].status, "watching")
        self.assertEqual(alerts[0].action, "hold")

    def test_missing_order_uses_reference_price_watching(self):
        alerts = IntradayMonitor().evaluate([position("600000.SH")], orders=[])
        self.assertEqual(alerts[0].status, "watching")

    def test_critical_risk_event_blocks_new_orders(self):
        monitor = IntradayMonitor(current_prices={"600000.SH": 10.0})
        critical = RiskEvent(event_id="r", type="daily_loss_circuit_breaker", level="critical",
                             status="triggered", message="x", action="block_orders", timestamp=utc_now())
        alerts = monitor.evaluate([position("600000.SH")], orders=[order("600000.SH")],
                                  risk_events=[critical])
        self.assertTrue(any(a.action == "block_new_orders" for a in alerts))


if __name__ == "__main__":
    unittest.main()
