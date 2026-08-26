from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.broker.ibkr_orders import (
    MARKET_PREVIEW_SAFETY_BUFFER_LIMIT,
    ORDER_SUBMIT_HARD_LIMIT,
    IbkrPaperOrderExecutor,
    LiveQuote,
    OrderUpdate,
    ResolvedContract,
)
from private_quant.broker.order_base import (
    DuplicateOrderSubmissionError,
    InvalidOrderIntentError,
    OrderConfigurationError,
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
    OrderSide,
    OrderStatus,
    OrderType,
    QuoteSource,
)


FIXED_NOW = datetime(2026, 8, 26, 16, 30, tzinfo=timezone.utc)


class FakeOrderSession:
    def __init__(self) -> None:
        self.connected = True
        self.contracts = (
            ResolvedContract(
                symbol="AAPL",
                con_id=265598,
                security_type="STK",
                exchange="SMART",
                currency="USD",
            ),
        )
        self.quote = LiveQuote(
            market_data_type=1,
            bid=Decimal("99"),
            ask=Decimal("100"),
        )
        self.managed_account_count = 1
        self.next_order_id = 7001
        self.order_update = OrderUpdate(
            broker_status="Submitted",
            filled_quantity=Decimal("0"),
            remaining_quantity=Decimal("1"),
            average_fill_price=None,
            rejected=False,
        )
        self.submissions: list[tuple[object, ...]] = []
        self.calls: list[object] = []

    def start(self, host: str, port: int, client_id: int) -> None:
        self.calls.append(("start", host, port, client_id))

    def wait_until_connected(self, timeout: float) -> bool:
        self.calls.append(("wait_until_connected", timeout))
        return self.connected

    def resolve_contracts(
        self, symbol: str, timeout: float
    ) -> tuple[ResolvedContract, ...]:
        self.calls.append(("resolve_contracts", symbol, timeout))
        return self.contracts

    def request_live_quote(
        self, contract: ResolvedContract, timeout: float
    ) -> LiveQuote:
        self.calls.append(("request_live_quote", contract.symbol, timeout))
        return self.quote

    def wait_for_managed_accounts(self, timeout: float) -> bool:
        self.calls.append(("wait_for_managed_accounts", timeout))
        return True

    def submit_order(
        self,
        order_id: int,
        contract: ResolvedContract,
        intent: OrderIntent,
        order_ref: str,
    ) -> None:
        submission = (order_id, contract, intent, order_ref)
        self.submissions.append(submission)
        self.calls.append(("submit_order", order_id, order_ref))

    def wait_for_order_update(
        self, order_id: int, timeout: float
    ) -> OrderUpdate | None:
        self.calls.append(("wait_for_order_update", order_id, timeout))
        return self.order_update

    def close(self) -> None:
        self.calls.append("close")


def make_executor(
    session: FakeOrderSession,
    *,
    mode: str = "paper",
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 10,
    submission_enabled: bool = False,
    clock=lambda: FIXED_NOW,
) -> IbkrPaperOrderExecutor:
    return IbkrPaperOrderExecutor(
        mode=mode,
        host=host,
        port=port,
        client_id=client_id,
        session_factory=lambda: session,
        clock=clock,
        token_factory=lambda: "preview-1",
        timeout=0.01,
        submission_enabled=submission_enabled,
    )


def make_preview(
    *, preview_id: str = "preview-1", expires_at: datetime | None = None
) -> OrderPreview:
    return OrderPreview(
        preview_id=preview_id,
        intent=OrderIntent(
            "AAPL", OrderSide.BUY, OrderType.LIMIT, limit_price=Decimal("100")
        ),
        estimated_unit_price=Decimal("100"),
        estimated_notional=Decimal("100"),
        quote_source=QuoteSource.USER_LIMIT,
        created_at=FIXED_NOW,
        expires_at=expires_at or FIXED_NOW + timedelta(seconds=60),
    )


