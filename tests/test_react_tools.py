from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.agents import ReActAgent, ReActAgentError
from private_quant_lab.models import ChatResponse, ChatToolCall
from private_quant_lab.tools import (
    QuantTool,
    ToolEnvironment,
    ToolSpec,
    build_mock_quant_environment,
    common_quant_tool_names,
)


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

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
        if not self.responses:
            raise AssertionError("unexpected model call")
        response = self.responses.pop(0)
        if isinstance(response, ChatResponse):
            return response
        return ChatResponse(content=response, model="fake", finish_reason="stop")


class MockQuantToolTests(unittest.TestCase):
    def test_lists_common_quant_tools(self):
        names = common_quant_tool_names()

        self.assertIn("market_snapshot", names)
        self.assertIn("strategy_backtest", names)
        self.assertIn("paper_order", names)
        self.assertIn("web_search", names)

    def test_runs_mock_market_snapshot(self):
        environment = build_mock_quant_environment()

        result = environment.run("market_snapshot", {"symbol": "nvda"})

        self.assertEqual(result.name, "market_snapshot")
        self.assertEqual(result.output["symbol"], "NVDA")
        self.assertTrue(result.output["mock"])

    def test_runs_mock_web_search(self):
        environment = build_mock_quant_environment()

        result = environment.run("web_search", {"query": "NVDA AI demand", "limit": 2})

        self.assertEqual(result.name, "web_search")
        self.assertEqual(result.output["query"], "NVDA AI demand")
        self.assertEqual(len(result.output["results"]), 2)
        self.assertTrue(result.output["mock"])

    def test_exports_openai_tool_schemas(self):
        environment = build_mock_quant_environment()

        schemas = environment.openai_tools()
        web_search = [
            schema for schema in schemas if schema["function"]["name"] == "web_search"
        ][0]

        self.assertEqual(web_search["type"], "function")
        self.assertEqual(web_search["function"]["parameters"]["type"], "object")
        self.assertIn("query", web_search["function"]["parameters"]["required"])

    def test_can_use_model_to_simulate_observation(self):
        observation_model = FakeModel(
            [
                (
                    '{"symbol": "NVDA", "price": 501.25, "change_pct": 0.018, '
                    '"volume": 12345678, "regime": "risk_on", "mock": true}'
                )
            ]
        )
        environment = build_mock_quant_environment(observation_model=observation_model)

        result = environment.run("market_snapshot", {"symbol": "NVDA"})

        self.assertEqual(result.output["price"], 501.25)
        self.assertEqual(result.output["observation_source"], "deepseek")
        self.assertIn("required_output_shape", observation_model.calls[0][-1].content)

    def test_observation_model_empty_response_falls_back_locally(self):
        observation_model = FakeModel([""])
        environment = build_mock_quant_environment(observation_model=observation_model)

        result = environment.run("market_snapshot", {"symbol": "NVDA"})

        self.assertEqual(result.output["symbol"], "NVDA")
        self.assertEqual(result.output["observation_source"], "local_fallback")
        self.assertIn("empty content", result.output["observation_error"])


