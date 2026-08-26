"""Streamlit PAPER order Preview ticket with submission hard-disabled."""

from collections.abc import Callable
from decimal import Decimal, InvalidOperation

import streamlit as st

from private_quant.app.broker_config import (
    BrokerConfiguration,
    build_paper_order_executor,
    load_broker_configuration,
)
from private_quant.broker.base import (
    BrokerConfigurationError,
    OfficialIbapiUnavailableError,
)
from private_quant.broker.ibkr_orders import (
    MARKET_PREVIEW_SAFETY_BUFFER_LIMIT,
    ORDER_SUBMIT_HARD_LIMIT,
)
from private_quant.broker.order_base import (
    InvalidOrderIntentError,
    OrderConfigurationError,
    OrderConnectionError,
    OrderNotionalLimitError,
    OrderQuoteUnavailableError,
    PaperOrderExecutionProvider,
    UnsupportedContractError,
)
from private_quant.broker.order_models import (
    OrderIntent,
    OrderPreview,
    OrderSide,
    OrderType,
    QuoteSource,
)

_PREVIEW_STATE_KEY = "_paper_order_preview"
_EXECUTOR_STATE_KEY = "_paper_order_executor"


def build_order_intent(
    *,
    symbol: str,
    side: str,
    quantity: int,
    order_type: str,
    limit_price: object | None,
) -> OrderIntent:
    """Translate ticket values into a provider-independent order intent."""

    decimal_limit = None
    if order_type == OrderType.LIMIT.value and limit_price is not None:
        try:
            decimal_limit = Decimal(str(limit_price))
        except (InvalidOperation, TypeError, ValueError):
            decimal_limit = None
    return OrderIntent(
        symbol=symbol.strip().upper(),
        side=OrderSide(side),
        order_type=OrderType(order_type),
        quantity=quantity,
        limit_price=decimal_limit,
    )


def preview_matches_intent(
    preview: OrderPreview | None, intent: OrderIntent
) -> bool:
    """Return whether a Preview is bound to the exact current ticket."""

    return preview is not None and preview.intent == intent


def order_preview_error_message(error: Exception) -> str:
    """Map failures to fixed UI copy without reflecting broker details."""

    if isinstance(error, (BrokerConfigurationError, OrderConfigurationError)):
        return (
            "Paper broker setup is incomplete or unsafe. Check the five "
            "BROKER_* settings in your local .env file."
        )
    if isinstance(error, OfficialIbapiUnavailableError):
        return (
            "The official IBKR TWS Python API is unavailable in this "
            "environment. Install it from IBKR's official TWS API download."
        )
    if isinstance(error, InvalidOrderIntentError):
        return "Enter a valid US stock or ETF order and try Preview again."
    if isinstance(error, UnsupportedContractError):
        return (
            "IBKR could not confirm one unique US stock or ETF for this "
            "symbol."
        )
    if isinstance(error, OrderQuoteUnavailableError):
        return (
            "A valid bid or ask was unavailable from the newly requested "
            "IBKR live snapshot. MARKET Preview is blocked; no fallback "
            "price will be used."
        )
    if isinstance(error, OrderNotionalLimitError):
        return (
            "This order is above its PAPER safety threshold. MARKET Preview "
            "allows up to USD 950; the Submit hard limit is USD 1,000."
        )
    if isinstance(error, OrderConnectionError):
        return (
            "Could not complete the local TWS Paper Preview. Confirm TWS is "
            "running with API socket access enabled."
        )
    return "The PAPER order Preview could not be completed. Please try again."


def load_order_preview(
    intent: OrderIntent,
    *,
    configuration_loader: Callable[
        [], BrokerConfiguration
    ] = load_broker_configuration,
    executor_builder: Callable[
        [BrokerConfiguration], PaperOrderExecutionProvider
    ] = build_paper_order_executor,
) -> tuple[PaperOrderExecutionProvider, OrderPreview]:
    """Create a fresh locked executor and request one broker Preview."""

    configuration = configuration_loader()
    executor = executor_builder(configuration)
    return executor, executor.preview_order(intent)


def _format_money(value: Decimal) -> str:
    return f"USD {value:,.2f}"


def _quote_source_label(source: QuoteSource) -> str:
    return {
        QuoteSource.IBKR_LIVE_ASK: "IBKR live ask — new snapshot request",
        QuoteSource.IBKR_LIVE_BID: "IBKR live bid — new snapshot request",
        QuoteSource.USER_LIMIT: "Entered limit price",
    }[source]