class IbkrPaperOrderPreviewTests(unittest.TestCase):
    def test_buy_market_preview_uses_fresh_live_ask_and_default_quantity(self) -> None:
        session = FakeOrderSession()

        preview = make_executor(session).preview_order(
            OrderIntent(
                symbol=" aapl ",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
            )
        )

        self.assertEqual(preview.intent.symbol, "AAPL")
        self.assertEqual(preview.intent.quantity, 1)
        self.assertEqual(preview.estimated_unit_price, Decimal("100"))
        self.assertEqual(preview.estimated_notional, Decimal("100"))
        self.assertIs(preview.quote_source, QuoteSource.IBKR_LIVE_ASK)
        self.assertEqual(preview.created_at, FIXED_NOW)
        self.assertEqual(preview.expires_at, FIXED_NOW + timedelta(seconds=60))
        self.assertEqual(session.calls[-1], "close")

    def test_sell_market_preview_uses_fresh_live_bid(self) -> None:
        session = FakeOrderSession()

        preview = make_executor(session).preview_order(
            OrderIntent(
                symbol="AAPL",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=2,
            )
        )

        self.assertEqual(preview.estimated_unit_price, Decimal("99"))
        self.assertEqual(preview.estimated_notional, Decimal("198"))
        self.assertIs(preview.quote_source, QuoteSource.IBKR_LIVE_BID)

    def test_limit_preview_uses_entered_price_without_market_quote(self) -> None:
        session = FakeOrderSession()

        preview = make_executor(session).preview_order(
            OrderIntent(
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=2,
                limit_price=Decimal("75.25"),
            )
        )

        self.assertEqual(preview.estimated_unit_price, Decimal("75.25"))
        self.assertEqual(preview.estimated_notional, Decimal("150.50"))
        self.assertIs(preview.quote_source, QuoteSource.USER_LIMIT)
        self.assertFalse(
            any(call[0] == "request_live_quote" for call in session.calls if isinstance(call, tuple))
        )

    def test_rejects_unsafe_configuration_before_creating_session(self) -> None:
        unsafe_settings = (
            ("live", "127.0.0.1", 7497, 10),
            ("paper", "localhost", 7497, 10),
            ("paper", "127.0.0.1", 7496, 10),
            ("paper", "127.0.0.1", 7497, 11),
        )

        for mode, host, port, client_id in unsafe_settings:
            with self.subTest(
                mode=mode, host=host, port=port, client_id=client_id
            ):
                factory = Mock()
                with self.assertRaises(OrderConfigurationError):
                    IbkrPaperOrderExecutor(
                        mode=mode,
                        host=host,
                        port=port,
                        client_id=client_id,
                        session_factory=factory,
                    )
                factory.assert_not_called()

    def test_rejects_invalid_ticker_before_session_creation(self) -> None:
        invalid_symbols = ("", "   ", "1AAPL", "AA PL", "AAPL$", "A" * 11)

        for symbol in invalid_symbols:
            with self.subTest(symbol=symbol):
                factory = Mock()
                executor = IbkrPaperOrderExecutor(
                    mode="paper",
                    host="127.0.0.1",
                    port=7497,
                    client_id=10,
                    session_factory=factory,
                )
                with self.assertRaises(InvalidOrderIntentError):
                    executor.preview_order(
                        OrderIntent(
                            symbol=symbol,
                            side=OrderSide.BUY,
                            order_type=OrderType.MARKET,
                        )
                    )
                factory.assert_not_called()

    def test_rejects_non_integer_or_non_positive_quantity(self) -> None:
        invalid_quantities = (True, 0, -1, 1.5, Decimal("1.5"), "1")

        for quantity in invalid_quantities:
            with self.subTest(quantity=quantity):
                session = FakeOrderSession()
                with self.assertRaises(InvalidOrderIntentError):
                    make_executor(session).preview_order(
                        OrderIntent(
                            symbol="AAPL",
                            side=OrderSide.BUY,
                            order_type=OrderType.MARKET,
                            quantity=quantity,  # type: ignore[arg-type]
                        )
                    )
                self.assertEqual(session.calls, [])

    def test_rejects_order_type_and_limit_price_mismatches(self) -> None:
        invalid_intents = (
            OrderIntent(
                "AAPL",
                OrderSide.BUY,
                OrderType.MARKET,
                limit_price=Decimal("100"),
            ),
            OrderIntent("AAPL", OrderSide.BUY, OrderType.LIMIT),
            OrderIntent(
                "AAPL",
                OrderSide.BUY,
                OrderType.LIMIT,
                limit_price=Decimal("0"),
            ),
            OrderIntent(
                "AAPL",
                OrderSide.BUY,
                OrderType.LIMIT,
                limit_price=Decimal("NaN"),
            ),
        )

        for intent in invalid_intents:
            with self.subTest(intent=intent):
                session = FakeOrderSession()
                with self.assertRaises(InvalidOrderIntentError):
                    make_executor(session).preview_order(intent)
                self.assertEqual(session.calls, [])

    def test_rejects_untyped_side_and_order_type_values(self) -> None:
        invalid_intents = (
            OrderIntent(
                "AAPL", "BUY", OrderType.MARKET  # type: ignore[arg-type]
            ),
            OrderIntent(
                "AAPL", OrderSide.BUY, "MARKET"  # type: ignore[arg-type]
            ),
        )

        for intent in invalid_intents:
            with self.subTest(intent=intent):
                session = FakeOrderSession()
                with self.assertRaises(InvalidOrderIntentError):
                    make_executor(session).preview_order(intent)
                self.assertEqual(session.calls, [])

    def test_connection_failure_does_not_retain_raw_exception(self) -> None:
        sentinel = "sensitive broker connection detail"

        class FailingSession(FakeOrderSession):
            def start(self, host: str, port: int, client_id: int) -> None:
                del host, port, client_id
                raise RuntimeError(sentinel)

        with self.assertRaises(OrderConnectionError) as raised:
            make_executor(FailingSession()).preview_order(
                OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET)
            )

        self.assertNotIn(sentinel, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_requires_exactly_one_supported_stk_smart_usd_contract(self) -> None:
        unsupported_sets = (
            (),
            (
                ResolvedContract("AAPL", 1, "STK", "SMART", "USD"),
                ResolvedContract("AAPL", 2, "STK", "SMART", "USD"),
            ),
            (ResolvedContract("AAPL", 0, "STK", "SMART", "USD"),),
            (ResolvedContract("AAPL", 1, "OPT", "SMART", "USD"),),
            (ResolvedContract("AAPL", 1, "STK", "NYSE", "USD"),),
            (ResolvedContract("AAPL", 1, "STK", "SMART", "CAD"),),
        )

        for contracts in unsupported_sets:
            with self.subTest(contracts=contracts):
                session = FakeOrderSession()
                session.contracts = contracts
                with self.assertRaises(UnsupportedContractError):
                    make_executor(session).preview_order(
                        OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET)
                    )
                self.assertEqual(session.calls[-1], "close")

    def test_rejects_delayed_frozen_or_missing_side_quote(self) -> None:
        invalid_quotes = (
            LiveQuote(2, Decimal("99"), Decimal("100")),
            LiveQuote(3, Decimal("99"), Decimal("100")),
            LiveQuote(4, Decimal("99"), Decimal("100")),
            LiveQuote(1, Decimal("99"), None),
            LiveQuote(1, Decimal("99"), Decimal("0")),
            LiveQuote(1, Decimal("99"), Decimal("-1")),
            LiveQuote(1, Decimal("99"), Decimal("NaN")),
            LiveQuote(1, Decimal("99"), Decimal("Infinity")),
        )

        for quote in invalid_quotes:
            with self.subTest(quote=quote):
                session = FakeOrderSession()
                session.quote = quote
                with self.assertRaises(OrderQuoteUnavailableError):
                    make_executor(session).preview_order(
                        OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET)
                    )
                self.assertEqual(session.calls[-1], "close")

    def test_market_preview_safety_buffer_is_distinct_from_submit_hard_limit(self) -> None:
        self.assertEqual(
            MARKET_PREVIEW_SAFETY_BUFFER_LIMIT, Decimal("950")
        )
        self.assertEqual(ORDER_SUBMIT_HARD_LIMIT, Decimal("1000"))

        at_buffer = FakeOrderSession()
        at_buffer.quote = LiveQuote(1, Decimal("949"), Decimal("950"))
        preview = make_executor(at_buffer).preview_order(
            OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET)
        )
        self.assertEqual(preview.estimated_notional, Decimal("950"))

        above_buffer = FakeOrderSession()
        above_buffer.quote = LiveQuote(1, Decimal("949"), Decimal("950.01"))
        with self.assertRaises(OrderNotionalLimitError) as raised:
            make_executor(above_buffer).preview_order(
                OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET)
            )
        self.assertIn("safety buffer", str(raised.exception).lower())
        self.assertIn("USD 1,000", str(raised.exception))

    def test_limit_preview_enforces_submit_hard_limit(self) -> None:
        session = FakeOrderSession()

        with self.assertRaises(OrderNotionalLimitError):
            make_executor(session).preview_order(
                OrderIntent(
                    "AAPL",
                    OrderSide.BUY,
                    OrderType.LIMIT,
                    quantity=2,
                    limit_price=Decimal("500.01"),
                )
            )


