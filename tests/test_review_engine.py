"""ReviewEngine 单元测试：成交率、风控有效性、账户快照指标、诚实边界。"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.domain import OrderExecution, RiskEvent, utc_now
from private_quant_lab.trading import ReviewEngine


def execution(status="filled", quantity=100):
    return OrderExecution(execution_id="e", order_id="o", symbol="600000.SH", side="buy",
                          quantity=quantity, order_type="limit", status=status,
                          submitted_at=utc_now(), filled_quantity=quantity if status == "filled" else 0,
                          avg_price=10.0, raw_result={})


def critical_event():
    return RiskEvent(event_id="r", type="daily_loss_circuit_breaker", level="critical",
                     status="triggered", message="x", action="block_orders", timestamp=utc_now())


class ReviewEngineTests(unittest.TestCase):
    def test_fill_rate_computed_from_filled(self):
        review = ReviewEngine().build({}, [execution("filled"), execution("rejected")], [], [])
        self.assertEqual(review.order_fill_rate, 0.5)
        self.assertEqual(review.risk_effectiveness, "error")  # 有拒绝 → error

    def test_all_filled_is_normal(self):
        review = ReviewEngine().build({}, [execution("filled")], [], [])
        self.assertEqual(review.order_fill_rate, 1.0)
        self.assertEqual(review.risk_effectiveness, "normal")

    def test_blocked_risk_is_blocked(self):
        review = ReviewEngine().build({}, [], [critical_event()], [])
        self.assertEqual(review.risk_effectiveness, "blocked")

    def test_account_snapshot_in_notes(self):
        snapshot = {"cash": "95000", "positions": {"600000.SH": {"total": 500}}}
        review = ReviewEngine().build({}, [execution("filled")], [], [], account_snapshot=snapshot)
        self.assertTrue(any("现金 95000" in note for note in review.notes))
        self.assertTrue(any("持仓 1 只" in note for note in review.notes))

    def test_alpha_honestly_zero_with_note(self):
        review = ReviewEngine().build({}, [execution("filled")], [], [])
        self.assertEqual(review.industry_alpha, 0)
        self.assertEqual(review.stock_alpha, 0)
        self.assertTrue(any("不计算" in note for note in review.notes))


if __name__ == "__main__":
    unittest.main()
