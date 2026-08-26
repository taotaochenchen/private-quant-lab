"""PAPER-only IBKR order validation and Preview workflow."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
from secrets import token_urlsafe
from threading import Lock
from typing import Protocol, TypeVar

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
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    QuoteSource,
)

MARKET_PREVIEW_SAFETY_BUFFER_LIMIT = Decimal("950")
"""Preview threshold reserving room below the USD 1,000 Submit hard limit."""

ORDER_SUBMIT_HARD_LIMIT = Decimal("1000")
"""Maximum estimated notional immediately before PAPER Submit."""

_PREVIEW_LIFETIME = timedelta(seconds=60)
_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
_SAFE_CONFIGURATION_MESSAGE = (
    "IBKR paper orders require paper mode on 127.0.0.1:7497 with client ID 10."
)
_SAFE_INTENT_MESSAGE = (
    "Enter a valid US stock or ETF order with a positive whole quantity."
)
_SAFE_CONTRACT_MESSAGE = (
    "A unique US stock or ETF contract could not be confirmed through IBKR."
)
_SAFE_QUOTE_MESSAGE = (
    "A valid current IBKR live quote is required for a MARKET order."
)
_SAFE_PREVIEW_NOTIONAL_MESSAGE = (
    "MARKET Preview safety buffer allows up to USD 950 estimated notional; "
    "the Submit hard limit remains USD 1,000."
)
_SAFE_LIMIT_NOTIONAL_MESSAGE = (
    "Paper order estimated notional cannot exceed USD 1,000."
)
_SAFE_CONNECTION_MESSAGE = (
    "Could not complete the local IBKR TWS Paper order Preview session."
)
_SAFE_ACCOUNT_SCOPE_MESSAGE = (
    "Paper order submission requires exactly one account in the TWS session."
)
_SAFE_PREVIEW_REQUIRED_MESSAGE = (
    "Preview this exact order before submitting it."
)
_SAFE_PREVIEW_EXPIRED_MESSAGE = (
    "This order Preview has expired. Preview the order again."
)
_SAFE_DUPLICATE_MESSAGE = (
    "This order Preview has already been submitted and cannot be reused."
)
_SAFE_SUBMISSION_DISABLED_MESSAGE = (
    "Paper order submission is disabled while TWS Read-Only API remains enabled."
)
_SAFE_SUBMIT_NOTIONAL_MESSAGE = (
    "Paper order Submit hard limit is USD 1,000 estimated notional."
)
_SAFE_STATUS_TIMEOUT_MESSAGE = (
    "IBKR did not return an initial paper-order status in time."
)

_Result = TypeVar("_Result")


@dataclass(frozen=True, slots=True)
class ResolvedContract:
    """Sanitized contract identity needed to construct an IBKR order."""

    symbol: str
    con_id: int
    security_type: str
    exchange: str
    currency: str


@dataclass(frozen=True, slots=True)
class LiveQuote:
    """One uncached IBKR market-data snapshot."""

    market_data_type: int | None
    bid: Decimal | None
    ask: Decimal | None


@dataclass(frozen=True, slots=True)
class OrderUpdate:
    """Sanitized initial state received after an enabled mocked Submit."""

    broker_status: str
    filled_quantity: Decimal
    remaining_quantity: Decimal
    average_fill_price: Decimal | None
    rejected: bool


class IbkrOrderSession(Protocol):
    """Narrow session surface used by the paper-order executor."""

    def start(self, host: str, port: int, client_id: int) -> None: ...

    def wait_until_connected(self, timeout: float) -> bool: ...

    def resolve_contracts(
        self, symbol: str, timeout: float
    ) -> tuple[ResolvedContract, ...]: ...

    def request_live_quote(
        self, contract: ResolvedContract, timeout: float
    ) -> LiveQuote: ...

    @property
    def managed_account_count(self) -> int: ...

    @property
    def next_order_id(self) -> int | None: ...

    def wait_for_managed_accounts(self, timeout: float) -> bool: ...

    def submit_order(
        self,
        order_id: int,
        contract: ResolvedContract,
        intent: OrderIntent,
        order_ref: str,
    ) -> None: ...

    def wait_for_order_update(
        self, order_id: int, timeout: float
    ) -> OrderUpdate | None: ...

    def close(self) -> None: ...


IbkrOrderSessionFactory = Callable[[], IbkrOrderSession]
Clock = Callable[[], datetime]
TokenFactory = Callable[[], str]


def _default_session_factory() -> IbkrOrderSession:
    from private_quant.broker.ibkr_order_session import (
        create_official_ibkr_order_session,
    )

    return create_official_ibkr_order_session()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_preview_id() -> str:
    return token_urlsafe(24)


def _call_without_details(
    action: Callable[[], _Result],
) -> tuple[bool, _Result | None]:
    """Discard vendor exception objects and their potentially sensitive text."""

    try:
        return True, action()
    except Exception:
        return False, None


def _positive_finite_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not decimal_value.is_finite() or decimal_value <= 0:
        return None
    return decimal_value


class IbkrPaperOrderExecutor:
    """Validate and issue short-lived PAPER order Previews."""

    def __init__(
        self,
        *,
        mode: str,
        host: str,
        port: int,
        client_id: int,
        session_factory: IbkrOrderSessionFactory = _default_session_factory,
        clock: Clock = _utc_now,
        token_factory: TokenFactory = _new_preview_id,
        timeout: float = 12.0,
        submission_enabled: bool = False,
    ) -> None:
        normalized_mode = mode.strip().lower()
        if (
            normalized_mode != "paper"
            or host != "127.0.0.1"
            or port != 7497
            or client_id != 10
        ):
            raise OrderConfigurationError(_SAFE_CONFIGURATION_MESSAGE)
        self._mode = normalized_mode
        self._host = host
        self._port = port
        self._client_id = client_id
        self._session_factory = session_factory
        self._clock = clock
        self._token_factory = token_factory
        self._timeout = timeout
        self._submission_enabled = submission_enabled
        self._issued_previews: dict[str, OrderPreview] = {}
        self._consumed_preview_ids: set[str] = set()
        self._preview_lock = Lock()

    def preview_order(self, intent: OrderIntent) -> OrderPreview:
        """Validate an intent using one fresh IBKR session and quote."""

        normalized_intent = self._normalize_intent(intent)
        created, session = _call_without_details(self._session_factory)
        if not created or session is None:
            raise OrderConnectionError(_SAFE_CONNECTION_MESSAGE)

        try:
            self._connect(session)
            contract = self._resolve_one_contract(
                session, normalized_intent.symbol
            )
            unit_price, quote_source = self._preview_price(
                session, contract, normalized_intent
            )
            estimated_notional = unit_price * normalized_intent.quantity
            self._validate_preview_notional(
                normalized_intent.order_type, estimated_notional
            )
            created_at = self._clock()
            preview = OrderPreview(
                preview_id=self._token_factory(),
                intent=normalized_intent,
                estimated_unit_price=unit_price,
                estimated_notional=estimated_notional,
                quote_source=quote_source,
                created_at=created_at,
                expires_at=created_at + _PREVIEW_LIFETIME,
            )
            with self._preview_lock:
                if preview.preview_id in self._issued_previews:
                    raise OrderConnectionError(_SAFE_CONNECTION_MESSAGE)
                self._issued_previews[preview.preview_id] = preview
            return preview
        finally:
            _call_without_details(session.close)

    def submit_order(self, preview: OrderPreview) -> OrderResult:
        """Consume a Preview and run the guarded PAPER submission workflow."""

        if not self._submission_enabled:
            raise OrderSubmissionDisabledError(
                _SAFE_SUBMISSION_DISABLED_MESSAGE
            )
        self._consume_exact_unexpired_preview(preview)

        created, session = _call_without_details(self._session_factory)
        if not created or session is None:
            raise OrderConnectionError(_SAFE_CONNECTION_MESSAGE)
        try:
            self._connect(session)
            self._require_one_managed_account(session)
            contract = self._resolve_one_contract(
                session, preview.intent.symbol
            )
            self._revalidate_submit_notional(
                session, contract, preview.intent
            )
            order_id = self._require_next_order_id(session)
            submitted, _ = _call_without_details(
                lambda: session.submit_order(
                    order_id,
                    contract,
                    preview.intent,
                    preview.preview_id,
                )
            )
            if not submitted:
                raise OrderConnectionError(_SAFE_CONNECTION_MESSAGE)
            waited, update = _call_without_details(
                lambda: session.wait_for_order_update(order_id, self._timeout)
            )
            if not waited or update is None:
                raise OrderStatusTimeoutError(_SAFE_STATUS_TIMEOUT_MESSAGE)
            return self._to_result(preview.preview_id, order_id, update)
        finally:
            _call_without_details(session.close)

    def _normalize_intent(self, intent: OrderIntent) -> OrderIntent:
        if not isinstance(intent, OrderIntent):
            raise InvalidOrderIntentError(_SAFE_INTENT_MESSAGE)
        if not isinstance(intent.side, OrderSide) or not isinstance(
            intent.order_type, OrderType
        ):
            raise InvalidOrderIntentError(_SAFE_INTENT_MESSAGE)
        if not isinstance(intent.symbol, str):
            raise InvalidOrderIntentError(_SAFE_INTENT_MESSAGE)
        symbol = intent.symbol.strip().upper()
        if _SYMBOL_PATTERN.fullmatch(symbol) is None:
            raise InvalidOrderIntentError(_SAFE_INTENT_MESSAGE)
        if (
            isinstance(intent.quantity, bool)
            or not isinstance(intent.quantity, int)
            or intent.quantity <= 0
        ):
            raise InvalidOrderIntentError(_SAFE_INTENT_MESSAGE)

        if intent.order_type is OrderType.MARKET:
            if intent.limit_price is not None:
                raise InvalidOrderIntentError(_SAFE_INTENT_MESSAGE)
            limit_price = None
        else:
            limit_price = _positive_finite_decimal(intent.limit_price)
            if limit_price is None:
                raise InvalidOrderIntentError(_SAFE_INTENT_MESSAGE)

        return OrderIntent(
            symbol=symbol,
            side=intent.side,
            order_type=intent.order_type,
            quantity=intent.quantity,
            limit_price=limit_price,
        )

    def _connect(self, session: IbkrOrderSession) -> None:
        started, _ = _call_without_details(
            lambda: session.start(self._host, self._port, self._client_id)
        )
        waited, connected = _call_without_details(
            lambda: session.wait_until_connected(self._timeout)
        )
        if not started or not waited or not connected:
            raise OrderConnectionError(_SAFE_CONNECTION_MESSAGE)

    def _resolve_one_contract(
        self, session: IbkrOrderSession, symbol: str
    ) -> ResolvedContract:
        loaded, contracts = _call_without_details(
            lambda: session.resolve_contracts(symbol, self._timeout)
        )
        if not loaded or contracts is None or len(contracts) != 1:
            raise UnsupportedContractError(_SAFE_CONTRACT_MESSAGE)
        contract = contracts[0]
        if (
            contract.symbol != symbol
            or isinstance(contract.con_id, bool)
            or not isinstance(contract.con_id, int)
            or contract.con_id <= 0
            or contract.security_type != "STK"
            or contract.exchange != "SMART"
            or contract.currency != "USD"
        ):
            raise UnsupportedContractError(_SAFE_CONTRACT_MESSAGE)
        return contract

    def _preview_price(
        self,
        session: IbkrOrderSession,
        contract: ResolvedContract,
        intent: OrderIntent,
    ) -> tuple[Decimal, QuoteSource]:
        if intent.order_type is OrderType.LIMIT:
            if intent.limit_price is None:
                raise InvalidOrderIntentError(_SAFE_INTENT_MESSAGE)
            return intent.limit_price, QuoteSource.USER_LIMIT

        loaded, quote = _call_without_details(
            lambda: session.request_live_quote(contract, self._timeout)
        )
        if not loaded or quote is None or quote.market_data_type != 1:
            raise OrderQuoteUnavailableError(_SAFE_QUOTE_MESSAGE)
        if intent.side is OrderSide.BUY:
            price = _positive_finite_decimal(quote.ask)
            source = QuoteSource.IBKR_LIVE_ASK
        else:
            price = _positive_finite_decimal(quote.bid)
            source = QuoteSource.IBKR_LIVE_BID
        if price is None:
            raise OrderQuoteUnavailableError(_SAFE_QUOTE_MESSAGE)
        return price, source

    def _validate_preview_notional(
        self, order_type: OrderType, estimated_notional: Decimal
    ) -> None:
        if order_type is OrderType.MARKET:
            if estimated_notional > MARKET_PREVIEW_SAFETY_BUFFER_LIMIT:
                raise OrderNotionalLimitError(_SAFE_PREVIEW_NOTIONAL_MESSAGE)
            return
        if estimated_notional > ORDER_SUBMIT_HARD_LIMIT:
            raise OrderNotionalLimitError(_SAFE_LIMIT_NOTIONAL_MESSAGE)

    def _consume_exact_unexpired_preview(
        self, preview: OrderPreview
    ) -> None:
        with self._preview_lock:
            if preview.preview_id in self._consumed_preview_ids:
                raise DuplicateOrderSubmissionError(_SAFE_DUPLICATE_MESSAGE)
            issued = self._issued_previews.get(preview.preview_id)
            if issued is None or issued != preview:
                raise OrderPreviewRequiredError(_SAFE_PREVIEW_REQUIRED_MESSAGE)
            if self._clock() >= preview.expires_at:
                raise OrderPreviewExpiredError(_SAFE_PREVIEW_EXPIRED_MESSAGE)
            self._consumed_preview_ids.add(preview.preview_id)

    def _require_one_managed_account(
        self, session: IbkrOrderSession
    ) -> None:
        waited, complete = _call_without_details(
            lambda: session.wait_for_managed_accounts(self._timeout)
        )
        read, count = _call_without_details(
            lambda: session.managed_account_count
        )
        if not waited or not complete or not read or count != 1:
            raise OrderConnectionError(_SAFE_ACCOUNT_SCOPE_MESSAGE)

    def _revalidate_submit_notional(
        self,
        session: IbkrOrderSession,
        contract: ResolvedContract,
        intent: OrderIntent,
    ) -> None:
        if intent.order_type is OrderType.MARKET:
            unit_price, _ = self._preview_price(session, contract, intent)
        else:
            if intent.limit_price is None:
                raise InvalidOrderIntentError(_SAFE_INTENT_MESSAGE)
            unit_price = intent.limit_price
        estimated_notional = unit_price * intent.quantity
        if estimated_notional > ORDER_SUBMIT_HARD_LIMIT:
            raise OrderNotionalLimitError(_SAFE_SUBMIT_NOTIONAL_MESSAGE)

    def _require_next_order_id(self, session: IbkrOrderSession) -> int:
        read, order_id = _call_without_details(lambda: session.next_order_id)
        if (
            not read
            or isinstance(order_id, bool)
            or not isinstance(order_id, int)
            or order_id <= 0
        ):
            raise OrderConnectionError(_SAFE_CONNECTION_MESSAGE)
        return order_id

    def _to_result(
        self, preview_id: str, order_id: int, update: OrderUpdate
    ) -> OrderResult:
        filled = self._nonnegative_finite_decimal(update.filled_quantity)
        remaining = self._nonnegative_finite_decimal(
            update.remaining_quantity
        )
        average_fill_price = None
        if update.average_fill_price is not None:
            average_fill_price = _positive_finite_decimal(
                update.average_fill_price
            )
            if average_fill_price is None:
                raise OrderStatusTimeoutError(_SAFE_STATUS_TIMEOUT_MESSAGE)
        if filled is None or remaining is None:
            raise OrderStatusTimeoutError(_SAFE_STATUS_TIMEOUT_MESSAGE)
        status = (
            OrderStatus.REJECTED
            if update.rejected
            else self._map_order_status(update.broker_status)
        )
        return OrderResult(
            preview_id=preview_id,
            broker_order_id=order_id,
            status=status,
            filled_quantity=filled,
            remaining_quantity=remaining,
            average_fill_price=average_fill_price,
        )

    @staticmethod
    def _nonnegative_finite_decimal(value: object) -> Decimal | None:
        if isinstance(value, bool):
            return None
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
        if not decimal_value.is_finite() or decimal_value < 0:
            return None
        return decimal_value

    @staticmethod
    def _map_order_status(broker_status: str) -> OrderStatus:
        return {
            "PendingSubmit": OrderStatus.PENDING_SUBMIT,
            "PreSubmitted": OrderStatus.PRE_SUBMITTED,
            "Submitted": OrderStatus.SUBMITTED,
            "Filled": OrderStatus.FILLED,
            "Cancelled": OrderStatus.CANCELLED,
            "ApiCancelled": OrderStatus.CANCELLED,
            "Inactive": OrderStatus.INACTIVE,
        }.get(str(broker_status), OrderStatus.UNKNOWN)


__all__ = [
    "IbkrOrderSession",
    "IbkrOrderSessionFactory",
    "IbkrPaperOrderExecutor",
    "LiveQuote",
    "MARKET_PREVIEW_SAFETY_BUFFER_LIMIT",
    "ORDER_SUBMIT_HARD_LIMIT",
    "OrderUpdate",
    "ResolvedContract",
]
