import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
import unittest

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.app.paper_trading import (
    attempt_paper_submit,
    build_order_intent,
    order_submit_error_message,
    order_preview_error_message,
    preview_matches_intent,
    preview_is_submittable,
    render_order_result,
    submit_help_text,
    submit_paper_order,
)
from private_quant.broker.base import OfficialIbapiUnavailableError
from private_quant.broker.order_base import (
    DuplicateOrderSubmissionError,
    InvalidOrderIntentError,
    OrderConnectionError,
    OrderNotionalLimitError,
    OrderPreviewExpiredError,
    OrderPreviewRequiredError,
    OrderQuoteUnavailableError,
    OrderStatusTimeoutError,
    OrderSubmissionDisabledError,
    UnsupportedContractError,
)
from private_quant.broker.order_models import (
    OrderIntent,
    OrderPreview,
    OrderResult,
    OrderSide,
    OrderStatus,
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


def make_preview(
    intent: OrderIntent, *, created_at: datetime
) -> OrderPreview:
    return OrderPreview(
        preview_id="opaque-preview-token",
        intent=intent,
        estimated_unit_price=Decimal("190.25"),
        estimated_notional=Decimal("190.25"),
        quote_source=QuoteSource.IBKR_LIVE_ASK,
        created_at=created_at,
        expires_at=created_at + timedelta(seconds=60),
    )


class FakeExecutor:
    def __init__(self, result: OrderResult) -> None:
        self.result = result
        self.calls: list[OrderPreview] = []

    def preview_order(self, intent: OrderIntent) -> OrderPreview:
        raise AssertionError("Preview is outside this fake's test boundary")

    def submit_order(self, preview: OrderPreview) -> OrderResult:
        self.calls.append(preview)
        return self.result


class FailingExecutor:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls: list[OrderPreview] = []

    def preview_order(self, intent: OrderIntent) -> OrderPreview:
        raise AssertionError("Preview is outside this fake's test boundary")

    def submit_order(self, preview: OrderPreview) -> OrderResult:
        self.calls.append(preview)
        raise self.error


class PaperTradingHelperTests(unittest.TestCase):
    def test_submit_eligibility_requires_every_gate(self) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        intent = OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET, 1)
        preview = make_preview(intent, created_at=now)

        cases = (
            ({"configuration_enabled": False}, False),
            ({"operator_confirmed": False}, False),
            ({"preview": None}, False),
            ({"intent": replace(intent, side=OrderSide.SELL)}, False),
            ({"now": preview.expires_at}, False),
            ({"consumed": True}, False),
            ({}, True),
        )
        defaults = {
            "preview": preview,
            "intent": intent,
            "now": now,
            "configuration_enabled": True,
            "operator_confirmed": True,
            "consumed": False,
        }

        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                values = defaults | overrides
                self.assertIs(preview_is_submittable(**values), expected)

    def test_submit_eligibility_rejects_naive_time(self) -> None:
        created_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        intent = OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET, 1)

        eligible = preview_is_submittable(
            make_preview(intent, created_at=created_at),
            intent,
            now=datetime(2026, 8, 26, 12, 0),
            configuration_enabled=True,
            operator_confirmed=True,
            consumed=False,
        )

        self.assertFalse(eligible)

    def test_submit_help_text_reports_the_first_unmet_gate(self) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        intent = OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET, 1)
        preview = make_preview(intent, created_at=now)
        raw_configuration_value = "IBKR_PAPER_SUBMIT_ENABLED=true"
        cases = (
            (
                {"configuration_enabled": False},
                "Local PAPER Submit gate is disabled. Enable it and Preview again.",
            ),
            (
                {"operator_confirmed": False},
                "Confirm that you intentionally disabled TWS Read-Only API.",
            ),
            (
                {"preview": None},
                "Preview this exact ticket before Submit.",
            ),
            (
                {"intent": replace(intent, side=OrderSide.SELL)},
                "Preview this exact ticket before Submit.",
            ),
            (
                {"now": preview.expires_at},
                "This Preview has expired. Preview the ticket again.",
            ),
            (
                {"consumed": True},
                "This Preview has already been consumed. Preview again.",
            ),
            ({}, "Ready for one manual IBKR PAPER Submit."),
        )
        defaults = {
            "preview": preview,
            "intent": intent,
            "now": now,
            "configuration_enabled": True,
            "operator_confirmed": True,
            "consumed": False,
        }

        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                message = submit_help_text(**(defaults | overrides))
                self.assertEqual(message, expected)
                self.assertNotIn(raw_configuration_value, message)

    def test_submit_helper_calls_executor_once_and_returns_result(self) -> None:
        created_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        preview = make_preview(
            OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET, 1),
            created_at=created_at,
        )
        expected = OrderResult(
            preview_id=preview.preview_id,
            broker_order_id=7001,
            status=OrderStatus.SUBMITTED,
            filled_quantity=Decimal("0"),
            remaining_quantity=Decimal("1"),
            average_fill_price=None,
        )
        executor = FakeExecutor(expected)

        actual = submit_paper_order(executor, preview)

        self.assertIs(actual, expected)
        self.assertEqual(executor.calls, [preview])

    def test_submit_errors_use_fixed_copy_without_broker_details(self) -> None:
        sentinel = "DU1234567 secret vendor text"
        cases = (
            (
                OrderSubmissionDisabledError(sentinel),
                "PAPER Submit is disabled by the local safety gate.",
            ),
            (
                OrderPreviewRequiredError(sentinel),
                "Preview this exact ticket before Submit.",
            ),
            (
                OrderPreviewExpiredError(sentinel),
                "This Preview has expired. Preview the ticket again.",
            ),
            (
                DuplicateOrderSubmissionError(sentinel),
                "This Preview has already been consumed. Preview again.",
            ),
            (
                OrderQuoteUnavailableError(sentinel),
                "A current IBKR quote was unavailable. Preview the ticket again.",
            ),
            (
                OrderNotionalLimitError(sentinel),
                "This order is above the PAPER Submit safety limit.",
            ),
            (
                OrderConnectionError(sentinel),
                "Could not submit the local TWS PAPER order. Check TWS and try a new Preview.",
            ),
            (
                OrderStatusTimeoutError(sentinel),
                "The PAPER order response timed out. Check TWS before trying again.",
            ),
            (
                OfficialIbapiUnavailableError(sentinel),
                "The official IBKR TWS Python API is unavailable in this environment.",
            ),
            (
                RuntimeError(sentinel),
                "The PAPER order could not be submitted. Preview again before retrying.",
            ),
        )

        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                message = order_submit_error_message(error)
                self.assertEqual(message, expected)
                self.assertNotIn(sentinel, message)

    def test_attempt_submit_rejects_expired_preview_without_executor_call(self) -> None:
        created_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        intent = OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET, 1)
        preview = make_preview(intent, created_at=created_at)
        executor = FakeExecutor(
            OrderResult(
                preview.preview_id,
                7001,
                OrderStatus.SUBMITTED,
                Decimal("0"),
                Decimal("1"),
                None,
            )
        )

        outcome = attempt_paper_submit(
            executor,
            preview,
            intent,
            now=preview.expires_at,
            configuration_enabled=True,
            operator_confirmed=True,
            consumed=False,
        )

        self.assertEqual(
            outcome.error_message,
            "This Preview has expired. Preview the ticket again.",
        )
        self.assertFalse(outcome.consumed)
        self.assertIsNone(outcome.result)
        self.assertEqual(executor.calls, [])

    def test_attempt_submit_rejects_false_gate_without_executor_call(self) -> None:
        created_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        intent = OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET, 1)
        preview = make_preview(intent, created_at=created_at)
        executor = FakeExecutor(
            OrderResult(
                preview.preview_id,
                7001,
                OrderStatus.SUBMITTED,
                Decimal("0"),
                Decimal("1"),
                None,
            )
        )

        for configuration_enabled, operator_confirmed, expected in (
            (
                False,
                True,
                "Local PAPER Submit gate is disabled. Enable it and Preview again.",
            ),
            (
                True,
                False,
                "Confirm that you intentionally disabled TWS Read-Only API.",
            ),
        ):
            with self.subTest(
                configuration_enabled=configuration_enabled,
                operator_confirmed=operator_confirmed,
            ):
                outcome = attempt_paper_submit(
                    executor,
                    preview,
                    intent,
                    now=created_at,
                    configuration_enabled=configuration_enabled,
                    operator_confirmed=operator_confirmed,
                    consumed=False,
                )
                self.assertEqual(outcome.error_message, expected)
                self.assertFalse(outcome.consumed)
                self.assertIsNone(outcome.result)

        self.assertEqual(executor.calls, [])

    def test_attempt_submit_consumes_preview_after_one_successful_call(self) -> None:
        created_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        intent = OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET, 1)
        preview = make_preview(intent, created_at=created_at)
        expected = OrderResult(
            preview.preview_id,
            7001,
            OrderStatus.SUBMITTED,
            Decimal("0"),
            Decimal("1"),
            None,
        )
        executor = FakeExecutor(expected)

        outcome = attempt_paper_submit(
            executor,
            preview,
            intent,
            now=created_at,
            configuration_enabled=True,
            operator_confirmed=True,
            consumed=False,
        )

        self.assertTrue(outcome.consumed)
        self.assertIs(outcome.result, expected)
        self.assertIsNone(outcome.error_message)
        self.assertEqual(executor.calls, [preview])

    def test_attempt_submit_consumes_preview_after_executor_failure(self) -> None:
        created_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        intent = OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET, 1)
        preview = make_preview(intent, created_at=created_at)
        executor = FailingExecutor(OrderConnectionError("DU1234567 raw failure"))

        outcome = attempt_paper_submit(
            executor,
            preview,
            intent,
            now=created_at,
            configuration_enabled=True,
            operator_confirmed=True,
            consumed=False,
        )

        self.assertTrue(outcome.consumed)
        self.assertIsNone(outcome.result)
        self.assertEqual(
            outcome.error_message,
            "Could not submit the local TWS PAPER order. Check TWS and try a new Preview.",
        )
        self.assertEqual(executor.calls, [preview])

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
        preview = make_preview(
            original,
            created_at=datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
        )

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
    def test_rendered_order_result_exposes_only_sanitized_fields(self) -> None:
        sentinel = "DU1234567 raw broker account detail"
        cases = (
            (OrderStatus.FILLED, "Filled"),
            (OrderStatus.CANCELLED, "Cancelled"),
            (OrderStatus.REJECTED, "Rejected"),
            (OrderStatus.INACTIVE, "Inactive"),
            (OrderStatus.UNKNOWN, "Unknown"),
        )

        for status, status_label in cases:
            with self.subTest(status=status):
                app = AppTest.from_string(
                    f'''
from decimal import Decimal
from private_quant.app.paper_trading import render_order_result
from private_quant.broker.order_models import OrderResult, OrderStatus

raw_broker_detail = "{sentinel}"
render_order_result(OrderResult(
    preview_id="opaque-preview-token",
    broker_order_id=7001,
    status=OrderStatus.{status.name},
    filled_quantity=Decimal("1"),
    remaining_quantity=Decimal("0"),
    average_fill_price=Decimal("100.25"),
))
'''
                ).run(timeout=20)

                self.assertEqual(
                    [(metric.label, metric.value) for metric in app.metric],
                    [
                        ("Status", status_label),
                        ("Broker order ID", "7001"),
                        ("Filled", "1"),
                        ("Remaining", "0"),
                        ("Average fill price", "USD 100.25"),
                    ],
                )
                rendered_values = " ".join(
                    [item.value for item in app.success]
                    + [metric.value for metric in app.metric]
                )
                self.assertNotIn(sentinel, rendered_values)
                self.assertNotIn("opaque-preview-token", rendered_values)
                self.assertEqual(len(app.exception), 0)

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
                ("Price source", "IBKR live ask — new snapshot request"),
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

    def test_page_distinguishes_snapshot_request_live_type_and_quote_age(self) -> None:
        app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
        rendered = " ".join(
            [item.value for item in app.info]
            + [item.value for item in app.caption]
        )

        self.assertIn("Snapshot request: new for each MARKET Preview", rendered)
        self.assertIn("Market-data type: IBKR live (type 1)", rendered)
        self.assertIn(
            "Quote age: unavailable and not independently verified",
            rendered,
        )

    def test_quote_unavailable_message_does_not_claim_age_verification(self) -> None:
        message = order_preview_error_message(
            OrderQuoteUnavailableError("raw broker detail")
        )

        self.assertEqual(
            message,
            "A valid bid or ask was unavailable from the newly requested "
            "IBKR live snapshot. MARKET Preview is blocked; no fallback "
            "price will be used.",
        )

    def test_limit_selection_shows_limit_price_input(self) -> None:
        app = AppTest.from_file(str(APP_PATH)).run(timeout=20)

        app.segmented_control(key="paper_order_type").set_value("LIMIT").run(
            timeout=20
        )

        self.assertIsNotNone(app.number_input(key="paper_order_limit_price"))
        self.assertEqual(len(app.exception), 0)

    def test_streamlit_page_has_no_submit_order_call_path(self) -> None:
        tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        main = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        called_attributes = {
            node.func.attr
            for node in ast.walk(main)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }

        self.assertNotIn("submit_order", called_attributes)


if __name__ == "__main__":
    unittest.main()
