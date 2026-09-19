from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.web.tool_testing import tool_catalog, snowball_config_status
from private_quant_lab.tools.snowball_adapter import SnowballSettings, SnowballError
from private_quant_lab.web.server import run_tool_request


class ToolTestingTests(unittest.TestCase):
    def test_snowball_configuration_exposes_only_safe_status(self):
        config = SnowballSettings(content_permission_confirmed=True)
        config.set_token("xq_a_token=TEST_PRIVATE_TOKEN")
        with patch("private_quant_lab.web.tool_testing.load_snowball_settings", return_value=config):
            self.assertEqual(snowball_config_status(), {
                "status": "ok", "token_configured": True,
                "content_permission_confirmed": True, "timeout_seconds": 35})
        with patch("private_quant_lab.web.tool_testing.load_snowball_settings",
                   side_effect=SnowballError("TEST_PRIVATE_TOKEN")):
            self.assertEqual(snowball_config_status(), {"status": "invalid_configuration"})

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
