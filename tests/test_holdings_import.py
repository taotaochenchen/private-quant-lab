import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.trading.holdings_import import parse_holdings_rows, HoldingsImportError


class HoldingsImportTests(unittest.TestCase):
    def setUp(self):
        self.headers = ["\ufeff证券代码", "\ufeff证券名称", "股份余额", "参考持股", "可用股份", "冻结数量", "成本价", "当前价", "最新市值", "资金账号", "股东代码"]
        self.row = ["000001", "测试证券", "1,000.00", "1000.00", "900.00", 100, "10.1234", "11.20", "11,200.00", "PRIVATE_ACCOUNT", "PRIVATE_HOLDER"]

    def parse(self):
        return parse_holdings_rows([self.headers, self.row])

    def test_text_numbers_and_identity_exclusion(self):
        result = self.parse()
        position = result["positions"][0]
        self.assertEqual(position["security_code"], "000001")
        self.assertEqual(position["quantity"], 1000)
        self.assertEqual(position["available_quantity"], 900)
        self.assertEqual(position["cost_price"], "10.1234")
        self.assertEqual(position["market_value"], "11200.00")
        self.assertIsNone(result["snapshot_at"])
        self.assertFalse(result["execution_ready"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_numeric_code_and_negative_adjusted_cost(self):
        self.row[0], self.row[6] = 1.0, "-0.5000"
        position = self.parse()["positions"][0]
        self.assertEqual(position["security_code"], "000001")
        self.assertEqual(position["cost_price"], "-0.5000")

    def test_invalid_quantities_and_prices_are_not_zeroed(self):
        for index, value in ((2, "NaN"), (2, "1.5"), (4, "--"), (5, -1), (7, "Infinity"), (8, "PRIVATE_BAD_VALUE")):
            original = self.row[index]
            self.row[index] = value
            with self.assertRaises(HoldingsImportError) as context:
                self.parse()
            self.assertNotIn("PRIVATE", str(context.exception))
            self.row[index] = original

    def test_consistency_and_duplicate_rows(self):
        self.row[4] = "1001"
        with self.assertRaises(HoldingsImportError):
            self.parse()
        self.row[4] = "900"
        result = parse_holdings_rows([self.headers, self.row, self.row])
        self.assertEqual(len(result["positions"]), 2)
        self.assertEqual(len(result["warnings"]), 1)

    def test_empty_holdings_require_valid_headers(self):
        self.assertEqual(parse_holdings_rows([self.headers])["positions"], [])
        with self.assertRaises(HoldingsImportError):
            parse_holdings_rows([])
        with self.assertRaises(HoldingsImportError):
            parse_holdings_rows([["证券代码"]])

    def test_duplicate_header_and_reference_fallback(self):
        with self.assertRaises(HoldingsImportError):
            parse_holdings_rows([self.headers + ["证券代码"], self.row + ["000001"]])
        self.headers.pop(2)
        self.row.pop(2)
        self.assertEqual(self.parse()["positions"][0]["quantity"], 1000)
