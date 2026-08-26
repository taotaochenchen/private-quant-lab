"""Read-only IBKR TWS Paper adapter using the official Python API."""

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from importlib import import_module
import math
from threading import Event, Thread
from types import ModuleType
from typing import Protocol

from private_quant.broker.base import (
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

_SAFE_CONFIGURATION_MESSAGE = (
    "IBKR Phase 1 requires paper mode on 127.0.0.1:7497 with client ID 10."
)
_SAFE_CONNECTION_MESSAGE = (
    "Could not connect to local IBKR TWS Paper. Confirm TWS Paper is running, "
    "socket clients are enabled, Read-Only API is on, and client ID 10 is free."
)
_SAFE_DATA_TIMEOUT_MESSAGE = (
    "IBKR connected, but the required read-only account data did not complete."
)
_SAFE_OFFICIAL_API_MESSAGE = (
    "Install the official IBKR TWS API Python package from IBKR's API download "
    "into this project environment."
)
_ACCOUNT_SUMMARY_REQUEST_ID = 9001
_ACCOUNT_SUMMARY_TAGS = "BuyingPower,TotalCashValue"


class IbkrSession(Protocol):
    """Narrow internal surface used by the read-only provider."""

    balances: tuple[AccountBalance, ...]
    positions: tuple[BrokerPosition, ...]
    open_orders: tuple[BrokerOpenOrder, ...]

    def start(self, host: str, port: int, client_id: int) -> None: ...

    def wait_until_connected(self, timeout: float) -> bool: ...

    def request_account_summary(self) -> None: ...

    def request_positions(self) -> None: ...

    def request_open_orders(self) -> None: ...

    def wait_for_account_summary(self, timeout: float) -> bool: ...

    def wait_for_positions(self, timeout: float) -> bool: ...

    def wait_for_open_orders(self, timeout: float) -> bool: ...

    def close(self) -> None: ...


IbkrSessionFactory = Callable[[], IbkrSession]
ModuleLoader = Callable[[str], ModuleType]


class IbkrBrokerProvider:
    """Take one bounded, sanitized snapshot from local TWS Paper."""

    def __init__(
        self,
        *,
        mode: str,
        host: str,
        port: int,
        client_id: int,
        session_factory: IbkrSessionFactory = lambda: create_official_ibkr_session(),
        timeout: float = 8.0,
    ) -> None:
        normalized_mode = mode.strip().lower()
        if (
            normalized_mode != "paper"
            or host != "127.0.0.1"
            or port != 7497
            or client_id != 10
        ):
            raise BrokerConfigurationError(_SAFE_CONFIGURATION_MESSAGE)
        self._mode = normalized_mode
        self._host = host
        self._port = port
        self._client_id = client_id
        self._session_factory = session_factory
        self._timeout = timeout

    def get_read_only_snapshot(self) -> BrokerSnapshot:
        """Connect, perform only approved reads, sanitize, and disconnect."""

        session = self._session_factory()
        try:
            try:
                session.start(self._host, self._port, self._client_id)
            except Exception as exc:
                raise BrokerConnectionError(_SAFE_CONNECTION_MESSAGE) from exc

            if not session.wait_until_connected(self._timeout):
                raise BrokerConnectionError(_SAFE_CONNECTION_MESSAGE)

            try:
                session.request_account_summary()
                session.request_positions()
                session.request_open_orders()
            except Exception as exc:
                raise BrokerConnectionError(_SAFE_CONNECTION_MESSAGE) from exc

            if not session.wait_for_account_summary(self._timeout):
                raise BrokerDataTimeoutError(_SAFE_DATA_TIMEOUT_MESSAGE)
            if not session.wait_for_positions(self._timeout):
                raise BrokerDataTimeoutError(_SAFE_DATA_TIMEOUT_MESSAGE)

            open_orders_complete = session.wait_for_open_orders(self._timeout)
            return BrokerSnapshot(
                connected=True,
                mode=self._mode,
                balances=session.balances,
                positions=session.positions,
                open_orders=(session.open_orders if open_orders_complete else ()),
                open_orders_availability=(
                    OpenOrdersAvailability.AVAILABLE
                    if open_orders_complete
                    else OpenOrdersAvailability.UNAVAILABLE_READ_ONLY
                ),
            )
        finally:
            session.close()


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BrokerDataTimeoutError(_SAFE_DATA_TIMEOUT_MESSAGE) from exc


def _optional_limit_price(value: object) -> Decimal | None:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric_value) or abs(numeric_value) >= 1e307:
        return None
    return _decimal(value)


