"""PaperExecutionEngine 单元测试：仓位→整手股数、限价成交、拒绝处理。"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.domain import OrderInstruction
from private_quant_lab.risk import ReviewedPlan
from private_quant_lab.trading import PaperExecutionEngine, reference_price


def reviewed(symbol, side="buy", pct=5.0, stop_loss=None, take_profit=None):
    return ReviewedPlan(
        plan={"symbol": symbol, "name": symbol, "side": side, "buy_conditions": []},
        reviewed_position_pct=pct,
        stop_loss_price=stop_loss,
        take_profit_price=take_profit,
    )


def instruction(index, symbol, side, quantity):
    return OrderInstruction(
        order_id="paper_plan_{0:03d}".format(index), symbol=symbol, name=symbol, side=side,
        quantity=quantity, order_type="limit", time_in_force="day",
        source_plan_ref="trade_plan[0]", trigger_conditions=[])


class SizingTests(unittest.TestCase):
    def test_buy_rounds_down_to_lot(self):
        engine = PaperExecutionEngine("100000", "2026-09-14", prices={"600000.SH": 10.0})
        self.assertEqual(engine.size(5.0, "600000.SH", "buy"), 500)  # 5000/10 = 500
        self.assertEqual(engine.size(1.0, "600000.SH", "buy"), 100)  # 1000/10 = 100
        self.assertEqual(engine.size(0.5, "600000.SH", "buy"), 0)   # 500/10 = 50 -> 0 lot

    def test_reference_price_fallback(self):
        engine = PaperExecutionEngine("100000", "2026-09-14")
        self.assertEqual(engine.price_for("600000.SH"), reference_price("600000.SH"))


class ExecutionTests(unittest.TestCase):
    def test_buy_fills_and_reduces_cash(self):
        engine = PaperExecutionEngine("100000", "2026-09-14", prices={"600000.SH": 10.0})
        order = engine.execute_order(1, instruction(1, "600000.SH", "buy", 500),
                                     reviewed("600000.SH", "buy", 5.0).plan)
        self.assertEqual(order.status, "filled")
        self.assertEqual(order.filled_quantity, 500)
        self.assertEqual(order.avg_price, 10.0)
        positions = engine.positions(name_map={"600000.SH": "浦发银行"})
        self.assertEqual(positions[0].quantity, 500)
        self.assertEqual(positions[0].name, "浦发银行")
        self.assertEqual(positions[0].weight, "5%")
        self.assertEqual(float(engine.snapshot()["cash"]), 95000)

    def test_invalid_symbol_rejected(self):
        engine = PaperExecutionEngine("100000", "2026-09-14", prices={"688981.SH": 50.0})
        order = engine.execute_order(1, instruction(1, "688981.SH", "buy", 100),
                                     reviewed("688981.SH", "buy", 5.0).plan)
        self.assertEqual(order.status, "rejected")
        self.assertEqual(order.filled_quantity, 0)

    def test_insufficient_cash_rejected(self):
        engine = PaperExecutionEngine("1000", "2026-09-14", prices={"600000.SH": 10.0})
        order = engine.execute_order(1, instruction(1, "600000.SH", "buy", 500),
                                     reviewed("600000.SH", "buy", 5.0).plan)
        self.assertEqual(order.status, "rejected")


if __name__ == "__main__":
    unittest.main()
