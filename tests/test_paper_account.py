from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.trading import PaperAccount


class PaperAccountTests(unittest.TestCase):
    def setUp(self):
        self.account = PaperAccount("10000", "2026-09-14")

    def test_buy_t1_sell(self):
        buy = self.account.submit("one", "600000.SH", "buy", 100, "10")
        self.assertEqual(buy["filled_quantity"], 0)
        self.assertEqual(self.account.snapshot()["available_cash"], "9000")
        self.account.fill(buy["order_id"], "fill1", 100, "9.90")
        with self.assertRaises(ValueError):
            self.account.submit("sell", "600000.SH", "sell", 100, "10")
        self.account.settle_to("2026-09-15")
        sell = self.account.submit("sell", "600000.SH", "sell", 100, "10")
        self.account.fill(sell["order_id"], "fill2", 100, "10.10")
        self.assertEqual(self.account.snapshot()["positions"]["600000.SH"]["total"], 0)
        self.assertEqual(float(self.account.snapshot()["cash"]), 10020)

    def test_partial_fill_cancel_and_idempotency(self):
        buy = self.account.submit("one", "600000.SH", "buy", 200, "10")
        self.assertEqual(self.account.submit("one", "600000.SH", "buy", 200, "10.00"), buy)
        with self.assertRaises(ValueError):
            self.account.submit("one", "600000.SH", "buy", 100, "10")
        self.account.fill(buy["order_id"], "fill1", 50, "9")
        self.account.cancel(buy["order_id"])
        self.assertEqual(float(self.account.snapshot()["available_cash"]), 9550)
        self.assertEqual(self.account.snapshot()["positions"]["600000.SH"]["total"], 50)
        with self.assertRaises(ValueError):
            self.account.fill(buy["order_id"], "fill1", 50, "9")

    def test_frozen_sell_and_odd_lots(self):
        account = PaperAccount("100", "2026-09-14", {"600000.SH": 150})
        sell = account.submit("a", "600000.SH", "sell", 100, "10")
        with self.assertRaises(ValueError):
            account.submit("b", "600000.SH", "sell", 100, "10")
        account.cancel(sell["order_id"])
        account.submit("all", "600000.SH", "sell", 150, "10")
        self.assertEqual(account.snapshot()["positions"]["600000.SH"]["available"], 0)

    def test_invalid_orders_leave_account_unchanged(self):
        before = self.account.snapshot()
        for symbol, quantity, price in [("688001.SH", 200, "10"), ("600000.SH", 10, "10"),
                                         ("600000.SH", True, "10"), ("600000.SH", 2000, "10"),
                                         ("600000.SH", 100, "NaN"), ("600000.SH", 100, "10.001")]:
            with self.assertRaises(ValueError):
                self.account.submit("bad", symbol, "buy", quantity, price)
            self.assertEqual(self.account.snapshot(), before)

    def test_bad_fill_and_snapshot_isolation(self):
        buy = self.account.submit("a", "600000.SH", "buy", 100, "10")
        with self.assertRaises(ValueError):
            self.account.fill(buy["order_id"], "fill", 100, "11")
        self.account.snapshot()["orders"].clear()
        self.assertEqual(len(self.account.snapshot()["orders"]), 1)
        self.account.settle_to("2026-09-15")
        self.assertEqual(self.account.snapshot()["orders"][0]["status"], "cancelled")
