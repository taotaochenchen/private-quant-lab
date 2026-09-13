from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.domain import (
    empty_pre_market_report,
    parse_pre_market_report,
    pre_market_report_schema,
)


class PreMarketDomainTests(unittest.TestCase):
    def test_empty_report_matches_top_level_schema_keys(self):
        report = empty_pre_market_report("2026-09-05").to_dict()
        schema = pre_market_report_schema()

        self.assertEqual(report["report_date"], "2026-09-05")
        self.assertEqual(set(schema["required"]), set(report.keys()))
        self.assertEqual(report["risk_review"]["status"], "pending")
        self.assertEqual(report["market_state"]["trading_mode"], "observe")

    def test_schema_defines_core_workbench_sections(self):
        schema = pre_market_report_schema()
        properties = schema["properties"]

        self.assertIn("market_state", properties)
        self.assertIn("industries", properties)
        self.assertIn("stocks", properties)
        self.assertIn("risk_review", properties)
        self.assertIn("trade_plan", properties)
        self.assertIn("evidence_chain", properties)

    def test_schema_requires_quantified_conditions_and_operator_breakdown(self):
        schema = pre_market_report_schema()
        market = schema["properties"]["market_state"]
        stock = schema["properties"]["stocks"]["items"]
        trade_plan = schema["properties"]["trade_plan"]["items"]
        evidence = schema["properties"]["evidence_chain"]["items"]

        self.assertIn("capital_intensity", market["required"])
        self.assertIn("volatility_risk", market["required"])
        self.assertEqual(
            market["properties"]["forbidden_conditions"]["items"]["required"],
            ["expression", "text"],
        )
        self.assertIn("operator_breakdown", stock["required"])
        self.assertIn("roe_ttm", stock["properties"]["operator_breakdown"]["required"])
        self.assertIn("buy_conditions", trade_plan["required"])
        self.assertIn("evidence_id", evidence["required"])

    def test_parse_pre_market_report_accepts_fenced_json(self):
        report = empty_pre_market_report("2026-09-05").to_dict()
        payload = "```json\n{0}\n```".format(__import__("json").dumps(report, ensure_ascii=False))

        parsed = parse_pre_market_report(payload)

        self.assertEqual(parsed["report_date"], "2026-09-05")

    def test_parse_pre_market_report_extracts_json_from_prefixed_text(self):
        report = empty_pre_market_report("2026-09-05").to_dict()
        payload = "下面是报告：\n{0}".format(__import__("json").dumps(report, ensure_ascii=False))

        parsed = parse_pre_market_report(payload)

        self.assertEqual(parsed["headline"], "等待盘前分析")

    def test_parse_pre_market_report_rejects_missing_required_field(self):
        report = empty_pre_market_report("2026-09-05").to_dict()
        del report["risk_review"]

        with self.assertRaisesRegex(ValueError, "risk_review is required"):
            parse_pre_market_report(__import__("json").dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
