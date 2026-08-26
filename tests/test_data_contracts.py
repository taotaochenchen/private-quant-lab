from datetime import date
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.data import BalanceSheetSnapshot, PriceBar, ProviderRegistry


class DataModelTests(unittest.TestCase):
    def test_price_bar_rejects_invalid_low_high(self) -> None:
        with self.assertRaisesRegex(ValueError, "low cannot exceed high"):
            PriceBar(symbol="AAPL", trading_date=date(2026, 8, 25), open=100.0, high=99.0, low=101.0, close=100.0, adjusted_close=100.0, volume=1_000)

    def test_balance_sheet_requires_filing_after_period_end(self) -> None:
        with self.assertRaisesRegex(ValueError, "filed_date cannot be before period_end"):
            BalanceSheetSnapshot(symbol="AAPL", period_end=date(2026, 6, 30), filed_date=date(2026, 6, 1), total_assets=100.0, total_liabilities=50.0)


class ProviderRegistryTests(unittest.TestCase):
    def test_registry_is_case_insensitive(self) -> None:
        registry: ProviderRegistry[object] = ProviderRegistry()
        provider = object()
        registry.register(" Demo ", provider)
        self.assertIs(registry.get("demo"), provider)
        self.assertEqual(registry.names(), ("demo",))

    def test_registry_rejects_duplicate_names(self) -> None:
        registry: ProviderRegistry[object] = ProviderRegistry()
        registry.register("demo", object())
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register("DEMO", object())


if __name__ == "__main__":
    unittest.main()
