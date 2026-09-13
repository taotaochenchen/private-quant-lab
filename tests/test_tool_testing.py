from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.web.tool_testing import tool_catalog
from private_quant_lab.web.server import run_tool_request


class ToolTestingTests(unittest.TestCase):
    def test_every_example_runs_without_model_configuration(self):
        with patch("private_quant_lab.web.server._build_models_from_payload", side_effect=AssertionError("unexpected model")):
            for tool in tool_catalog():
                if "local" not in tool["modes"]:
                    continue
                with self.subTest(tool=tool["name"]):
                    result = run_tool_request({"name": tool["name"], "arguments": tool["example"]})
                    self.assertTrue(result["ok"])
                    self.assertTrue(result["result"]["mock"])

    def test_invalid_input_rejected_before_model_call(self):
        with patch("private_quant_lab.web.server._build_models_from_payload", side_effect=AssertionError("unexpected model")):
            for payload in ({"name": "unknown"}, {"name": "get_market_snapshot", "arguments": []},
                            {"name": "market_snapshot", "arguments": {}, "mode": "llm"},
                            {"name": "market_snapshot", "arguments": {"symbol": "NVDA"}, "mode": "real"}):
                with self.assertRaises(ValueError):
                    run_tool_request(payload)

    def test_score_stays_local_in_llm_mode(self):
        tool = next(t for t in tool_catalog() if t["name"] == "compute_market_regime_metrics")
        with patch("private_quant_lab.web.server._build_models_from_payload", side_effect=AssertionError("unexpected model")):
            self.assertTrue(run_tool_request({"name": tool["name"], "arguments": tool["example"], "mode": "llm"})["ok"])
