from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.broker.order_base import PaperOrderExecutionProvider
from private_quant.broker.order_models import (
    OrderIntent,
    OrderPreview,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    QuoteSource,
)


class OrderContractTests(unittest.TestCase):
    def test_order_intent_defaults_quantity_to_one(self) -> None:
        intent = OrderIntent(
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
        )

        self.assertEqual(intent.quantity, 1)
        self.assertIsNone(intent.limit_price)

    def test_models_are_immutable_and_have_no_account_fields(self) -> None:
        created_at = datetime(2026, 8, 26, tzinfo=timezone.utc)
        intent = OrderIntent(
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
        )
        preview = OrderPreview(
            preview_id="preview-1",
            intent=intent,
            estimated_unit_price=Decimal("100"),
            estimated_notional=Decimal("100"),
            quote_source=QuoteSource.IBKR_LIVE_ASK,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=60),
        )
        result = OrderResult(
            preview_id="preview-1",
            broker_order_id=7001,
            status=OrderStatus.FILLED,
            filled_quantity=Decimal("1"),
            remaining_quantity=Decimal("0"),
            average_fill_price=Decimal("100.25"),
        )

        for model in (OrderIntent, OrderPreview, OrderResult):
            field_names = {field.name.lower() for field in fields(model)}
            self.assertFalse(
                any("account" in field_name for field_name in field_names)
            )

        with self.assertRaises(FrozenInstanceError):
            preview.preview_id = "changed"  # type: ignore[misc]
        self.assertEqual(result.broker_order_id, 7001)

    def test_status_values_cover_required_ibkr_outcomes(self) -> None:
        self.assertEqual(
            {status.value for status in OrderStatus},
            {
                "pending_submit",
                "pre_submitted",
                "submitted",
                "filled",
                "cancelled",
                "rejected",
                "inactive",
                "unknown",
            },
        )

    def test_provider_contract_is_framework_independent(self) -> None:
        created_at = datetime(2026, 8, 26, tzinfo=timezone.utc)
        preview = OrderPreview(
            preview_id="preview-1",
            intent=OrderIntent(
                symbol="QQQ",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                limit_price=Decimal("500"),
            ),
            estimated_unit_price=Decimal("500"),
            estimated_notional=Decimal("500"),
            quote_source=QuoteSource.USER_LIMIT,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=60),
        )
        result = OrderResult(
            preview_id="preview-1",
            broker_order_id=7001,
            status=OrderStatus.SUBMITTED,
            filled_quantity=Decimal("0"),
            remaining_quantity=Decimal("1"),
            average_fill_price=None,
        )

        class FakeExecutor:
            def preview_order(self, intent: OrderIntent) -> OrderPreview:
                del intent
                return preview

            def submit_order(self, submitted: OrderPreview) -> OrderResult:
                del submitted
                return result

        provider: PaperOrderExecutionProvider = FakeExecutor()

        self.assertEqual(provider.preview_order(preview.intent), preview)
        self.assertEqual(provider.submit_order(preview), result)


if __name__ == "__main__":
    unittest.main()
