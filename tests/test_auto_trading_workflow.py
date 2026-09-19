from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.models import ChatResponse
from private_quant_lab.web.server import run_auto_trade_request
from private_quant_lab.workflows import auto_trading_schema
from market_agent_fixture import market_response


class FakeAutoModel:
    def __init__(self, final):
        self.calls = []
        self.responses = [
            ChatResponse(content='{"industries":[{"industry":"银行","score":80}]}', model="fake", finish_reason="stop"),
            ChatResponse(content='{"stocks":[{"symbol":"600000.SH","industry":"银行"}]}', model="fake", finish_reason="stop"),
            ChatResponse(content='{"operator_evaluations":[{"symbol":"600000.SH","total_score":78}]}', model="fake", finish_reason="stop"),
            ChatResponse(content='{"risk_review":{"status":"passed","reason":"mock"}}', model="fake", finish_reason="stop"),
            ChatResponse(content=final, model="fake", finish_reason="stop"),
        ]

    def complete(
        self,
        messages,
        temperature=None,
        max_tokens=None,
        tools=None,
        tool_choice=None,
        extra_body=None,
    ):
        self.calls.append(list(messages))
        if "市场情绪 Agent" in messages[0].content:
            return market_response(messages)
        return self.responses.pop(0)


def report_json(risk_status="passed", side="buy", first_position="5%"):
    return (
        '{"report_date":"2026-09-05","headline":"模拟盘可执行",'
        '"market_state":{"direction":"neutral","trading_mode":"rotation",'
        '"sentiment_score":55,"capital_intensity":60,"volatility_risk":35,'
        '"summary":"mock","forbidden_conditions":[]},'
        '"industries":[{"industry":"银行","score":80,"confidence":75,'
        '"thesis":"mock","evidence":[],"counterpoints":[],"invalid_conditions":[]}],'
        '"stocks":[{"symbol":"600000.SH","name":"浦发银行","industry":"银行",'
        '"total_score":78,"quality":70,"momentum":82,"valuation":60,'
        '"liquidity":85,"crowding":42,"risk_score":38,"suggested_position":"8%",'
        '"operator_breakdown":{"roe_ttm":8.5,"gross_margin":24.3,'
        '"debt_ratio":38.1,"rs_20d":12.4,"rs_60d":8.7,"pe_ttm":45.2,'
        '"pe_percentile_5y":63.0,"volume_avg_20d":18.2,'
        '"turnover_rate":2.1,"short_term_gain_20d":15.8,'
        '"margin_balance_change":4.3},"reason":"mock",'
        '"buy_conditions":[],"stop_loss_conditions":[]}],'
        '"risk_review":{"status":"' + risk_status + '","reason":"mock risk",'
        '"hard_limits":{"total_position_limit":"30%","single_stock_max":"12%",'
        '"single_industry_max":"40%","daily_loss_limit":"0.8R"},'
        '"rejections":[],"manual_confirmations":[]},'
        '"trade_plan":[{"symbol":"600000.SH","name":"浦发银行","side":"' + side + '",'
        '"first_position":"' + first_position + '","max_position":"8%",'
        '"buy_conditions":[{"expression":"open_15m_volume >= past_5d_avg_volume_15m * 1.2",'
        '"text":"开盘15分钟量能达标"}]}],'
        '"evidence_chain":[],"summary":"mock summary"}'
    )


class AutoTradingWorkflowTests(unittest.TestCase):
    def test_schema_exposes_order_and_risk_sections(self):
        schema = auto_trading_schema()

        self.assertIn("order_instructions", schema["properties"])
        self.assertIn("executions", schema["properties"])
        self.assertIn("risk_events", schema["properties"])

    def test_run_auto_trade_request_executes_paper_order(self):
        fake_model = FakeAutoModel(report_json())
        events = []

        with patch("private_quant_lab.web.server.load_model_config", return_value=object()):
            with patch("private_quant_lab.web.server.build_chat_model", return_value=fake_model):
                result = run_auto_trade_request(
                    {"task": "运行模拟盘", "llm_observation": False,
                     "account_state": {"cash": "100000"},
                     "market_data": {"600000.SH": {"last_price": 10.0}}},
                    on_event=lambda name, data: events.append((name, data)),
                )

        self.assertEqual(result.run["status"], "completed")
        self.assertEqual(result.run["order_instructions"][0]["symbol"], "600000.SH")
        self.assertEqual(result.run["executions"][0]["status"], "filled")
        self.assertEqual(result.run["positions"][0]["quantity"], 500)
        self.assertEqual(result.run["intraday_alerts"][0]["status"], "watching")
        self.assertEqual(result.run["review_report"]["status"], "completed")
        self.assertIn("paper_order_finished", [name for name, _data in events])
        self.assertIn("intraday_alert", [name for name, _data in events])
        self.assertIn("review_report", [name for name, _data in events])

    def test_pending_risk_blocks_paper_order(self):
        fake_model = FakeAutoModel(report_json(risk_status="pending"))

        with patch("private_quant_lab.web.server.load_model_config", return_value=object()):
            with patch("private_quant_lab.web.server.build_chat_model", return_value=fake_model):
                result = run_auto_trade_request({"task": "运行模拟盘", "llm_observation": False})

        self.assertEqual(result.run["status"], "blocked")
        self.assertEqual(result.run["order_instructions"], [])
        self.assertEqual(result.run["risk_events"][0]["type"], "execution_blocked")
        self.assertEqual(result.run["intraday_alerts"][0]["status"], "skipped")
        self.assertEqual(result.run["review_report"]["risk_effectiveness"], "blocked")

    def test_single_stock_limit_reduces_order_before_execution(self):
        fake_model = FakeAutoModel(report_json(first_position="20%"))

        with patch("private_quant_lab.web.server.load_model_config", return_value=object()):
            with patch("private_quant_lab.web.server.build_chat_model", return_value=fake_model):
                result = run_auto_trade_request({"task_context": "每日自动任务", "llm_observation": False,
                                                 "account_state": {"cash": "100000"},
                                                 "market_data": {"600000.SH": {"last_price": 10.0}}})

        self.assertEqual(result.run["status"], "completed")
        self.assertEqual(result.run["order_instructions"][0]["quantity"], 1200)
        self.assertEqual(result.run["positions"][0]["weight"], "12%")
        self.assertEqual(result.run["risk_events"][0]["type"], "single_stock_limit")
        self.assertIn("每日自动任务", fake_model.calls[0][1].content)

    def test_emergency_stop_blocks_all_orders(self):
        fake_model = FakeAutoModel(report_json())

        with patch("private_quant_lab.web.server.load_model_config", return_value=object()):
            with patch("private_quant_lab.web.server.build_chat_model", return_value=fake_model):
                result = run_auto_trade_request(
                    {
                        "task_context": "每日自动任务",
                        "llm_observation": False,
                        "account_state": {"emergency_stop": True},
                    }
                )

        self.assertEqual(result.run["status"], "blocked")
        self.assertEqual(result.run["executions"], [])
        self.assertEqual(result.run["risk_events"][0]["type"], "emergency_stop")


if __name__ == "__main__":
    unittest.main()
