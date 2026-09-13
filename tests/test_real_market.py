from pathlib import Path
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.tools.real_market import real_market_snapshot
from private_quant_lab.web.server import run_tool_request


class RealMarketTests(unittest.TestCase):
    def setUp(self):
        self.args = {"market": "CN_A", "indices": ["000300.SH"], "as_of": "2026-09-05T08:45:00+08:00"}
        self.now = datetime(2026, 9, 6, tzinfo=timezone.utc)
        self.bars = [{"date": "2026-09-03", "close": 100, "amount": 1000},
                     {"date": "2026-09-04", "close": 102, "amount": 2000},
                     {"date": "2026-09-05", "close": 900, "amount": 10000}]

    def test_cutoff_change_units_and_source(self):
        result = real_market_snapshot(self.args, lambda *a: self.bars, self.now)
        self.assertFalse(result["is_mock"])
        self.assertEqual(result["missing_fields"], [])
        quote = result["data"]["quotes"][0]
        self.assertEqual(quote["price"], 102)
        self.assertEqual(quote["change_pct"], 2)
        self.assertEqual(quote["turnover_cny"], 2000)
        self.assertEqual(quote["trade_date"], "2026-09-04")

    def test_before_close_uses_prior_day(self):
        self.args["as_of"] = "2026-09-04T14:00:00+08:00"
        result = real_market_snapshot(self.args, lambda *a: self.bars, self.now)
        self.assertTrue(result["missing_fields"])

    def test_partial_failure_is_not_mock(self):
        self.args["indices"].append("000905.SH")
        def fetch(symbol, *a):
            if symbol == "sh000905":
                raise RuntimeError("network unavailable")
            return self.bars
        result = real_market_snapshot(self.args, fetch, self.now)
        self.assertEqual(result["missing_fields"], ["000905.SH"])
        self.assertEqual(len(result["data"]["quotes"]), 1)
        self.assertFalse(result["mock"])

    def test_future_unknown_invalid_numbers(self):
        with self.assertRaises(ValueError):
            real_market_snapshot(dict(self.args, indices=["NVDA"]), now=self.now)
        with self.assertRaises(ValueError):
            real_market_snapshot(dict(self.args, as_of="2027-01-01T00:00:00Z"), now=self.now)
        self.bars[1]["amount"] = float("nan")
        self.assertTrue(real_market_snapshot(self.args, lambda *a: self.bars, self.now)["errors"])

    def test_real_api_bypasses_model_and_propagates_missing(self):
        with patch("private_quant_lab.web.server.real_market_snapshot", return_value={"mock": False, "missing_fields": ["000300.SH"]}):
            with patch("private_quant_lab.web.server._build_models_from_payload", side_effect=AssertionError("no model")):
                result = run_tool_request({"name": "get_market_snapshot", "mode": "real", "arguments": self.args})
        self.assertFalse(result["ok"])
        self.assertFalse(result["result"]["mock"])
