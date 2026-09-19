"""全自动模拟盘闭环端到端测试：分析→决策→风控→下单→持仓→监控→复盘。"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.workflows import build_auto_trading_run


def full_report():
    return {
        "report_date": "2026-09-05",
        "headline": "闭环测试",
        "market_state": {"direction": "neutral", "trading_mode": "rotation",
                         "sentiment_score": 55, "capital_intensity": 60, "volatility_risk": 35,
                         "summary": "mock", "forbidden_conditions": []},
        "industries": [{"industry": "银行", "score": 80, "confidence": 75, "thesis": "mock",
                        "evidence": [], "counterpoints": [], "invalid_conditions": []}],
        "stocks": [
            {"symbol": "600000.SH", "name": "浦发银行", "industry": "银行", "total_score": 78},
            {"symbol": "000001.SZ", "name": "平安银行", "industry": "银行", "total_score": 75},
        ],
        "risk_review": {"status": "passed", "reason": "mock",
                        "hard_limits": {"total_position_limit": "30%", "single_stock_max": "12%",
                                        "single_industry_max": "40%", "daily_loss_limit": "0.8R"},
                        "rejections": [], "manual_confirmations": []},
        "trade_plan": [
            {"symbol": "600000.SH", "name": "浦发银行", "side": "buy",
             "first_position": "5%", "max_position": "8%", "buy_conditions": []},
            {"symbol": "000001.SZ", "name": "平安银行", "side": "buy",
             "first_position": "8%", "max_position": "8%", "buy_conditions": []},
        ],
        "evidence_chain": [],
        "summary": "mock",
    }


class ClosedLoopTests(unittest.TestCase):
    def setUp(self):
        self.account_state = {"cash": "200000", "trade_date": "2026-09-05"}
        self.market_data = {
            "600000.SH": {"last_price": 10.0},
            "000001.SZ": {"last_price": 12.5},
        }

    def test_full_closed_loop_happy_path(self):
        run = build_auto_trading_run(full_report(), account_state=self.account_state,
                                     market_data=self.market_data)

        self.assertEqual(run["status"], "completed")
        # 下单：两条限价指令
        self.assertEqual(len(run["order_instructions"]), 2)
        self.assertEqual(run["order_instructions"][0]["symbol"], "600000.SH")
        self.assertEqual(run["order_instructions"][0]["order_type"], "limit")
        # 成交：均 filled，含止损/止盈
        self.assertEqual([e["status"] for e in run["executions"]], ["filled", "filled"])
        self.assertIsNotNone(run["order_instructions"][0]["stop_loss_price"])
        # 持仓：整手股数，600000.SH 5% = 1000 股；000001.SZ 8% = 1200 股
        positions = {p["symbol"]: p for p in run["positions"]}
        self.assertEqual(positions["600000.SH"]["quantity"], 1000)
        self.assertEqual(positions["000001.SZ"]["quantity"], 1200)
        # 盘中监控：两只持仓都保持观察
        self.assertEqual(len(run["intraday_alerts"]), 2)
        self.assertTrue(all(a["status"] == "watching" for a in run["intraday_alerts"]))
        # 复盘：成交率 100%，账户快照进入 notes
        self.assertEqual(run["review_report"]["order_fill_rate"], 1.0)
        self.assertEqual(run["review_report"]["risk_effectiveness"], "normal")
        self.assertTrue(any("持仓 2 只" in note for note in run["review_report"]["notes"]))

    def test_closed_loop_blocked_by_risk(self):
        report = full_report()
        report["risk_review"]["status"] = "blocked"
        run = build_auto_trading_run(report, account_state=self.account_state,
                                     market_data=self.market_data)

        self.assertEqual(run["status"], "blocked")
        self.assertEqual(run["order_instructions"], [])
        self.assertEqual(run["executions"], [])
        self.assertEqual(run["intraday_alerts"][0]["status"], "skipped")
        self.assertEqual(run["review_report"]["risk_effectiveness"], "blocked")

    def test_closed_loop_stop_loss_triggers_intraday(self):
        report = full_report()
        report["trade_plan"] = report["trade_plan"][:1]
        # 执行参考价 10.0 → 止损 9.2；盘中现价 9.0 跌破止损 → stop_loss
        run = build_auto_trading_run(
            report, account_state=self.account_state,
            market_data={"600000.SH": {"last_price": 10.0, "current_price": 9.0}})
        self.assertEqual(run["executions"][0]["status"], "filled")
        self.assertEqual(run["intraday_alerts"][0]["action"], "stop_loss")


if __name__ == "__main__":
    unittest.main()
