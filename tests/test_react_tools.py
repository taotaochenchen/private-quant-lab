from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.agents import ReActAgent, ReActAgentError
from private_quant_lab.models import ChatResponse
from private_quant_lab.tools import build_mock_quant_environment, common_quant_tool_names


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, temperature=None, max_tokens=None, extra_body=None):
        self.calls.append(list(messages))
        if not self.responses:
            raise AssertionError("unexpected model call")
        return ChatResponse(
            content=self.responses.pop(0),
            model="fake",
            finish_reason="stop",
        )


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


class ReActAgentTests(unittest.TestCase):
    def test_runs_action_observation_final_flow(self):
        model = FakeModel(
            [
                'Thought: need a quote\nAction: market_snapshot\nAction Input: {"symbol": "NVDA"}',
                "Final: NVDA mock snapshot received; flow is healthy.",
            ]
        )
        agent = ReActAgent(model, build_mock_quant_environment(), max_steps=3)

        result = agent.run("analyze NVDA")

        self.assertIn("flow is healthy", result.final)
        self.assertEqual(result.trace[1]["type"], "tool")
        self.assertEqual(result.trace[1]["output"]["symbol"], "NVDA")
        self.assertIn("Observation:", model.calls[1][-1].content)

    def test_rejects_unparseable_model_response(self):
        agent = ReActAgent(FakeModel(["Thought: unsure"]), build_mock_quant_environment())

        with self.assertRaisesRegex(ReActAgentError, "did not contain"):
            agent.run("analyze NVDA")


if __name__ == "__main__":
    unittest.main()
