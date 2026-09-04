from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.models import ChatResponse
from private_quant_lab.web.logging import RequestLogStore
from private_quant_lab.web.server import run_react_request


class FakeModel:
    def __init__(self):
        self.calls = []
        self.responses = [
            'Thought: search first\nAction: web_search\nAction Input: {"query": "NVDA AI demand", "limit": 2}',
            "Final: web search flow complete.",
        ]

    def complete(self, messages, temperature=None, max_tokens=None, extra_body=None):
        self.calls.append(list(messages))
        return ChatResponse(
            content=self.responses.pop(0),
            model="fake",
            finish_reason="stop",
        )


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
        self.assertIn("messages", logs[0])
        self.assertIn("response", logs[0])
        self.assertEqual(logs[0]["response"]["model"], "fake")


if __name__ == "__main__":
    unittest.main()