def render_order_preview(preview: OrderPreview) -> None:
    """Render the safe fields from one short-lived Preview."""

    st.success("Preview ready. It applies only to this exact ticket and expires shortly.")
    with st.container(horizontal=True):
        st.metric("Estimated unit price", _format_money(preview.estimated_unit_price), border=True)
        st.metric("Estimated notional", _format_money(preview.estimated_notional), border=True)
        st.metric("Price source", _quote_source_label(preview.quote_source), border=True)
        st.metric(
            "Preview expires",
            preview.expires_at.strftime("%H:%M:%S UTC"),
            border=True,
        )
    st.caption(
        "MARKET estimates use only the bid or ask returned by the new IBKR "
        "live snapshot request for this Preview. The callback has no quote "
        "timestamp, so price age is not independently verified. Actual "
        "market fills can be higher or lower."
    )


def _clear_stale_preview(intent: OrderIntent) -> None:
    preview = st.session_state.get(_PREVIEW_STATE_KEY)
    if preview is not None and not preview_matches_intent(preview, intent):
        st.session_state.pop(_PREVIEW_STATE_KEY, None)
        st.session_state.pop(_EXECUTOR_STATE_KEY, None)


def main() -> None:
    """Run the local PAPER-only order Preview page."""

    st.set_page_config(
        page_title="Private Quant Lab — Paper Trading",
        page_icon=":material/receipt_long:",
        layout="wide",
    )
    st.title("Private Quant Lab — Paper Trading")
    st.warning(
        "PAPER only. TWS Read-Only API stays enabled, so order submission "
        "is unavailable in this phase."
    )
    st.caption(
        "No live trading, automatic execution, order staging, preview at "
        "TWS, cancellation, or transmission is available."
    )
    st.caption(
        "MARKET quote checks — Snapshot request: new for each MARKET "
        "Preview. Market-data type: IBKR live (type 1). Quote age: "
        "unavailable and not independently verified because the snapshot "
        "bid/ask callback has no timestamp."
    )

    st.subheader("Paper order ticket")
    with st.container(border=True):
        symbol = st.text_input(
            "Symbol",
            placeholder="AAPL, NVDA, MSFT, or QQQ",
            key="paper_order_symbol",
        )
        side = st.segmented_control(
            "Side",
            options=[OrderSide.BUY.value, OrderSide.SELL.value],
            default=OrderSide.BUY.value,
            key="paper_order_side",
        )
        quantity = st.number_input(
            "Quantity",
            min_value=1,
            value=1,
            step=1,
            key="paper_order_quantity",
        )
        order_type = st.segmented_control(
            "Order type",
            options=[OrderType.MARKET.value, OrderType.LIMIT.value],
            default=OrderType.MARKET.value,
            key="paper_order_type",
        )
        limit_price = None
        if order_type == OrderType.LIMIT.value:
            limit_price = st.number_input(
                "Limit price (USD)",
                min_value=0.01,
                value=None,
                step=0.01,
                format="%.2f",
                key="paper_order_limit_price",
            )

        st.info(
            f"USD {MARKET_PREVIEW_SAFETY_BUFFER_LIMIT:,.0f} is the named "
            "MARKET Preview safety buffer. It leaves room for price movement "
            f"below the separate USD {ORDER_SUBMIT_HARD_LIMIT:,.0f} Submit "
            "hard limit; USD 950 is not the Submit limit."
        )
        preview_clicked = st.button(
            "Preview",
            type="primary",
            icon=":material/visibility:",
            key="paper_order_preview",
        )

    try:
        intent = build_order_intent(
            symbol=symbol,
            side=side or OrderSide.BUY.value,
            quantity=int(quantity),
            order_type=order_type or OrderType.MARKET.value,
            limit_price=limit_price,
        )
    except (TypeError, ValueError):
        intent = OrderIntent("", OrderSide.BUY, OrderType.MARKET, 1)

    _clear_stale_preview(intent)
    if preview_clicked:
        try:
            with st.spinner("Requesting a new IBKR PAPER snapshot Preview..."):
                executor, preview = load_order_preview(intent)
        except Exception as error:
            st.session_state.pop(_PREVIEW_STATE_KEY, None)
            st.session_state.pop(_EXECUTOR_STATE_KEY, None)
            st.error(order_preview_error_message(error))
        else:
            st.session_state[_EXECUTOR_STATE_KEY] = executor
            st.session_state[_PREVIEW_STATE_KEY] = preview

    preview = st.session_state.get(_PREVIEW_STATE_KEY)
    if preview_matches_intent(preview, intent):
        render_order_preview(preview)

    st.button(
        "Submit PAPER order",
        disabled=True,
        icon=":material/lock:",
        key="paper_order_submit",
        help=(
            "Disabled for this PR. TWS Read-Only API remains enabled and the "
            "production executor has submission_enabled=False."
        ),
    )
    st.caption(
        "Submit hard limit: USD 1,000. A new IBKR live snapshot would be "
        "requested again immediately before a future MARKET Submit; quote "
        "age would still not be independently verified."
    )


if __name__ == "__main__":
    main()
