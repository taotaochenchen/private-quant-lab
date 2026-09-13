from pathlib import Path
from datetime import datetime, timedelta, timezone
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.models import ChatResponse, ChatToolCall
from private_quant_lab.web.server import run_pre_market_request
from private_quant_lab.workflows import build_pre_market_system_prompt


class FakeModel:
    def __init__(self):
        self.calls = []
        final_report = (
            '{"report_date":"2026-09-05","headline":"观察为主",'
            '"market_state":{"direction":"neutral","trading_mode":"observe",'
            '"sentiment_score":55,"capital_intensity":50,"volatility_risk":42,'
            '"summary":"市场状态中性。","forbidden_conditions":[]},'
            '"industries":[{"industry":"半导体","score":80,"confidence":75,'
            '"thesis":"mock","evidence":[],"counterpoints":[],'
            '"invalid_conditions":[{"expression":"industry_strength < 70","text":"行业强度跌破70"}]}],'
            '"stocks":[{"symbol":"SMIC","name":"中芯国际","industry":"半导体",'
            '"total_score":78,"quality":70,"momentum":82,"valuation":60,'
            '"liquidity":85,"crowding":42,"risk_score":38,"suggested_position":"8%",'
            '"operator_breakdown":{"roe_ttm":8.5,"gross_margin":24.3,'
            '"debt_ratio":38.1,"rs_20d":12.4,"rs_60d":8.7,"pe_ttm":45.2,'
            '"pe_percentile_5y":63.0,"volume_avg_20d":18.2,'
            '"turnover_rate":2.1,"short_term_gain_20d":15.8,'
            '"margin_balance_change":4.3},"reason":"mock",'
            '"buy_conditions":[],"stop_loss_conditions":[]}],'
            '"risk_review":{"status":"pending","reason":"mock",'
            '"hard_limits":{"total_position_limit":"0%","single_stock_max":"0%",'
            '"single_industry_max":"0%","daily_loss_limit":"0R"},'
            '"rejections":[],"manual_confirmations":[]},'
            '"trade_plan":[{"symbol":"SMIC","name":"中芯国际","side":"hold",'
            '"first_position":"0%","max_position":"8%",'
            '"buy_conditions":[{"expression":"open_15m_volume >= past_5d_avg_volume_15m * 1.2",'
            '"text":"开盘15分钟量能达标"}]}],'
            '"evidence_chain":[{"evidence_id":"evt_001","type":"macro",'
            '"source":"mock","source_timestamp":"2026-09-05T00:00:00Z",'
            '"value":{"vix":42},"used_by":["market_sentiment_agent"],'
            '"influence":"风险温度为42"}],"summary":"等待更多数据。"}'
        )
        self.responses = [
            ChatResponse(
                content="",
                model="fake",
                finish_reason="tool_calls",
                tool_calls=[ChatToolCall("call-1", "get_macro_snapshot", {"indicators": ["vix"], "as_of": "2026-09-05T08:45:00+08:00"})],
            ),
            ChatResponse(content='{"direction":"neutral","trading_mode":"observe"}', model="fake", finish_reason="stop"),
            ChatResponse(
                content="",
                model="fake",
                finish_reason="tool_calls",
                tool_calls=[ChatToolCall("call-2", "universe_screen", {"universe": "us_large_cap", "limit": 2})],
            ),
            ChatResponse(content='{"industries":[{"industry":"半导体","score":80}]}', model="fake", finish_reason="stop"),
            ChatResponse(content='{"stocks":[{"symbol":"SMIC","industry":"半导体"}]}', model="fake", finish_reason="stop"),
            ChatResponse(content='{"operator_evaluations":[{"symbol":"SMIC","total_score":78}]}', model="fake", finish_reason="stop"),
            ChatResponse(content='{"risk_review":{"status":"pending","reason":"mock"}}', model="fake", finish_reason="stop"),
            ChatResponse(
                content=final_report,
                model="fake",
                finish_reason="stop",
            ),
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
        self.tool_sets = getattr(self, "tool_sets", [])
        self.tool_sets.append(tools)
        self.extra_bodies = getattr(self, "extra_bodies", [])
        self.extra_bodies.append(extra_body or {})
        return self.responses.pop(0)


class PreMarketWorkflowTests(unittest.TestCase):
    def test_prompt_embeds_schema(self):
        prompt = build_pre_market_system_prompt()

        self.assertIn("盘前指挥官", prompt)
        self.assertIn("market_state", prompt)
        self.assertIn("trade_plan", prompt)
        self.assertNotIn("{schema}", prompt)

    def test_run_pre_market_request_uses_tools_and_returns_final_report_text(self):
        fake_model = FakeModel()

        with patch("private_quant_lab.web.server.load_model_config", return_value=object()):
            with patch("private_quant_lab.web.server.build_chat_model", return_value=fake_model):
                result = run_pre_market_request(
                    {
                        "task": "生成盘前报告",
                        "llm_observation": False,
                        "max_steps": 3,
                        "max_tokens": 500,
                    }
                )

        self.assertEqual(result.report["headline"], "市场情绪校验未通过，今日观察。")
        self.assertEqual(result.report["risk_review"]["status"], "blocked")
        self.assertEqual(result.report["trade_plan"], [])
        self.assertIsNone(result.report["market_state"]["capital_intensity"])
        self.assertEqual(result.trace[1]["name"], "get_macro_snapshot")
        names = {tool["function"]["name"] for tool in fake_model.tool_sets[0]}
        self.assertEqual(len(names), 9)
        self.assertIn("compute_market_regime_metrics", names)
        self.assertNotIn("paper_order", names)
        self.assertTrue(any(item.get("name") == "universe_screen" for item in result.trace))
        self.assertIn("市场情绪 Agent", fake_model.calls[0][0].content)
        self.assertIn("upstream_results", fake_model.calls[-1][1].content)
        self.assertEqual(fake_model.extra_bodies[0]["response_format"]["type"], "json_object")

    def test_run_pre_market_request_uses_agent_prompt_overrides(self):
        fake_model = FakeModel()

        with patch("private_quant_lab.web.server.load_model_config", return_value=object()):
            with patch("private_quant_lab.web.server.build_chat_model", return_value=fake_model):
                run_pre_market_request(
                    {
                        "task_context": "自动任务",
                        "llm_observation": False,
                        "max_steps": 3,
                        "max_tokens": 500,
                        "agent_system_prompts": {
                            "market_sentiment_agent": "自定义市场情绪 SP",
                        },
                    }
                )

        self.assertTrue(fake_model.calls[0][0].content.startswith("自定义市场情绪 SP\n"))
        self.assertIn("本次仅生成建议", fake_model.calls[0][0].content)
        self.assertIn("行业研究 Agent", fake_model.calls[2][0].content)

    def test_previous_advice_reaches_all_agents_without_order_tools(self):
        from private_quant_lab.domain import empty_pre_market_report
        from private_quant_lab.domain.calendar import TradingCalendar
        fake_model = FakeModel()
        previous_date = (datetime.now(timezone(timedelta(hours=8))).date() - timedelta(days=3)).isoformat()
        previous = empty_pre_market_report(previous_date).to_dict()
        previous["trade_plan"] = [{"symbol": "TEST", "name": "测试标的", "side": "buy",
                                   "first_position": "2%", "max_position": "4%", "buy_conditions": []}]
        events = []
        with patch("private_quant_lab.web.server.get_trading_calendar",
                   return_value=TradingCalendar.weekday_only()), \
                patch("private_quant_lab.web.server.load_model_config", return_value=object()), \
                patch("private_quant_lab.web.server.build_chat_model", return_value=fake_model):
            result = run_pre_market_request({
                "llm_observation": False, "previous_report": previous,
                "previous_trade_date": previous_date, "execution_feedback": "昨日未执行。",
            }, on_event=lambda event, data: events.append((event, data)))
        timestamps = set()
        for messages, schemas in zip(fake_model.calls, fake_model.tool_sets):
            task = json.loads(messages[1].content)
            self.assertEqual(task["decision_context"]["previous_report"], previous)
            self.assertEqual(task["decision_context"]["execution_feedback"], "昨日未执行。")
            timestamps.add(task["scheduled_task"]["as_of"])
            self.assertNotIn("paper_order", {tool["function"]["name"] for tool in schemas})
        self.assertEqual(len(timestamps), 1)
        revision = result.report["strategy_revision"]
        self.assertEqual(revision["changes"][0]["status"], "suspended")
        self.assertEqual(revision["execution_status"], "user_reported_unverified")
        self.assertTrue(any(event == "pre_market_report" and "strategy_revision" in data["report"]
                            for event, data in events))

    def test_invalid_baseline_stops_before_model_requests(self):
        from private_quant_lab.domain import empty_pre_market_report
        from private_quant_lab.domain.calendar import TradingCalendar
        fake_model = FakeModel()
        with patch("private_quant_lab.web.server.get_trading_calendar",
                   return_value=TradingCalendar.weekday_only()), \
                patch("private_quant_lab.web.server.load_model_config", return_value=object()), \
                patch("private_quant_lab.web.server.build_chat_model", return_value=fake_model):
            with self.assertRaises(ValueError):
                run_pre_market_request({"llm_observation": False,
                                        "previous_report": empty_pre_market_report().to_dict()})
        self.assertFalse(fake_model.calls)

    def test_run_pre_market_request_falls_back_when_report_json_is_invalid(self):
        fake_model = FakeModel()
        fake_model.responses = [
            ChatResponse(content='{"node":"market"}', model="fake", finish_reason="stop"),
            ChatResponse(content='{"node":"industry"}', model="fake", finish_reason="stop"),
            ChatResponse(content='{"node":"stock"}', model="fake", finish_reason="stop"),
            ChatResponse(content='{"node":"operator"}', model="fake", finish_reason="stop"),
            ChatResponse(content='{"node":"risk"}', model="fake", finish_reason="stop"),
            ChatResponse(content="不是 JSON", model="fake", finish_reason="stop"),
        ]

        with patch("private_quant_lab.web.server.load_model_config", return_value=object()):
            with patch("private_quant_lab.web.server.build_chat_model", return_value=fake_model):
                result = run_pre_market_request(
                    {
                        "task": "生成盘前报告",
                        "llm_observation": False,
                        "max_steps": 3,
                        "max_tokens": 500,
                    }
                )

        self.assertEqual(result.report["market_state"]["trading_mode"], "observe")
        self.assertIn("pre-market report must be valid JSON", result.report["risk_review"]["rejections"][0])


if __name__ == "__main__":
    unittest.main()