def create_official_ibkr_session(
    *, module_loader: ModuleLoader = import_module
) -> IbkrSession:
    """Create a one-shot session from IBKR's separately installed package."""

    try:
        client_module = module_loader("ibapi.client")
        wrapper_module = module_loader("ibapi.wrapper")
    except (ImportError, ModuleNotFoundError) as exc:
        raise OfficialIbapiUnavailableError(_SAFE_OFFICIAL_API_MESSAGE) from exc

    EClient = client_module.EClient
    EWrapper = wrapper_module.EWrapper

    class OfficialIbkrSession(EWrapper, EClient):
        def __init__(self) -> None:
            EWrapper.__init__(self)
            EClient.__init__(self, self)
            self._connected_event = Event()
            self._account_summary_event = Event()
            self._positions_event = Event()
            self._open_orders_event = Event()
            self._balance_values: dict[tuple[str, str], AccountBalance] = {}
            self._position_values: list[BrokerPosition] = []
            self._open_order_values: list[BrokerOpenOrder] = []
            self._reader_thread: Thread | None = None
            self._account_summary_requested = False
            self._positions_requested = False

        @property
        def balances(self) -> tuple[AccountBalance, ...]:
            return tuple(
                sorted(
                    self._balance_values.values(),
                    key=lambda balance: (balance.name, balance.currency),
                )
            )

        @property
        def positions(self) -> tuple[BrokerPosition, ...]:
            return tuple(self._position_values)

        @property
        def open_orders(self) -> tuple[BrokerOpenOrder, ...]:
            return tuple(self._open_order_values)

        def start(self, host: str, port: int, client_id: int) -> None:
            self.connect(host, port, client_id)
            self._reader_thread = Thread(
                target=self.run,
                name="ibkr-read-only-reader",
                daemon=True,
            )
            self._reader_thread.start()

        def wait_until_connected(self, timeout: float) -> bool:
            return self._connected_event.wait(timeout)

        def request_account_summary(self) -> None:
            self._account_summary_requested = True
            self.reqAccountSummary(
                _ACCOUNT_SUMMARY_REQUEST_ID,
                "All",
                _ACCOUNT_SUMMARY_TAGS,
            )

        def request_positions(self) -> None:
            self._positions_requested = True
            self.reqPositions()

        def request_open_orders(self) -> None:
            self.reqAllOpenOrders()

        def wait_for_account_summary(self, timeout: float) -> bool:
            return self._account_summary_event.wait(timeout)

        def wait_for_positions(self, timeout: float) -> bool:
            return self._positions_event.wait(timeout)

        def wait_for_open_orders(self, timeout: float) -> bool:
            return self._open_orders_event.wait(timeout)

        def close(self) -> None:
            if self.isConnected():
                if self._account_summary_requested:
                    self.cancelAccountSummary(_ACCOUNT_SUMMARY_REQUEST_ID)
                if self._positions_requested:
                    self.cancelPositions()
                self.disconnect()
            if self._reader_thread is not None:
                self._reader_thread.join(timeout=1.0)

        def nextValidId(self, orderId: int) -> None:
            del orderId
            self._connected_event.set()

        def accountSummary(
            self,
            reqId: int,
            account: str,
            tag: str,
            value: str,
            currency: str,
        ) -> None:
            del reqId, account
            if tag not in {"BuyingPower", "TotalCashValue"}:
                return
            balance = AccountBalance(tag, _decimal(value), currency)
            self._balance_values[(tag, currency)] = balance

        def accountSummaryEnd(self, reqId: int) -> None:
            del reqId
            self._account_summary_event.set()

        def position(
            self,
            account: str,
            contract: object,
            position: object,
            avgCost: float,
        ) -> None:
            del account
            self._position_values.append(
                BrokerPosition(
                    symbol=str(getattr(contract, "symbol", "")),
                    security_type=str(getattr(contract, "secType", "")),
                    currency=str(getattr(contract, "currency", "")),
                    quantity=_decimal(position),
                    average_cost=_decimal(avgCost),
                )
            )

        def positionEnd(self) -> None:
            self._positions_event.set()

        def openOrder(
            self,
            orderId: int,
            contract: object,
            order: object,
            orderState: object,
        ) -> None:
            del orderId
            self._open_order_values.append(
                BrokerOpenOrder(
                    symbol=str(getattr(contract, "symbol", "")),
                    side=str(getattr(order, "action", "")),
                    quantity=_decimal(getattr(order, "totalQuantity", "0")),
                    order_type=str(getattr(order, "orderType", "")),
                    limit_price=_optional_limit_price(
                        getattr(order, "lmtPrice", None)
                    ),
                    status=str(getattr(orderState, "status", "")),
                )
            )

        def openOrderEnd(self) -> None:
            self._open_orders_event.set()

        def error(self, reqId: int, *args: object) -> None:
            del reqId, args

    return OfficialIbkrSession()


__all__ = [
    "IbkrBrokerProvider",
    "IbkrSession",
    "IbkrSessionFactory",
    "create_official_ibkr_session",
]
