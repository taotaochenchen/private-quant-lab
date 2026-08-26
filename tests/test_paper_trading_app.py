import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
import unittest

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.app.paper_trading import (
    build_order_intent,
    order_preview_error_message,
    preview_matches_intent,
)
from private_quant.broker.order_base import (
    InvalidOrderIntentError,
    OrderConnectionError,
    OrderNotionalLimitError,
    OrderQuoteUnavailableError,
    UnsupportedContractError,
)
from private_quant.broker.order_models import (
    OrderIntent,
    OrderPreview,
    OrderSide,
    OrderType,
    QuoteSource,
)


APP_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "private_quant"
    / "app"
    / "paper_trading.py"
)


def make_preview(intent: OrderIntent) -> OrderPreview:
    created_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    return OrderPreview(
        preview_id="opaque-preview-token",
        intent=intent,
        estimated_unit_price=Decimal("190.25"),
        estimated_notional=Decimal("190.25"),
        quote_source=QuoteSource.IBKR_LIVE_ASK,
        created_at=created_at,
        expires_at=created_at + timedelta(seconds=60),
    )


class PaperTradingHelperTests(unittest.TestCase):
    def test_builds_normalized_market_intent_with_default_quantity(self) -> None:
        intent = build_order_intent(
            symbol=" aapl ",
            side="BUY",
            quantity=1,
            order_type="MARKET",
            limit_price=None,
        )

        self.assertEqual(
            intent,
            OrderIntent(
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=1,
                limit_price=None,
            ),
        )

    def test_builds_limit_intent_without_float_rounding(self) -> None:
        intent = build_order_intent(
            symbol="qqq",
            side="SELL",
            quantity=2,
            order_type="LIMIT",
            limit_price="501.25",
        )

        self.assertEqual(intent.limit_price, Decimal("501.25"))
        self.assertEqual(intent.side, OrderSide.SELL)
        self.assertEqual(intent.order_type, OrderType.LIMIT)

    def test_preview_matches_only_the_exact_current_intent(self) -> None:
        original = OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET, 1)
        preview = make_preview(original)

        self.assertTrue(preview_matches_intent(preview, original))
        self.assertFalse(
            preview_matches_intent(
                preview,
                OrderIntent("AAPL", OrderSide.SELL, OrderType.MARKET, 1),
            )
        )

    def test_preview_errors_use_fixed_copy_without_vendor_details(self) -> None:
        sentinel = "DU1234567 secret vendor text"
        cases = (
            InvalidOrderIntentError(sentinel),
            UnsupportedContractError(sentinel),
            OrderQuoteUnavailableError(sentinel),
            OrderNotionalLimitError(sentinel),
            OrderConnectionError(sentinel),
            RuntimeError(sentinel),
        )

        for error in cases:
            with self.subTest(error=type(error).__name__):
                message = order_preview_error_message(error)
                self.assertTrue(message)
                self.assertNotIn(sentinel, message)


class PaperTradingPageTests(unittest.TestCase):
    def test_rendered_preview_shows_source_notional_and_expiry(self) -> None:
        app = AppTest.from_string(
            """
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from private_quant.app.paper_trading import render_order_preview
from private_quant.broker.order_models import (
    OrderIntent, OrderPreview, OrderSide, OrderType, QuoteSource,
)

created_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
render_order_preview(OrderPreview(
    preview_id="opaque-preview-token",
    intent=OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET, 1),
    estimated_unit_price=Decimal("190.25"),
    estimated_notional=Decimal("190.25"),
    quote_source=QuoteSource.IBKR_LIVE_ASK,
    created_at=created_at,
    expires_at=created_at + timedelta(seconds=60),
))
"""
        ).run(timeout=20)

        self.assertEqual(
            [(metric.label, metric.value) for metric in app.metric],
            [
                ("Estimated unit price", "USD 190.25"),
                ("Estimated notional", "USD 190.25"),
                ("Price source", "Fresh IBKR live ask"),
                ("Preview expires", "12:01:00 UTC"),
            ],
        )
        self.assertNotIn("opaque-preview-token", repr(app))
        self.assertEqual(len(app.exception), 0)

    def test_page_starts_in_safe_paper_read_only_state(self) -> None:
        app = AppTest.from_file(str(APP_PATH)).run(timeout=20)

        self.assertEqual(app.title[0].value, "Private Quant Lab — Paper Trading")
        warning_text = " ".join(item.value for item in app.warning)
        self.assertIn("PAPER", warning_text)
        self.assertIn("Read-Only", warning_text)
        self.assertEqual(app.text_input[0].value, "")
        self.assertEqual(app.number_input(key="paper_order_quantity").value, 1)
        self.assertEqual(app.segmented_control(key="paper_order_side").value, "BUY")
        self.assertEqual(
            app.segmented_control(key="paper_order_type").value, "MARKET"
        )
        self.assertEqual(
            app.button(key="paper_order_preview").disabled,
            False,
        )
        self.assertEqual(
            app.button(key="paper_order_submit").disabled,
            True,
        )
        self.assertEqual(len(app.exception), 0)

    def test_market_buffer_is_distinct_from_submit_hard_limit(self) -> None:
        app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
        rendered = " ".join(
            [item.value for item in app.info]
            + [item.value for item in app.caption]
        )

        self.assertIn("USD 950", rendered)
        self.assertIn("MARKET Preview safety buffer", rendered)
        self.assertIn("USD 1,000", rendered)
        self.assertIn("Submit hard limit", rendered)

    def test_limit_selection_shows_limit_price_input(self) -> None:
        app = AppTest.from_file(str(APP_PATH)).run(timeout=20)

        app.segmented_control(key="paper_order_type").set_value("LIMIT").run(
            timeout=20
        )

        self.assertIsNotNone(app.number_input(key="paper_order_limit_price"))
        self.assertEqual(len(app.exception), 0)

    def test_streamlit_page_has_no_submit_order_call_path(self) -> None:
        tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }

        self.assertNotIn("submit_order", called_attributes)


if __name__ == "__main__":
    unittest.main()
