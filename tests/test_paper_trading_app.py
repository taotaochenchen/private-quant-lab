from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
import unittest

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.app.broker_config import BrokerConfiguration
from private_quant.app.paper_trading import (
    attempt_paper_submit,
    build_order_intent,
    load_order_preview,
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


class PreviewingExecutor(FakeExecutor):
    def __init__(self, preview: OrderPreview, result: OrderResult) -> None:
        super().__init__(result)
        self.preview = preview
        self.preview_calls: list[OrderIntent] = []

    def preview_order(self, intent: OrderIntent) -> OrderPreview:
        self.preview_calls.append(intent)
        return self.preview


class PaperTradingHelperTests(unittest.TestCase):
    def test_load_order_preview_returns_the_exact_configuration_gate(self) -> None:
        created_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        intent = OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET, 1)
        preview = make_preview(intent, created_at=created_at)
        result = OrderResult(
            preview.preview_id,
            7001,
            OrderStatus.SUBMITTED,
            Decimal("0"),
            Decimal("1"),
            None,
        )
        executor = PreviewingExecutor(preview, result)
        configuration = BrokerConfiguration(
            provider_name="ibkr",
            mode="paper",
            host="127.0.0.1",
            port=7497,
            client_id=10,
            paper_submit_enabled=True,
        )
        built_from: list[BrokerConfiguration] = []

        actual_executor, actual_preview, configuration_enabled = load_order_preview(
            intent,
            configuration_loader=lambda: configuration,
            executor_builder=lambda received: (built_from.append(received) or executor),
        )

        self.assertIs(actual_executor, executor)
        self.assertIs(actual_preview, preview)
        self.assertEqual(executor.preview_calls, [intent])
        self.assertEqual(built_from, [configuration])
        self.assertTrue(configuration_enabled)

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

    def test_attempt_submit_never_calls_executor_for_a_consumed_preview(self) -> None:
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
            now=created_at,
            configuration_enabled=True,
            operator_confirmed=True,
            consumed=True,
        )

        self.assertTrue(outcome.consumed)
        self.assertIsNone(outcome.result)
        self.assertEqual(
            outcome.error_message,
            "This Preview has already been consumed. Preview again.",
        )
        self.assertEqual(executor.calls, [])

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
    @staticmethod
    def _app_with_fake_preview(
        *, configuration_enabled: bool, submit_fails: bool = False
    ) -> AppTest:
        return AppTest.from_string(
            f'''
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from private_quant.app import paper_trading
from private_quant.broker.order_base import OrderConnectionError
from private_quant.broker.order_models import (
    OrderPreview, OrderResult, OrderStatus, QuoteSource,
)

class FakeExecutor:
    def __init__(self):
        self.calls = []

    def submit_order(self, preview):
        self.calls.append(preview)
        if {submit_fails!r}:
            raise OrderConnectionError("DU1234567 raw broker failure")
        return OrderResult(
            preview_id=preview.preview_id,
            broker_order_id=7001,
            status=OrderStatus.SUBMITTED,
            filled_quantity=Decimal("0"),
            remaining_quantity=Decimal("1"),
            average_fill_price=None,
        )

def fake_load_order_preview(intent):
    now = datetime.now(timezone.utc)
    return (
        FakeExecutor(),
        OrderPreview(
            preview_id="opaque-preview-token",
            intent=intent,
            estimated_unit_price=Decimal("190.25"),
            estimated_notional=Decimal("190.25"),
            quote_source=QuoteSource.IBKR_LIVE_ASK,
            created_at=now,
            expires_at=now + timedelta(seconds=60),
        ),
        {configuration_enabled!r},
    )

paper_trading.load_order_preview = fake_load_order_preview
paper_trading.main()
'''
        ).run(timeout=20)

    @classmethod
    def _preview_with_fake_executor(
        cls, *, configuration_enabled: bool, submit_fails: bool = False
    ) -> AppTest:
        app = cls._app_with_fake_preview(
            configuration_enabled=configuration_enabled,
            submit_fails=submit_fails,
        )
        app.text_input(key="paper_order_symbol").set_value("AAPL").run(timeout=20)
        app.button(key="paper_order_preview").click().run(timeout=20)
        return app

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
        self.assertIn(
            "PAPER ONLY — manual Submit can transmit an order to your IBKR "
            "Paper account. No live trading or automatic execution is available.",
            warning_text,
        )
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
        self.assertFalse(
            app.checkbox(key="paper_order_read_only_confirmation").value
        )
        self.assertEqual(
            app.checkbox(key="paper_order_read_only_confirmation").label,
            "I intentionally disabled Read-Only API in TWS PAPER for this session.",
        )
        rendered = " ".join(item.value for item in app.caption)
        self.assertIn(
            "Operator confirmation only — the app does not automatically detect "
            "the TWS Read-Only setting.",
            rendered,
        )
        self.assertIn(
            "IBKR_PAPER_SUBMIT_ENABLED must be true before creating a "
            "Submit-capable Preview.",
            rendered,
        )
        self.assertEqual(len(app.exception), 0)

    def test_submit_stays_disabled_when_configuration_gate_is_false(self) -> None:
        app = self._preview_with_fake_executor(configuration_enabled=False)

        app.checkbox(key="paper_order_read_only_confirmation").set_value(True).run(
            timeout=20
        )

        self.assertTrue(app.button(key="paper_order_submit").disabled)
        self.assertEqual(len(app.exception), 0)

    def test_submit_stays_disabled_until_operator_confirms_read_only_is_disabled(self) -> None:
        app = self._preview_with_fake_executor(configuration_enabled=True)

        self.assertFalse(app.checkbox(key="paper_order_read_only_confirmation").value)
        self.assertTrue(app.button(key="paper_order_submit").disabled)
        self.assertEqual(len(app.exception), 0)

    def test_exact_preview_with_both_gates_enables_submit(self) -> None:
        app = self._preview_with_fake_executor(configuration_enabled=True)

        app.checkbox(key="paper_order_read_only_confirmation").set_value(True).run(
            timeout=20
        )

        self.assertFalse(app.button(key="paper_order_submit").disabled)
        self.assertEqual(len(app.exception), 0)

    def test_successful_submit_is_one_shot_resets_confirmation_and_clears_stale_state(
        self,
    ) -> None:
        app = self._preview_with_fake_executor(configuration_enabled=True)
        app.checkbox(key="paper_order_read_only_confirmation").set_value(True).run(
            timeout=20
        )

        app.button(key="paper_order_submit").click().run(timeout=20)

        self.assertEqual(
            app.session_state["_paper_order_executor"].calls,
            [app.session_state["_paper_order_preview"]],
        )
        self.assertTrue(app.session_state["_paper_order_preview_consumed"])
        self.assertEqual(
            app.session_state["_paper_order_result"].broker_order_id,
            7001,
        )
        self.assertFalse(
            app.checkbox(key="paper_order_read_only_confirmation").value
        )
        self.assertTrue(app.button(key="paper_order_submit").disabled)

        app.text_input(key="paper_order_symbol").set_value("MSFT").run(timeout=20)

        for state_key in (
            "_paper_order_preview",
            "_paper_order_executor",
            "_paper_order_submit_configuration_enabled",
            "_paper_order_preview_consumed",
            "_paper_order_result",
            "_paper_order_submit_error",
        ):
            self.assertNotIn(state_key, app.session_state)
        self.assertFalse(
            app.checkbox(key="paper_order_read_only_confirmation").value
        )
        self.assertTrue(app.button(key="paper_order_submit").disabled)
        self.assertEqual(len(app.exception), 0)

    def test_failed_submit_consumes_preview_once_and_stores_only_safe_error_copy(
        self,
    ) -> None:
        app = self._preview_with_fake_executor(
            configuration_enabled=True,
            submit_fails=True,
        )
        app.checkbox(key="paper_order_read_only_confirmation").set_value(True).run(
            timeout=20
        )

        app.button(key="paper_order_submit").click().run(timeout=20)

        self.assertEqual(len(app.session_state["_paper_order_executor"].calls), 1)
        self.assertTrue(app.session_state["_paper_order_preview_consumed"])
        self.assertNotIn("_paper_order_result", app.session_state)
        self.assertEqual(
            app.session_state["_paper_order_submit_error"],
            "Could not submit the local TWS PAPER order. Check TWS and try a "
            "new Preview.",
        )
        self.assertNotIn("DU1234567 raw broker failure", repr(app))
        self.assertFalse(
            app.checkbox(key="paper_order_read_only_confirmation").value
        )
        self.assertTrue(app.button(key="paper_order_submit").disabled)
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

if __name__ == "__main__":
    unittest.main()
