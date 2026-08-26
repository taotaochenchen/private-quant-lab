from decimal import Decimal
from pathlib import Path
import sys
import unittest

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.app.broker_status import (
    broker_error_message,
    load_broker_snapshot,
)
from private_quant.broker.base import (
    BrokerAccountScopeError,
    BrokerConfigurationError,
    BrokerConnectionError,
    BrokerDataTimeoutError,
    OfficialIbapiUnavailableError,
)
from private_quant.broker.models import (
    AccountBalance,
    BrokerOpenOrder,
    BrokerPosition,
    BrokerSnapshot,
    OpenOrdersAvailability,
)


def make_snapshot(
    *,
    positions: tuple[BrokerPosition, ...] | None = None,
    open_orders: tuple[BrokerOpenOrder, ...] | None = None,
    availability: OpenOrdersAvailability = OpenOrdersAvailability.AVAILABLE,
) -> BrokerSnapshot:
    return BrokerSnapshot(
        connected=True,
        mode="paper",
        balances=(
            AccountBalance("BuyingPower", Decimal("250000.00"), "CAD"),
            AccountBalance("TotalCashValue", Decimal("125000.50"), "CAD"),
        ),
        positions=(
            BrokerPosition(
                "AAPL", "STK", "USD", Decimal("12"), Decimal("190.25")
            ),
        )
        if positions is None
        else positions,
        open_orders=(
            BrokerOpenOrder(
                "QQQ",
                "BUY",
                Decimal("3"),
                "LMT",
                Decimal("600.00"),
                "Submitted",
            ),
        )
        if open_orders is None
        else open_orders,
        open_orders_availability=availability,
    )


class BrokerStatusHelperTests(unittest.TestCase):
    def test_load_broker_snapshot_uses_injected_configuration_and_provider(self) -> None:
        configuration = object()
        expected = make_snapshot()

        class Provider:
            def get_read_only_snapshot(self) -> BrokerSnapshot:
                return expected

        provider = Provider()

        def build(received_configuration):
            self.assertIs(received_configuration, configuration)
            return provider

        actual = load_broker_snapshot(
            configuration_loader=lambda: configuration,
            provider_builder=build,
        )

        self.assertIs(actual, expected)

    def test_error_messages_are_fixed_and_do_not_reflect_details(self) -> None:
        sentinel = "DU1234567-sensitive-details"
        cases = (
            (
                BrokerConfigurationError(sentinel),
                "Paper broker setup is incomplete or unsafe. Check the five "
                "BROKER_* settings in your local .env file.",
            ),
            (
                OfficialIbapiUnavailableError(sentinel),
                "The official IBKR TWS Python API is not available in this "
                "environment. Install it from IBKR's official TWS API download.",
            ),
            (
                BrokerConnectionError(sentinel),
                "Could not connect to local TWS Paper. Confirm TWS is running, "
                "API socket access is enabled, and client ID 10 is available.",
            ),
            (
                BrokerDataTimeoutError(sentinel),
                "TWS connected, but the required read-only account snapshot did "
                "not finish. Please try again.",
            ),
            (
                BrokerAccountScopeError(sentinel),
                "More than one IBKR account was returned. Phase 1 requires a "
                "TWS session with exactly one account.",
            ),
            (
                RuntimeError(sentinel),
                "Something went wrong while loading the read-only broker snapshot. "
                "Please try again.",
            ),
        )

        for error, expected in cases:
            with self.subTest(error_type=type(error).__name__):
                message = broker_error_message(error)
                self.assertEqual(message, expected)
                self.assertNotIn(sentinel, message)


