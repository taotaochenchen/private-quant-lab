"""Local Streamlit page for a one-shot, read-only IBKR Paper snapshot."""

from collections.abc import Callable
from decimal import Decimal

import streamlit as st

from private_quant.app.broker_config import (
    BrokerConfiguration,
    build_broker_provider,
    load_broker_configuration,
)
from private_quant.broker.base import (
    BrokerAccountScopeError,
    BrokerConfigurationError,
    BrokerConnectionError,
    BrokerDataTimeoutError,
    BrokerProvider,
    OfficialIbapiUnavailableError,
)
from private_quant.broker.models import BrokerSnapshot, OpenOrdersAvailability


def load_broker_snapshot(
    *,
    configuration_loader: Callable[
        [], BrokerConfiguration
    ] = load_broker_configuration,
    provider_builder: Callable[
        [BrokerConfiguration], BrokerProvider
    ] = build_broker_provider,
) -> BrokerSnapshot:
    """Create a fresh provider and return one bounded, sanitized snapshot."""

    configuration = configuration_loader()
    provider = provider_builder(configuration)
    return provider.get_read_only_snapshot()


def broker_error_message(error: Exception) -> str:
    """Map broker failures to fixed UI copy without reflecting details."""

    if isinstance(error, BrokerConfigurationError):
        return (
            "Paper broker setup is incomplete or unsafe. Check the five "
            "BROKER_* settings in your local .env file."
        )
    if isinstance(error, OfficialIbapiUnavailableError):
        return (
            "The official IBKR TWS Python API is not available in this "
            "environment. Install it from IBKR's official TWS API download."
        )
    if isinstance(error, BrokerConnectionError):
        return (
            "Could not connect to local TWS Paper. Confirm TWS is running, "
            "API socket access is enabled, and client ID 10 is available."
        )
    if isinstance(error, BrokerDataTimeoutError):
        return (
            "TWS connected, but the required read-only account snapshot did "
            "not finish. Please try again."
        )
    if isinstance(error, BrokerAccountScopeError):
        return (
            "More than one IBKR account was returned. Phase 1 requires a "
            "TWS session with exactly one account."
        )
    return (
        "Something went wrong while loading the read-only broker snapshot. "
        "Please try again."
    )


def _format_decimal(value: Decimal) -> str:
    return f"{value:,.2f}"


def _position_rows(snapshot: BrokerSnapshot) -> list[dict[str, str]]:
    return [
        {
            "Symbol": position.symbol,
            "Security type": position.security_type,
            "Currency": position.currency,
            "Quantity": f"{position.quantity:,}",
            "Average cost": _format_decimal(position.average_cost),
        }
        for position in snapshot.positions
    ]


def _open_order_rows(snapshot: BrokerSnapshot) -> list[dict[str, str]]:
    return [
        {
            "Symbol": order.symbol,
            "Side": order.side,
            "Quantity": f"{order.quantity:,}",
            "Order type": order.order_type,
            "Limit price": (
                _format_decimal(order.limit_price)
                if order.limit_price is not None
                else "N/A"
            ),
            "Status": order.status,
        }
        for order in snapshot.open_orders
    ]


def render_broker_snapshot(snapshot: BrokerSnapshot) -> None:
    """Render only account-safe fields from one broker snapshot."""

    with st.container(horizontal=True):
        st.metric(
            "Connection",
            "Connected" if snapshot.connected else "Disconnected",
            border=True,
        )
        st.metric("Mode", "PAPER — configuration enforced", border=True)

    if snapshot.balances:
        with st.container(horizontal=True):
            for balance in snapshot.balances:
                label = {
                    "BuyingPower": "Buying power",
                    "TotalCashValue": "Total cash",
                }.get(balance.name, balance.name)
                st.metric(
                    f"{label} ({balance.currency})",
                    _format_decimal(balance.value),
                    border=True,
                )
    else:
        st.info("No buying power or cash values returned.")

    st.header("Positions")
    if snapshot.positions:
        st.dataframe(_position_rows(snapshot), hide_index=True)
    else:
        st.info("No positions.")

    st.header("Open orders")
    if (
        snapshot.open_orders_availability
        is OpenOrdersAvailability.UNAVAILABLE_READ_ONLY
    ):
        st.warning("Open orders unavailable while TWS Read-Only API is enabled.")
    elif (
        snapshot.open_orders_availability
        is OpenOrdersAvailability.UNAVAILABLE
    ):
        st.warning(
            "Open orders unavailable in the current TWS session. "
            "Read-Only API may be the cause."
        )
    elif snapshot.open_orders_availability is OpenOrdersAvailability.TIMEOUT:
        st.warning(
            "Open orders did not finish loading in the current TWS session. "
            "Read-Only API may be the cause."
        )
    elif snapshot.open_orders:
        st.dataframe(_open_order_rows(snapshot), hide_index=True)
    else:
        st.info("No open orders.")


def main() -> None:
    """Run the local, read-only paper broker page."""

    st.set_page_config(
        page_title="Private Quant Lab — Paper Broker",
        page_icon=":material/account_balance:",
        layout="wide",
    )
    st.title("Private Quant Lab — Paper Broker")
    st.warning("Read-only monitoring only. No order actions are available.")
    st.caption(
        "TWS Paper must be running locally with API socket access and "
        "Read-Only API enabled."
    )

    connect_clicked = st.button(
        "Connect / Refresh",
        type="primary",
        icon=":material/refresh:",
    )
    result_slot = st.container()

    if connect_clicked:
        try:
            with st.spinner("Loading one read-only broker snapshot..."):
                snapshot = load_broker_snapshot()
        except Exception as error:
            with result_slot:
                st.metric("Connection", "Disconnected", border=True)
                st.error(broker_error_message(error))
        else:
            with result_slot:
                render_broker_snapshot(snapshot)


if __name__ == "__main__":
    main()
