import ast
from decimal import Decimal
from io import StringIO
import logging
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.broker.base import (
    BrokerAccountScopeError,
    BrokerConfigurationError,
    BrokerConnectionError,
    BrokerDataTimeoutError,
    OfficialIbapiUnavailableError,
)
from private_quant.broker.ibkr import (
    IbkrBrokerProvider,
    create_official_ibkr_session,
)
from private_quant.broker.models import (
    AccountBalance,
    BrokerOpenOrder,
    BrokerPosition,
    OpenOrdersAvailability,
)


class FakeIbkrSession:
    def __init__(
        self,
        *,
        connected: bool = True,
        account_summary_complete: bool = True,
        positions_complete: bool = True,
        open_orders_complete: bool = True,
        open_orders_wait_error: bool = False,
        multiple_accounts_detected: bool = False,
    ) -> None:
        self.connected = connected
        self.account_summary_complete = account_summary_complete
        self.positions_complete = positions_complete
        self.open_orders_complete = open_orders_complete
        self.open_orders_wait_error = open_orders_wait_error
        self.multiple_accounts_detected = multiple_accounts_detected
        self.calls: list[object] = []
        self.balances = (
            AccountBalance("BuyingPower", Decimal("1000"), "USD"),
            AccountBalance("TotalCashValue", Decimal("250"), "USD"),
        )
        self.positions = (
            BrokerPosition(
                "AAPL", "STK", "USD", Decimal("2"), Decimal("150.25")
            ),
        )
        self.open_orders = (
            BrokerOpenOrder(
                "MSFT",
                "BUY",
                Decimal("1"),
                "LMT",
                Decimal("300"),
                "Submitted",
            ),
        )

    def start(self, host: str, port: int, client_id: int) -> None:
        self.calls.append(("start", host, port, client_id))

    def wait_until_connected(self, timeout: float) -> bool:
        self.calls.append("wait_connected")
        return self.connected

    def request_account_summary(self) -> None:
        self.calls.append("request_account_summary")

    def request_positions(self) -> None:
        self.calls.append("request_positions")

    def request_open_orders(self) -> None:
        self.calls.append("request_open_orders")

    def wait_for_account_summary(self, timeout: float) -> bool:
        self.calls.append("wait_account_summary")
        return self.account_summary_complete

    def wait_for_positions(self, timeout: float) -> bool:
        self.calls.append("wait_positions")
        return self.positions_complete

    def wait_for_open_orders(self, timeout: float) -> bool:
        self.calls.append("wait_open_orders")
        if self.open_orders_wait_error:
            raise RuntimeError("sensitive open-order callback detail")
        return self.open_orders_complete

    def close(self) -> None:
        self.calls.append("close")


def make_provider(session: FakeIbkrSession) -> IbkrBrokerProvider:
    return IbkrBrokerProvider(
        mode="paper",
        host="127.0.0.1",
        port=7497,
        client_id=10,
        session_factory=lambda: session,
        timeout=0.01,
    )


