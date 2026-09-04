from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.models import ChatResponse, ChatToolCall
from private_quant_lab.web.logging import RequestLogStore
from private_quant_lab.web.server import run_react_request


class FakeModel:
    def __init__(self):
        self.calls = []
        self.responses = [
            ChatResponse(
                content="",
                model="fake",
                finish_reason="tool_calls",
                tool_calls=[ChatToolCall("call-1", "web_search", {"query": "NVDA AI demand", "limit": 2})],
            ),
            ChatResponse(
                content="web search flow complete.",
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
        return self.responses.pop(0)


class ReActWebTests(unittest.TestCase):
    def test_run_react_request_returns_trace_and_final(self):
        fake_model = FakeModel()

        with patch("private_quant_lab.web.server.load_model_config", return_value=object()):
            with patch("private_quant_lab.web.server.build_chat_model", return_value=fake_model):
                result = run_react_request(
                    {
                        "task": "test web search",
                        "llm_observation": False,
                        "max_steps": 3,
                        "max_tokens": 400,
                    }
                )

        self.assertEqual(result.final, "web search flow complete.")
        self.assertEqual(result.trace[1]["name"], "web_search")
        self.assertEqual(result.trace[1]["output"]["query"], "NVDA AI demand")

    def test_thinking_mode_uses_deepseek_reasoner_by_default(self):
        fake_model = FakeModel()
        model_names = []

        def fake_load_model_config(**kwargs):
            model_names.append(kwargs["model_name"])
            return object()

        with patch("private_quant_lab.web.server.load_model_config", side_effect=fake_load_model_config):
            with patch("private_quant_lab.web.server.build_chat_model", return_value=fake_model):
                run_react_request(
                    {
                        "task": "test reasoning",
                        "model": "deepseek-chat",
                        "thinking_mode": True,
                        "llm_observation": False,
                        "max_steps": 3,
                        "max_tokens": 400,
                    }
                )

        self.assertEqual(model_names[0], "deepseek-reasoner")

    def test_run_react_request_records_raw_model_logs(self):
        fake_model = FakeModel()
        log_store = RequestLogStore()

        with patch("private_quant_lab.web.server.load_model_config", return_value=object()):
            with patch("private_quant_lab.web.server.build_chat_model", return_value=fake_model):
                run_react_request(
                    {
                        "task": "test web search",
                        "llm_observation": False,
                        "max_steps": 3,
                        "max_tokens": 400,
                    },
                    run_id="run-test",
                    log_store=log_store,
                )

        logs = log_store.list(run_id="run-test")

        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0]["purpose"], "agent")
        self.assertEqual(logs[0]["parameters"]["max_tokens"], 400)
        self.assertEqual(logs[0]["parameters"]["tool_choice"], "auto")
        self.assertTrue(logs[0]["tools"])
        self.assertIn("messages", logs[0])
        self.assertIn("response", logs[0])
        self.assertEqual(logs[0]["response"]["model"], "fake")


if __name__ == "__main__":
    unittest.main()