class IbkrPaperOrderSubmitTests(unittest.TestCase):
    def test_production_submission_lock_fails_before_session_creation(self) -> None:
        factory = Mock()
        executor = IbkrPaperOrderExecutor(
            mode="paper",
            host="127.0.0.1",
            port=7497,
            client_id=10,
            session_factory=factory,
            submission_enabled=False,
        )

        with self.assertRaises(OrderSubmissionDisabledError):
            executor.submit_order(make_preview())

        factory.assert_not_called()

    def test_submit_requires_preview_issued_by_same_executor(self) -> None:
        session = FakeOrderSession()
        executor = make_executor(session, submission_enabled=True)

        with self.assertRaises(OrderPreviewRequiredError):
            executor.submit_order(make_preview(preview_id="foreign"))

        self.assertEqual(session.calls, [])

    def test_submit_rejects_changed_preview_value(self) -> None:
        session = FakeOrderSession()
        executor = make_executor(session, submission_enabled=True)
        preview = executor.preview_order(make_preview().intent)
        changed = replace(preview, estimated_notional=Decimal("99"))
        calls_after_preview = tuple(session.calls)

        with self.assertRaises(OrderPreviewRequiredError):
            executor.submit_order(changed)

        self.assertEqual(tuple(session.calls), calls_after_preview)

    def test_submit_rejects_expired_preview_before_new_session(self) -> None:
        session = FakeOrderSession()
        current_time = [FIXED_NOW]
        executor = make_executor(
            session,
            submission_enabled=True,
            clock=lambda: current_time[0],
        )
        preview = executor.preview_order(make_preview().intent)
        calls_after_preview = tuple(session.calls)
        current_time[0] = FIXED_NOW + timedelta(seconds=61)

        with self.assertRaises(OrderPreviewExpiredError):
            executor.submit_order(preview)

        self.assertEqual(tuple(session.calls), calls_after_preview)

    def test_duplicate_submit_is_blocked_before_second_broker_call(self) -> None:
        session = FakeOrderSession()
        executor = make_executor(session, submission_enabled=True)
        preview = executor.preview_order(make_preview().intent)

        executor.submit_order(preview)
        calls_after_first_submit = tuple(session.calls)
        with self.assertRaises(DuplicateOrderSubmissionError):
            executor.submit_order(preview)

        self.assertEqual(len(session.submissions), 1)
        self.assertEqual(tuple(session.calls), calls_after_first_submit)

    def test_valid_limit_submit_maps_order_id_and_status(self) -> None:
        session = FakeOrderSession()
        executor = make_executor(session, submission_enabled=True)
        preview = executor.preview_order(make_preview().intent)

        result = executor.submit_order(preview)

        self.assertEqual(result.preview_id, "preview-1")
        self.assertEqual(result.broker_order_id, 7001)
        self.assertIs(result.status, OrderStatus.SUBMITTED)
        self.assertEqual(result.remaining_quantity, Decimal("1"))
        self.assertEqual(len(session.submissions), 1)
        submitted = session.submissions[0]
        self.assertEqual(submitted[0], 7001)
        self.assertEqual(submitted[2], preview.intent)
        self.assertEqual(submitted[3], "preview-1")

    def test_valid_sell_market_submit_requotes_immediately(self) -> None:
        session = FakeOrderSession()
        session.contracts = (
            ResolvedContract("QQQ", 320227571, "STK", "SMART", "USD"),
        )
        session.quote = LiveQuote(1, Decimal("900"), Decimal("901"))
        session.order_update = OrderUpdate(
            broker_status="PreSubmitted",
            filled_quantity=Decimal("0"),
            remaining_quantity=Decimal("1"),
            average_fill_price=None,
            rejected=False,
        )
        executor = make_executor(session, submission_enabled=True)
        preview = executor.preview_order(
            OrderIntent("QQQ", OrderSide.SELL, OrderType.MARKET)
        )
        session.quote = LiveQuote(1, Decimal("999"), Decimal("1000"))

        result = executor.submit_order(preview)

        self.assertIs(result.status, OrderStatus.PRE_SUBMITTED)
        quote_requests = [
            call
            for call in session.calls
            if isinstance(call, tuple) and call[0] == "request_live_quote"
        ]
        self.assertEqual(len(quote_requests), 2)

    def test_market_submit_blocks_fresh_quote_above_hard_limit(self) -> None:
        session = FakeOrderSession()
        session.quote = LiveQuote(1, Decimal("900"), Decimal("900"))
        executor = make_executor(session, submission_enabled=True)
        preview = executor.preview_order(
            OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET)
        )
        session.quote = LiveQuote(1, Decimal("1000"), Decimal("1000.01"))

        with self.assertRaises(OrderNotionalLimitError):
            executor.submit_order(preview)

        self.assertEqual(session.submissions, [])

    def test_submit_requires_exactly_one_managed_account(self) -> None:
        for account_count in (0, 2):
            with self.subTest(account_count=account_count):
                session = FakeOrderSession()
                session.managed_account_count = account_count
                executor = make_executor(session, submission_enabled=True)
                preview = executor.preview_order(make_preview().intent)

                with self.assertRaises(OrderConnectionError) as raised:
                    executor.submit_order(preview)

                self.assertNotIn("DU", str(raised.exception))
                self.assertEqual(session.submissions, [])

    def test_submit_maps_required_broker_statuses(self) -> None:
        cases = (
            ("PendingSubmit", False, OrderStatus.PENDING_SUBMIT),
            ("PreSubmitted", False, OrderStatus.PRE_SUBMITTED),
            ("Submitted", False, OrderStatus.SUBMITTED),
            ("Filled", False, OrderStatus.FILLED),
            ("Cancelled", False, OrderStatus.CANCELLED),
            ("ApiCancelled", False, OrderStatus.CANCELLED),
            ("Inactive", False, OrderStatus.INACTIVE),
            ("unexpected", False, OrderStatus.UNKNOWN),
            ("Inactive", True, OrderStatus.REJECTED),
        )

        for broker_status, rejected, expected in cases:
            with self.subTest(broker_status=broker_status, rejected=rejected):
                session = FakeOrderSession()
                session.order_update = OrderUpdate(
                    broker_status=broker_status,
                    filled_quantity=Decimal("1" if expected is OrderStatus.FILLED else "0"),
                    remaining_quantity=Decimal("0" if expected is OrderStatus.FILLED else "1"),
                    average_fill_price=(
                        Decimal("100.25")
                        if expected is OrderStatus.FILLED
                        else None
                    ),
                    rejected=rejected,
                )
                executor = make_executor(session, submission_enabled=True)
                preview = executor.preview_order(make_preview().intent)

                result = executor.submit_order(preview)

                self.assertIs(result.status, expected)

    def test_submit_raises_safe_timeout_when_no_order_update_arrives(self) -> None:
        session = FakeOrderSession()
        session.order_update = None  # type: ignore[assignment]
        executor = make_executor(session, submission_enabled=True)
        preview = executor.preview_order(make_preview().intent)

        with self.assertRaises(OrderStatusTimeoutError) as raised:
            executor.submit_order(preview)

        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)


if __name__ == "__main__":
    unittest.main()