class ReActAgentTests(unittest.TestCase):
    def test_runs_tool_call_observation_final_flow(self):
        model = FakeModel(
            [
                ChatResponse(
                    content="",
                    model="fake",
                    finish_reason="tool_calls",
                    tool_calls=[
                        ChatToolCall("call-1", "market_snapshot", {"symbol": "NVDA"})
                    ],
                ),
                "NVDA mock snapshot received; flow is healthy.",
            ]
        )
        agent = ReActAgent(model, build_mock_quant_environment(), max_steps=3)

        result = agent.run("analyze NVDA")

        self.assertIn("flow is healthy", result.final)
        self.assertEqual(result.trace[1]["type"], "tool")
        self.assertEqual(result.trace[1]["output"]["symbol"], "NVDA")
        self.assertEqual(model.calls[1][-1].role, "tool")
        self.assertEqual(model.calls[1][-1].tool_call_id, "call-1")

    def test_emits_step_events_while_running(self):
        model = FakeModel(
            [
                ChatResponse(
                    content="",
                    model="fake",
                    finish_reason="tool_calls",
                    tool_calls=[
                        ChatToolCall("call-1", "market_snapshot", {"symbol": "NVDA"})
                    ],
                ),
                "flow complete.",
            ]
        )
        events = []
        agent = ReActAgent(model, build_mock_quant_environment(), max_steps=3)

        agent.run("analyze NVDA", on_event=lambda event, data: events.append((event, data)))

        names = [event for event, _data in events]
        self.assertEqual(names[0], "run_started")
        self.assertIn("assistant", names)
        self.assertIn("tool_started", names)
        self.assertIn("tool_finished", names)
        self.assertIn("final", names)

    def test_includes_reasoning_content_in_assistant_trace(self):
        model = FakeModel(
            [
                ChatResponse(
                    content="done",
                    model="fake",
                    finish_reason="stop",
                    reasoning_content="visible reasoning",
                ),
            ]
        )
        agent = ReActAgent(model, build_mock_quant_environment(), max_steps=1)

        result = agent.run("think")

        self.assertEqual(result.trace[0]["reasoning_content"], "visible reasoning")

    def test_rejects_empty_model_response_without_tool_calls(self):
        agent = ReActAgent(FakeModel([""]), build_mock_quant_environment())

        with self.assertRaisesRegex(ReActAgentError, "neither content nor tool_calls"):
            agent.run("analyze NVDA")

    def test_stops_when_same_tool_repeats_too_many_times(self):
        model = FakeModel(
            [
                ChatResponse(
                    content="",
                    model="fake",
                    finish_reason="tool_calls",
                    tool_calls=[ChatToolCall("call-1", "market_snapshot", {"symbol": "NVDA"})],
                ),
                ChatResponse(
                    content="",
                    model="fake",
                    finish_reason="tool_calls",
                    tool_calls=[ChatToolCall("call-2", "market_snapshot", {"symbol": "NVDA"})],
                ),
            ]
        )
        agent = ReActAgent(
            model,
            build_mock_quant_environment(),
            max_steps=3,
            max_tool_repeats=1,
        )

        with self.assertRaisesRegex(ReActAgentError, "tool repeated too many times"):
            agent.run("repeat")

    def test_allows_same_tool_for_different_arguments(self):
        model = FakeModel(
            [
                ChatResponse(
                    content="",
                    model="fake",
                    finish_reason="tool_calls",
                    tool_calls=[
                        ChatToolCall("call-1", "market_snapshot", {"symbol": "NVDA"}),
                        ChatToolCall("call-2", "market_snapshot", {"symbol": "SMH"}),
                    ],
                ),
                "different symbols are fine.",
            ]
        )
        agent = ReActAgent(
            model,
            build_mock_quant_environment(),
            max_steps=2,
            max_tool_repeats=1,
        )

        result = agent.run("compare")

        self.assertIn("different symbols", result.final)

    def test_failed_tool_returns_data_missing_observation_after_retry(self):
        calls = []

        def failing_handler(arguments):
            calls.append(arguments)
            raise ValueError("source unavailable")

        environment = ToolEnvironment(
            [
                QuantTool(
                    ToolSpec(
                        "broken_tool",
                        "Always fails for boundary testing.",
                        {"type": "object", "properties": {}, "required": []},
                    ),
                    failing_handler,
                )
            ]
        )
        model = FakeModel(
            [
                ChatResponse(
                    content="",
                    model="fake",
                    finish_reason="tool_calls",
                    tool_calls=[ChatToolCall("call-1", "broken_tool", {})],
                ),
                "fallback observation received.",
            ]
        )
        agent = ReActAgent(model, environment, max_steps=2, tool_retry_limit=1)

        result = agent.run("tool failure")

        self.assertEqual(len(calls), 2)
        self.assertTrue(result.trace[1]["output"]["data_missing"])
        self.assertIn("source unavailable", result.trace[1]["output"]["error"])


if __name__ == "__main__":
    unittest.main()
