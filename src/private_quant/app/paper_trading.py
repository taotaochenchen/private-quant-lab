"""Streamlit PAPER order ticket with explicitly confirmed manual submission."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
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
    PaperOrderExecutionProvider,
    UnsupportedContractError,
)
from private_quant.broker.order_models import (
    OrderIntent,
    OrderPreview,
    OrderResult,
    OrderSide,
    OrderType,
    QuoteSource,
)

_PREVIEW_STATE_KEY = "_paper_order_preview"
_EXECUTOR_STATE_KEY = "_paper_order_executor"
_CONFIGURATION_GATE_STATE_KEY = "_paper_order_submit_configuration_enabled"
_CONSUMED_STATE_KEY = "_paper_order_preview_consumed"
_RESULT_STATE_KEY = "_paper_order_result"
_ERROR_STATE_KEY = "_paper_order_submit_error"
_CONFIRMATION_WIDGET_KEY = "paper_order_read_only_confirmation"
_RESET_CONFIRMATION_STATE_KEY = "_paper_order_reset_confirmation"


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


@dataclass(frozen=True, slots=True)
class SubmitAttemptOutcome:
    """Safe, one-click Submit result for the app state boundary."""

    consumed: bool
    result: OrderResult | None
    error_message: str | None


def preview_is_submittable(
    preview: OrderPreview | None,
    intent: OrderIntent,
    *,
    now: datetime,
    configuration_enabled: bool,
    operator_confirmed: bool,
    consumed: bool,
) -> bool:
    """Return whether every local Submit gate is currently satisfied."""

    if now.tzinfo is None or now.utcoffset() is None:
        return False
    return (
        configuration_enabled
        and operator_confirmed
        and not consumed
        and preview is not None
        and preview.intent == intent
        and now < preview.expires_at
    )


def submit_paper_order(
    executor: PaperOrderExecutionProvider,
    preview: OrderPreview,
) -> OrderResult:
    """Forward one eligible Preview to its already-bound executor."""

    return executor.submit_order(preview)


def order_submit_error_message(error: Exception) -> str:
    """Map Submit failures to fixed UI copy without broker details."""

    if isinstance(error, OrderSubmissionDisabledError):
        return "PAPER Submit is disabled by the local safety gate."
    if isinstance(error, OrderPreviewRequiredError):
        return "Preview this exact ticket before Submit."
    if isinstance(error, OrderPreviewExpiredError):
        return "This Preview has expired. Preview the ticket again."
    if isinstance(error, DuplicateOrderSubmissionError):
        return "This Preview has already been consumed. Preview again."
    if isinstance(error, OrderQuoteUnavailableError):
        return "A current IBKR quote was unavailable. Preview the ticket again."
    if isinstance(error, OrderNotionalLimitError):
        return "This order is above the PAPER Submit safety limit."
    if isinstance(error, OrderConnectionError):
        return (
            "Could not submit the local TWS PAPER order. Check TWS and try a "
            "new Preview."
        )
    if isinstance(error, OrderStatusTimeoutError):
        return "The PAPER order response timed out. Check TWS before trying again."
    if isinstance(error, OfficialIbapiUnavailableError):
        return "The official IBKR TWS Python API is unavailable in this environment."
    return "The PAPER order could not be submitted. Preview again before retrying."


def submit_help_text(
    preview: OrderPreview | None,
    intent: OrderIntent,
    *,
    now: datetime,
    configuration_enabled: bool,
    operator_confirmed: bool,
    consumed: bool,
) -> str:
    """Explain the first unmet local Submit gate using safe fixed copy."""

    if not configuration_enabled:
        return "Local PAPER Submit gate is disabled. Enable it and Preview again."
    if not operator_confirmed:
        return "Confirm that you intentionally disabled TWS Read-Only API."
    if preview is None or preview.intent != intent:
        return "Preview this exact ticket before Submit."
    if now.tzinfo is None or now.utcoffset() is None or now >= preview.expires_at:
        return "This Preview has expired. Preview the ticket again."
    if consumed:
        return "This Preview has already been consumed. Preview again."
    return "Ready for one manual IBKR PAPER Submit."


def attempt_paper_submit(
    executor: PaperOrderExecutionProvider,
    preview: OrderPreview | None,
    intent: OrderIntent,
    *,
    now: datetime,
    configuration_enabled: bool,
    operator_confirmed: bool,
    consumed: bool,
) -> SubmitAttemptOutcome:
    """Consume an eligible Preview once and return only safe outcome data."""

    if not preview_is_submittable(
        preview,
        intent,
        now=now,
        configuration_enabled=configuration_enabled,
        operator_confirmed=operator_confirmed,
        consumed=consumed,
    ):
        return SubmitAttemptOutcome(
            consumed=consumed,
            result=None,
            error_message=submit_help_text(
                preview,
                intent,
                now=now,
                configuration_enabled=configuration_enabled,
                operator_confirmed=operator_confirmed,
                consumed=consumed,
            ),
        )
    if preview is None:
        return SubmitAttemptOutcome(
            consumed=consumed,
            result=None,
            error_message="Preview this exact ticket before Submit.",
        )
    try:
        result = submit_paper_order(executor, preview)
    except Exception as error:
        return SubmitAttemptOutcome(
            consumed=True,
            result=None,
            error_message=order_submit_error_message(error),
        )
    return SubmitAttemptOutcome(consumed=True, result=result, error_message=None)


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
) -> tuple[PaperOrderExecutionProvider, OrderPreview, bool]:
    """Create an executor, request one Preview, and return its local gate."""

    configuration = configuration_loader()
    executor = executor_builder(configuration)
    return (
        executor,
        executor.preview_order(intent),
        configuration.paper_submit_enabled,
    )


def _format_money(value: Decimal) -> str:
    return f"USD {value:,.2f}"


def render_order_result(result: OrderResult) -> None:
    """Render only the sanitized fields from a submitted PAPER order."""

    st.success("PAPER order response received.")
    with st.container(horizontal=True):
        st.metric(
            "Status", result.status.value.replace("_", " ").title(), border=True
        )
        st.metric("Broker order ID", str(result.broker_order_id), border=True)
        st.metric("Filled", f"{result.filled_quantity:,}", border=True)
        st.metric("Remaining", f"{result.remaining_quantity:,}", border=True)
        st.metric(
            "Average fill price",
            _format_money(result.average_fill_price)
            if result.average_fill_price is not None
            else "N/A",
            border=True,
        )


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
        _clear_preview_state()


def _clear_preview_state() -> None:
    """Discard every Preview-bound value before the confirmation widget exists."""

    for state_key in (
        _PREVIEW_STATE_KEY,
        _EXECUTOR_STATE_KEY,
        _CONFIGURATION_GATE_STATE_KEY,
        _CONSUMED_STATE_KEY,
        _RESULT_STATE_KEY,
        _ERROR_STATE_KEY,
    ):
        st.session_state.pop(state_key, None)
    st.session_state[_CONFIRMATION_WIDGET_KEY] = False


def main() -> None:
    """Run the local PAPER-only order Preview page."""

    st.set_page_config(
        page_title="Private Quant Lab — Paper Trading",
        page_icon=":material/receipt_long:",
        layout="wide",
    )
    if st.session_state.pop(_RESET_CONFIRMATION_STATE_KEY, False):
        st.session_state[_CONFIRMATION_WIDGET_KEY] = False

    st.title("Private Quant Lab — Paper Trading")
    st.warning(
        "PAPER ONLY — manual Submit can transmit an order to your IBKR Paper "
        "account. No live trading or automatic execution is available."
    )
    st.caption(
        "No automatic execution, order staging, preview at TWS, or cancellation "
        "is available."
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
                executor, preview, configuration_enabled = load_order_preview(
                    intent
                )
        except Exception as error:
            _clear_preview_state()
            st.error(order_preview_error_message(error))
        else:
            st.session_state[_EXECUTOR_STATE_KEY] = executor
            st.session_state[_PREVIEW_STATE_KEY] = preview
            st.session_state[_CONFIGURATION_GATE_STATE_KEY] = configuration_enabled
            st.session_state[_CONSUMED_STATE_KEY] = False
            st.session_state.pop(_RESULT_STATE_KEY, None)
            st.session_state.pop(_ERROR_STATE_KEY, None)

    preview = st.session_state.get(_PREVIEW_STATE_KEY)
    executor = st.session_state.get(_EXECUTOR_STATE_KEY)
    configuration_enabled = st.session_state.get(_CONFIGURATION_GATE_STATE_KEY, False)
    consumed = st.session_state.get(_CONSUMED_STATE_KEY, False)
    if preview_matches_intent(preview, intent):
        render_order_preview(preview)

    operator_confirmed = st.checkbox(
        "I intentionally disabled Read-Only API in TWS PAPER for this session.",
        value=False,
        key=_CONFIRMATION_WIDGET_KEY,
    )
    st.caption(
        "Operator confirmation only — the app does not automatically detect the "
        "TWS Read-Only setting."
    )
    st.caption(
        "IBKR_PAPER_SUBMIT_ENABLED must be true before creating a "
        "Submit-capable Preview."
    )
    st.caption(
        "Local Submit gate: "
        f"{'Enabled' if configuration_enabled else 'Disabled'}"
    )
    st.caption(
        "Read-Only confirmation: "
        f"{'Confirmed' if operator_confirmed else 'Required'}"
    )

    now = datetime.now(timezone.utc)
    can_submit = preview_is_submittable(
        preview,
        intent,
        now=now,
        configuration_enabled=configuration_enabled,
        operator_confirmed=operator_confirmed,
        consumed=consumed,
    )
    submit_clicked = st.button(
        "Submit PAPER order",
        disabled=not can_submit,
        icon=":material/send:",
        key="paper_order_submit",
        help=submit_help_text(
            preview,
            intent,
            now=now,
            configuration_enabled=configuration_enabled,
            operator_confirmed=operator_confirmed,
            consumed=consumed,
        ),
    )
    if submit_clicked:
        outcome = attempt_paper_submit(
            executor,
            preview,
            intent,
            now=datetime.now(timezone.utc),
            configuration_enabled=configuration_enabled,
            operator_confirmed=operator_confirmed,
            consumed=consumed,
        )
        st.session_state[_CONSUMED_STATE_KEY] = outcome.consumed
        if outcome.result is not None:
            st.session_state[_RESULT_STATE_KEY] = outcome.result
            st.session_state.pop(_ERROR_STATE_KEY, None)
        else:
            st.session_state.pop(_RESULT_STATE_KEY, None)
            st.session_state[_ERROR_STATE_KEY] = outcome.error_message
        st.session_state[_RESET_CONFIRMATION_STATE_KEY] = True
        st.rerun()

    result = st.session_state.get(_RESULT_STATE_KEY)
    if result is not None:
        render_order_result(result)
    error_message = st.session_state.get(_ERROR_STATE_KEY)
    if error_message is not None:
        st.error(error_message)
    st.caption(
        "Submit hard limit: USD 1,000. A new IBKR live snapshot would be "
        "requested for every MARKET Preview; quote age is not independently "
        "verified."
    )


if __name__ == "__main__":
    main()