class BrokerStatusRenderingTests(unittest.TestCase):
    def test_multiple_account_error_display_is_sanitized(self) -> None:
        first_account = "DU1111111"
        second_account = "DU2222222"
        app = AppTest.from_string(
            f"""
import streamlit as st
from private_quant.app.broker_status import broker_error_message
from private_quant.broker.base import BrokerAccountScopeError

st.error(broker_error_message(BrokerAccountScopeError(
    "{first_account} and {second_account}"
)))
"""
        ).run(timeout=20)

        self.assertEqual(
            app.error[0].value,
            "More than one IBKR account was returned. Phase 1 requires a "
            "TWS session with exactly one account.",
        )
        self.assertNotIn(first_account, app.error[0].value)
        self.assertNotIn(second_account, app.error[0].value)
        self.assertEqual(len(app.exception), 0)

    def test_renders_successful_snapshot_without_account_identifiers(self) -> None:
        sentinel = "DU1234567"
        app = AppTest.from_string(
            """
from decimal import Decimal
from private_quant.app.broker_status import render_broker_snapshot
from private_quant.broker.models import (
    AccountBalance, BrokerOpenOrder, BrokerPosition, BrokerSnapshot,
    OpenOrdersAvailability,
)

render_broker_snapshot(BrokerSnapshot(
    connected=True,
    mode="paper",
    balances=(
        AccountBalance("BuyingPower", Decimal("250000.00"), "CAD"),
        AccountBalance("TotalCashValue", Decimal("125000.50"), "CAD"),
    ),
    positions=(BrokerPosition(
        "AAPL", "STK", "USD", Decimal("12"), Decimal("190.25")
    ),),
    open_orders=(BrokerOpenOrder(
        "QQQ", "BUY", Decimal("3"), "LMT", Decimal("600"), "Submitted"
    ),),
    open_orders_availability=OpenOrdersAvailability.AVAILABLE,
))
"""
        ).run(timeout=20)

        self.assertEqual(
            [(metric.label, metric.value) for metric in app.metric],
            [
                ("Connection", "Connected"),
                ("Mode", "PAPER — configuration enforced"),
                ("Buying power (CAD)", "250,000.00"),
                ("Total cash (CAD)", "125,000.50"),
            ],
        )
        self.assertEqual([header.value for header in app.header], ["Positions", "Open orders"])
        self.assertEqual(app.dataframe[0].value.iloc[0]["Symbol"], "AAPL")
        self.assertEqual(app.dataframe[1].value.iloc[0]["Symbol"], "QQQ")
        self.assertEqual(len(app.exception), 0)
        self.assertNotIn(sentinel, repr(app))

    def test_renders_empty_positions_and_open_orders(self) -> None:
        app = AppTest.from_string(
            """
from private_quant.app.broker_status import render_broker_snapshot
from private_quant.broker.models import BrokerSnapshot, OpenOrdersAvailability

render_broker_snapshot(BrokerSnapshot(
    connected=True,
    mode="paper",
    balances=(),
    positions=(),
    open_orders=(),
    open_orders_availability=OpenOrdersAvailability.AVAILABLE,
))
"""
        ).run(timeout=20)

        self.assertEqual(
            [info.value for info in app.info],
            ["No buying power or cash values returned.", "No positions.", "No open orders."],
        )
        self.assertEqual(len(app.exception), 0)

    def test_renders_exact_read_only_open_orders_unavailable_message(self) -> None:
        app = AppTest.from_string(
            """
from private_quant.app.broker_status import render_broker_snapshot
from private_quant.broker.models import BrokerSnapshot, OpenOrdersAvailability

render_broker_snapshot(BrokerSnapshot(
    connected=True,
    mode="paper",
    balances=(),
    positions=(),
    open_orders=(),
    open_orders_availability=OpenOrdersAvailability.UNAVAILABLE_READ_ONLY,
))
"""
        ).run(timeout=20)

        self.assertEqual(len(app.warning), 1)
        self.assertEqual(
            app.warning[0].value,
            "Open orders unavailable while TWS Read-Only API is enabled.",
        )
        self.assertEqual(len(app.exception), 0)

    def test_renders_neutral_open_orders_unavailable_message(self) -> None:
        app = AppTest.from_string(
            """
from private_quant.app.broker_status import render_broker_snapshot
from private_quant.broker.models import BrokerSnapshot, OpenOrdersAvailability

render_broker_snapshot(BrokerSnapshot(
    connected=True,
    mode="paper",
    balances=(),
    positions=(),
    open_orders=(),
    open_orders_availability=OpenOrdersAvailability.UNAVAILABLE,
))
"""
        ).run(timeout=20)

        self.assertEqual(len(app.warning), 1)
        self.assertEqual(
            app.warning[0].value,
            "Open orders unavailable in the current TWS session. "
            "Read-Only API may be the cause.",
        )
        self.assertEqual(len(app.exception), 0)

    def test_renders_neutral_open_orders_timeout_message(self) -> None:
        app = AppTest.from_string(
            """
from private_quant.app.broker_status import render_broker_snapshot
from private_quant.broker.models import BrokerSnapshot, OpenOrdersAvailability

render_broker_snapshot(BrokerSnapshot(
    connected=True,
    mode="paper",
    balances=(),
    positions=(),
    open_orders=(),
    open_orders_availability=OpenOrdersAvailability.TIMEOUT,
))
"""
        ).run(timeout=20)

        self.assertEqual(len(app.warning), 1)
        self.assertEqual(
            app.warning[0].value,
            "Open orders did not finish loading in the current TWS session. "
            "Read-Only API may be the cause.",
        )
        self.assertEqual(len(app.exception), 0)

    def test_page_starts_safe_and_has_only_connect_action(self) -> None:
        app_path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "private_quant"
            / "app"
            / "broker_status.py"
        )
        app = AppTest.from_file(str(app_path)).run(timeout=20)

        self.assertEqual(app.title[0].value, "Private Quant Lab — Paper Broker")
        self.assertEqual(
            app.warning[0].value,
            "Read-only monitoring only. No order actions are available.",
        )
        self.assertEqual([button.label for button in app.button], ["Connect / Refresh"])
        self.assertEqual(len(app.exception), 0)


if __name__ == "__main__":
    unittest.main()
