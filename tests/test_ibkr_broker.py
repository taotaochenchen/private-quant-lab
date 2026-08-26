from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.broker.base import (
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
    ) -> None:
        self.connected = connected
        self.account_summary_complete = account_summary_complete
        self.positions_complete = positions_complete
        self.open_orders_complete = open_orders_complete
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

    def test_keeps_snapshot_when_open_orders_are_unavailable(self) -> None:
        session = FakeIbkrSession(open_orders_complete=False)

        snapshot = make_provider(session).get_read_only_snapshot()

        self.assertEqual(snapshot.balances, session.balances)
        self.assertEqual(snapshot.positions, session.positions)
        self.assertEqual(snapshot.open_orders, ())
        self.assertEqual(
            snapshot.open_orders_availability,
            OpenOrdersAvailability.UNAVAILABLE_READ_ONLY,
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

    def test_missing_official_package_returns_fixed_setup_error(self) -> None:
        def missing_module(name: str):
            raise ModuleNotFoundError(name)

        with self.assertRaises(OfficialIbapiUnavailableError) as raised:
            create_official_ibkr_session(module_loader=missing_module)

        self.assertIn("official IBKR TWS API", str(raised.exception))
        self.assertNotIn("pip install ibapi", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