class IbkrBrokerProviderTests(unittest.TestCase):
    def test_refuses_unsafe_settings_before_creating_session(self) -> None:
        cases = (
            {"mode": "live"},
            {"host": "localhost"},
            {"port": 7496},
            {"client_id": 0},
        )

        for override in cases:
            with self.subTest(override=override):
                factory_calls = 0

                def session_factory():
                    nonlocal factory_calls
                    factory_calls += 1
                    return FakeIbkrSession()

                settings = {
                    "mode": "paper",
                    "host": "127.0.0.1",
                    "port": 7497,
                    "client_id": 10,
                }
                settings.update(override)

                with self.assertRaises(BrokerConfigurationError):
                    IbkrBrokerProvider(
                        **settings,
                        session_factory=session_factory,
                    )

                self.assertEqual(factory_calls, 0)

    def test_collects_one_read_only_snapshot_and_closes_session(self) -> None:
        session = FakeIbkrSession()

        snapshot = make_provider(session).get_read_only_snapshot()

        self.assertTrue(snapshot.connected)
        self.assertEqual(snapshot.mode, "paper")
        self.assertEqual(snapshot.balances, session.balances)
        self.assertEqual(snapshot.positions, session.positions)
        self.assertEqual(snapshot.open_orders, session.open_orders)
        self.assertEqual(
            snapshot.open_orders_availability,
            OpenOrdersAvailability.AVAILABLE,
        )
        self.assertEqual(
            session.calls,
            [
                ("start", "127.0.0.1", 7497, 10),
                "wait_connected",
                "request_account_summary",
                "request_positions",
                "request_open_orders",
                "wait_account_summary",
                "wait_positions",
                "wait_open_orders",
                "close",
            ],
        )

    def test_maps_connection_and_required_data_timeouts_and_always_closes(self) -> None:
        cases = (
            (
                FakeIbkrSession(connected=False),
                BrokerConnectionError,
            ),
            (
                FakeIbkrSession(account_summary_complete=False),
                BrokerDataTimeoutError,
            ),
            (
                FakeIbkrSession(positions_complete=False),
                BrokerDataTimeoutError,
            ),
        )

        for session, error_type in cases:
            with self.subTest(error_type=error_type.__name__, calls=session.calls):
                with self.assertRaises(error_type):
                    make_provider(session).get_read_only_snapshot()
                self.assertEqual(session.calls[-1], "close")

    def test_raw_session_failure_is_not_retained_in_exception_chain(self) -> None:
        sentinel = "DU1234567-sensitive-session-detail"

        class FailingSession(FakeIbkrSession):
            def start(self, host: str, port: int, client_id: int) -> None:
                raise RuntimeError(sentinel)

        with self.assertRaises(BrokerConnectionError) as raised:
            make_provider(FailingSession()).get_read_only_snapshot()

        self.assertNotIn(sentinel, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_multiple_account_summary_is_rejected_without_raw_details(self) -> None:
        session = FakeIbkrSession(multiple_accounts_detected=True)

        with self.assertRaises(BrokerAccountScopeError) as raised:
            make_provider(session).get_read_only_snapshot()

        self.assertEqual(
            str(raised.exception),
            "IBKR returned more than one account. Phase 1 supports exactly one "
            "account per TWS session.",
        )
        self.assertNotIn("DU", str(raised.exception))
        self.assertEqual(session.calls[-1], "close")

    def test_open_order_timeout_is_neutral_not_read_only(self) -> None:
        session = FakeIbkrSession(open_orders_complete=False)

        snapshot = make_provider(session).get_read_only_snapshot()

        self.assertEqual(snapshot.balances, session.balances)
        self.assertEqual(snapshot.positions, session.positions)
        self.assertEqual(snapshot.open_orders, ())
        self.assertEqual(
            snapshot.open_orders_availability,
            OpenOrdersAvailability.TIMEOUT,
        )

    def test_open_order_wait_failure_is_neutral_not_read_only(self) -> None:
        session = FakeIbkrSession(open_orders_wait_error=True)

        snapshot = make_provider(session).get_read_only_snapshot()

        self.assertEqual(snapshot.open_orders, ())
        self.assertEqual(
            snapshot.open_orders_availability,
            OpenOrdersAvailability.UNAVAILABLE,
        )

    def test_open_order_property_failure_is_neutral_not_read_only(self) -> None:
        class FailingOpenOrdersSession(FakeIbkrSession):
            @property
            def open_orders(self):
                raise RuntimeError("sensitive open-order property detail")

            @open_orders.setter
            def open_orders(self, value) -> None:
                self._unused_open_orders = value

        snapshot = make_provider(
            FailingOpenOrdersSession()
        ).get_read_only_snapshot()

        self.assertEqual(snapshot.open_orders, ())
        self.assertEqual(
            snapshot.open_orders_availability,
            OpenOrdersAvailability.UNAVAILABLE,
        )

    def test_completed_empty_open_orders_are_available(self) -> None:
        session = FakeIbkrSession()
        session.open_orders = ()

        snapshot = make_provider(session).get_read_only_snapshot()

        self.assertEqual(snapshot.open_orders, ())
        self.assertEqual(
            snapshot.open_orders_availability,
            OpenOrdersAvailability.AVAILABLE,
        )


class OfficialIbkrSessionTests(unittest.TestCase):
    def test_disables_raw_ibapi_debug_logging_before_session_use(self) -> None:
        sentinel = "DU1234567-sensitive-callback-field"
        package_logger = logging.getLogger("ibapi")
        decoder_logger = logging.getLogger("ibapi.decoder")
        original_package_state = (
            package_logger.level,
            package_logger.disabled,
            package_logger.propagate,
            list(package_logger.handlers),
        )
        original_decoder_state = (
            decoder_logger.level,
            decoder_logger.disabled,
            decoder_logger.propagate,
            list(decoder_logger.handlers),
        )

        def restore_logger(logger, state) -> None:
            logger.setLevel(state[0])
            logger.disabled = state[1]
            logger.propagate = state[2]
            logger.handlers[:] = state[3]

        self.addCleanup(restore_logger, package_logger, original_package_state)
        self.addCleanup(restore_logger, decoder_logger, original_decoder_state)

        captured = StringIO()
        handler = logging.StreamHandler(captured)
        decoder_logger.handlers[:] = [handler]
        decoder_logger.setLevel(logging.DEBUG)
        decoder_logger.disabled = False
        decoder_logger.propagate = False

        class FakeWrapper:
            def __init__(self) -> None:
                pass

        class FakeClient:
            def __init__(self, wrapper) -> None:
                self.wrapper = wrapper

        modules = {
            "ibapi.client": SimpleNamespace(EClient=FakeClient),
            "ibapi.wrapper": SimpleNamespace(EWrapper=FakeWrapper),
        }

        create_official_ibkr_session(module_loader=modules.__getitem__)
        decoder_logger.debug("decoded account field: %s", sentinel)

        self.assertNotIn(sentinel, captured.getvalue())

    def test_maps_callbacks_without_retaining_account_or_order_ids(self) -> None:
        sentinel_account = "SENSITIVE-ACCOUNT-ID"
        session = create_official_ibkr_session()
        contract = SimpleNamespace(symbol="AAPL", secType="STK", currency="USD")
        order = SimpleNamespace(
            account=sentinel_account,
            action="BUY",
            totalQuantity=Decimal("3"),
            orderType="LMT",
            lmtPrice=175.5,
        )
        order_state = SimpleNamespace(status="Submitted")

        session.nextValidId(987654)
        session.accountSummary(
            9001, sentinel_account, "BuyingPower", "1234.56", "USD"
        )
        session.position(sentinel_account, contract, Decimal("2"), 150.25)
        session.openOrder(4321, contract, order, order_state)
        session.accountSummaryEnd(9001)
        session.positionEnd()
        session.openOrderEnd()

        self.assertTrue(session.wait_until_connected(0.01))
        self.assertTrue(session.wait_for_account_summary(0.01))
        self.assertTrue(session.wait_for_positions(0.01))
        self.assertTrue(session.wait_for_open_orders(0.01))
        self.assertEqual(
            session.balances,
            (AccountBalance("BuyingPower", Decimal("1234.56"), "USD"),),
        )
        self.assertEqual(
            session.positions,
            (
                BrokerPosition(
                    "AAPL", "STK", "USD", Decimal("2"), Decimal("150.25")
                ),
            ),
        )
        self.assertEqual(
            session.open_orders,
            (
                BrokerOpenOrder(
                    "AAPL",
                    "BUY",
                    Decimal("3"),
                    "LMT",
                    Decimal("175.5"),
                    "Submitted",
                ),
            ),
        )
        sanitized = repr(
            (session.balances, session.positions, session.open_orders)
        )
        self.assertNotIn(sentinel_account, sanitized)
        self.assertNotIn("987654", sanitized)
        self.assertNotIn("4321", sanitized)

    def test_multiple_account_callbacks_fail_without_retaining_identifiers(self) -> None:
        first_account = "DU1111111"
        second_account = "DU2222222"
        session = create_official_ibkr_session()

        session.accountSummary(
            9001, first_account, "BuyingPower", "1000", "USD"
        )
        session.accountSummary(
            9001, first_account, "TotalCashValue", "500", "USD"
        )
        session.accountSummary(
            9001, second_account, "BuyingPower", "2000", "USD"
        )
        session.accountSummary(
            9001, first_account, "BuyingPower", "3000", "USD"
        )
        session.accountSummaryEnd(9001)

        self.assertTrue(session.multiple_accounts_detected)
        self.assertEqual(session.balances, ())
        retained_state = repr(vars(session))
        self.assertNotIn(first_account, retained_state)
        self.assertNotIn(second_account, retained_state)

        with (
            patch.object(session, "start"),
            patch.object(session, "wait_until_connected", return_value=True),
            patch.object(session, "request_account_summary"),
            patch.object(session, "request_positions"),
            patch.object(session, "request_open_orders"),
            patch.object(session, "wait_for_account_summary", return_value=True),
            patch.object(session, "wait_for_positions", return_value=True),
            patch.object(session, "close"),
        ):
            with self.assertRaises(BrokerAccountScopeError) as raised:
                IbkrBrokerProvider(
                    mode="paper",
                    host="127.0.0.1",
                    port=7497,
                    client_id=10,
                    session_factory=lambda: session,
                    timeout=0.01,
                ).get_read_only_snapshot()

        self.assertNotIn(first_account, str(raised.exception))
        self.assertNotIn(second_account, str(raised.exception))

    def test_cleanup_clears_partial_account_scope_state_without_end_callback(self) -> None:
        account = "DU3333333"
        session = create_official_ibkr_session()
        session.accountSummary(9001, account, "BuyingPower", "1000", "USD")

        session.close()
        session.accountSummary(
            9001, "DU4444444", "BuyingPower", "2000", "USD"
        )

        self.assertEqual(session._account_fingerprint_key, b"")
        self.assertIsNone(session._account_fingerprint)
        self.assertEqual(session.balances, ())
        self.assertNotIn(account, repr(vars(session)))

    def test_request_methods_use_only_approved_read_apis(self) -> None:
        session = create_official_ibkr_session()

        with (
            patch.object(session, "reqAccountSummary") as account_summary,
            patch.object(session, "reqPositions") as positions,
            patch.object(session, "reqAllOpenOrders") as open_orders,
        ):
            session.request_account_summary()
            session.request_positions()
            session.request_open_orders()

        account_summary.assert_called_once_with(
            9001, "All", "BuyingPower,TotalCashValue"
        )
        positions.assert_called_once_with()
        open_orders.assert_called_once_with()

    def test_cleanup_attempts_every_step_when_one_step_fails(self) -> None:
        session = create_official_ibkr_session()
        session._account_summary_requested = True
        session._positions_requested = True
        reader_thread = Mock()
        session._reader_thread = reader_thread

        with (
            patch.object(session, "isConnected", return_value=True),
            patch.object(
                session,
                "cancelAccountSummary",
                side_effect=RuntimeError("sensitive cleanup detail"),
            ) as cancel_summary,
            patch.object(session, "cancelPositions") as cancel_positions,
            patch.object(session, "disconnect") as disconnect,
        ):
            session.close()

        cancel_summary.assert_called_once_with(9001)
        cancel_positions.assert_called_once_with()
        disconnect.assert_called_once_with()
        reader_thread.join.assert_called_once_with(timeout=1.0)

    def test_missing_official_package_returns_fixed_setup_error(self) -> None:
        def missing_module(name: str):
            raise ModuleNotFoundError(name)

        with self.assertRaises(OfficialIbapiUnavailableError) as raised:
            create_official_ibkr_session(module_loader=missing_module)

        self.assertIn("official IBKR TWS API", str(raised.exception))
        self.assertNotIn("pip install ibapi", str(raised.exception))


class IbkrSourceSafetyTests(unittest.TestCase):
    def test_production_adapter_has_no_forbidden_order_api_calls(self) -> None:
        source_path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "private_quant"
            / "broker"
            / "ibkr.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        called_methods = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

        self.assertTrue(
            called_methods.isdisjoint(
                {
                    "placeOrder",
                    "reqIds",
                    "cancelOrder",
                    "reqGlobalCancel",
                    "whatIf",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
