from dataclasses import fields
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.broker.base import BrokerProvider
from private_quant.broker.models import (
    AccountBalance,
    BrokerOpenOrder,
    BrokerPosition,
    BrokerSnapshot,
    OpenOrdersAvailability,
)


class BrokerContractTests(unittest.TestCase):
    def test_open_order_availability_distinguishes_unknown_failures(self) -> None:
        self.assertEqual(
            {status.value for status in OpenOrdersAvailability},
            {
                "available",
                "unavailable",
                "timeout",
                "unavailable_read_only",
            },
        )

    def test_provider_returns_framework_independent_immutable_snapshot(self) -> None:
        snapshot = BrokerSnapshot(
            connected=True,
            mode="paper",
            balances=(AccountBalance("BuyingPower", Decimal("1000"), "USD"),),
            positions=(
                BrokerPosition(
                    "AAPL", "STK", "USD", Decimal("2"), Decimal("150.25")
                ),
            ),
            open_orders=(
                BrokerOpenOrder(
                    "MSFT",
                    "BUY",
                    Decimal("1"),
                    "LMT",
                    Decimal("300"),
                    "Submitted",
                ),
            ),
            open_orders_availability=OpenOrdersAvailability.AVAILABLE,
        )

        class FakeBrokerProvider:
            def get_read_only_snapshot(self) -> BrokerSnapshot:
                return snapshot

        provider: BrokerProvider = FakeBrokerProvider()

        self.assertEqual(provider.get_read_only_snapshot(), snapshot)
        self.assertIsInstance(snapshot.balances, tuple)
        self.assertIsInstance(snapshot.positions, tuple)
        self.assertIsInstance(snapshot.open_orders, tuple)

    def test_domain_models_have_no_account_identifier_fields(self) -> None:
        model_types = (
            AccountBalance,
            BrokerPosition,
            BrokerOpenOrder,
            BrokerSnapshot,
        )

        for model_type in model_types:
            with self.subTest(model_type=model_type.__name__):
                field_names = {field.name.lower() for field in fields(model_type)}
                self.assertNotIn("account", field_names)
                self.assertNotIn("account_id", field_names)
                self.assertFalse(
                    any(name.startswith("account_") for name in field_names)
                )


if __name__ == "__main__":
    unittest.main()
