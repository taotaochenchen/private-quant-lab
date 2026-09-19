"""每日报告摘要格式化单元测试（不触发模型调用）。"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from daily_report import format_summary


def report(plans=None, revision=None):
    return {
        "report_date": "2026-09-22",
        "headline": "mock",
        "market_state": {"direction": "neutral", "trading_mode": "rotation",
                         "sentiment_score": 55, "capital_intensity": 60, "volatility_risk": 35,
                         "summary": "m", "forbidden_conditions": []},
        "trade_plan": plans or [],
        "strategy_revision": revision,
        "summary": "m",
    }


class DailyReportSummaryTests(unittest.TestCase):
    def test_summary_includes_decision_and_review(self):
        text = format_summary(report(
            plans=[{"symbol": "600000.SH", "name": "浦发银行", "side": "buy", "first_position": "5%"}],
            revision={"previous_trade_date": "2026-09-19",
                      "changes": [
                          {"symbol": "600000.SH", "status": "retained", "execution_status": "executed"},
                          {"symbol": "000001.SZ", "status": "added", "execution_status": "unknown"},
                      ]}))
        self.assertIn("盘前决策 2026-09-22", text)
        self.assertIn("600000.SH 浦发银行 买 5%", text)
        self.assertIn("复盘 vs 2026-09-19", text)
        self.assertIn("保留 1", text)
        self.assertIn("新增 1", text)
        self.assertIn("仅供研究参考", text)

    def test_empty_plan_and_no_baseline(self):
        text = format_summary(report(plans=[]))
        self.assertIn("无（观察 / 风控暂停）", text)
        self.assertIn("首次分析，无 T-1 基线", text)


if __name__ == "__main__":
    unittest.main()
