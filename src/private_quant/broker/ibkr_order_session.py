"""Official IBKR TWS API session for the guarded PAPER order workflow."""

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from importlib import import_module
from threading import Event, Thread
from types import ModuleType

from private_quant.broker.base import OfficialIbapiUnavailableError
from private_quant.broker.ibkr import (
    _call_without_details,
    _disable_ibapi_logging,
)
from private_quant.broker.ibkr_orders import (
    IbkrOrderSession,
    LiveQuote,
    OrderUpdate,
    ResolvedContract,
)
from private_quant.broker.order_models import OrderIntent, OrderType

_CONTRACT_REQUEST_ID = 9101
_QUOTE_REQUEST_ID = 9102
_SAFE_OFFICIAL_API_MESSAGE = (
    "Install the official IBKR TWS API Python package from IBKR's API download "
    "into this project environment."
)
_KNOWN_ORDER_STATUSES = {
    "PendingSubmit",
    "PreSubmitted",
    "Submitted",
    "Filled",
    "Cancelled",
    "ApiCancelled",
    "Inactive",
}

ModuleLoader = Callable[[str], ModuleType]


def _positive_decimal(value: object) -> Decimal | None:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not decimal_value.is_finite() or decimal_value <= 0:
        return None
    return decimal_value


def _nonnegative_decimal(value: object) -> Decimal | None:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not decimal_value.is_finite() or decimal_value < 0:
        return None
    return decimal_value


def _safe_status(value: object) -> str:
    status = str(value)
    return status if status in _KNOWN_ORDER_STATUSES else "Unknown"


def create_official_ibkr_order_session(
    *, module_loader: ModuleLoader = import_module
) -> IbkrOrderSession:
    """Create a disconnected session from the separately installed API."""

    _disable_ibapi_logging()
    try:
        client_module = module_loader("ibapi.client")
        wrapper_module = module_loader("ibapi.wrapper")
        contract_module = module_loader("ibapi.contract")
        order_module = module_loader("ibapi.order")
    except (ImportError, ModuleNotFoundError):
        client_module = None
        wrapper_module = None
        contract_module = None
        order_module = None
    if (
        client_module is None
        or wrapper_module is None
        or contract_module is None
        or order_module is None
    ):
        raise OfficialIbapiUnavailableError(_SAFE_OFFICIAL_API_MESSAGE)
    _disable_ibapi_logging()

    EClient = client_module.EClient
    EWrapper = wrapper_module.EWrapper
    Contract = contract_module.Contract
    Order = order_module.Order

    class OfficialIbkrOrderSession(EWrapper, EClient):
        def __init__(self) -> None:
            EWrapper.__init__(self)
            EClient.__init__(self, self)
            self._connected_event = Event()
            self._managed_accounts_event = Event()
            self._contract_event = Event()
            self._quote_event = Event()
            self._order_event = Event()
            self._next_order_id: int | None = None
            self._managed_account_count = 0
            self._contracts: list[ResolvedContract] = []
            self._contract_request_failed = False
            self._market_data_type: int | None = None
            self._bid: Decimal | None = None
            self._ask: Decimal | None = None
            self._quote_request_failed = False
            self._quote_requested = False
            self._submitted_order_id: int | None = None
            self._submitted_quantity = Decimal("0")
            self._order_updates: dict[int, OrderUpdate] = {}
            self._reader_thread: Thread | None = None

        @property
        def managed_account_count(self) -> int:
            return self._managed_account_count

        @property
        def next_order_id(self) -> int | None:
            return self._next_order_id

        @property
        def live_quote(self) -> LiveQuote:
            return LiveQuote(self._market_data_type, self._bid, self._ask)

        def start(self, host: str, port: int, client_id: int) -> None:
            self.connect(host, port, client_id)
            self._reader_thread = Thread(
                target=self.run,
                name="ibkr-paper-order-reader",
                daemon=True,
            )
            self._reader_thread.start()

        def wait_until_connected(self, timeout: float) -> bool:
            return self._connected_event.wait(timeout)

        def wait_for_managed_accounts(self, timeout: float) -> bool:
            return self._managed_accounts_event.wait(timeout)

        def resolve_contracts(
            self, symbol: str, timeout: float
        ) -> tuple[ResolvedContract, ...]:
            self._contracts.clear()
            self._contract_event.clear()
            self._contract_request_failed = False
            contract = Contract()
            contract.symbol = symbol
            contract.secType = "STK"
            contract.exchange = "SMART"
            contract.currency = "USD"
            self.reqContractDetails(_CONTRACT_REQUEST_ID, contract)
            if (
                not self._contract_event.wait(timeout)
                or self._contract_request_failed
            ):
                self._contracts.clear()
                return ()
            return tuple(self._contracts)

        def request_live_quote(
            self, contract: ResolvedContract, timeout: float
        ) -> LiveQuote:
            self._quote_event.clear()
            self._quote_request_failed = False
            self._market_data_type = None
            self._bid = None
            self._ask = None
            self._quote_requested = True
            official_contract = self._to_contract(contract)
            self.reqMarketDataType(1)
            self.reqMktData(
                _QUOTE_REQUEST_ID,
                official_contract,
                "",
                True,
                False,
                [],
            )
            if (
                not self._quote_event.wait(timeout)
                or self._quote_request_failed
            ):
                self._market_data_type = None
                self._bid = None
                self._ask = None
                return LiveQuote(None, None, None)
            return self.live_quote

        def submit_order(
            self,
            order_id: int,
            contract: ResolvedContract,
            intent: OrderIntent,
            order_ref: str,
        ) -> None:
            official_contract = self._to_contract(contract)
            order = Order()
            order.action = intent.side.value
            order.orderType = (
                "MKT" if intent.order_type is OrderType.MARKET else "LMT"
            )
            order.totalQuantity = Decimal(intent.quantity)
            if intent.order_type is OrderType.LIMIT:
                if intent.limit_price is None:
                    raise ValueError("limit price required")
                order.lmtPrice = float(intent.limit_price)
            order.orderRef = order_ref
            order.transmit = True

            self._submitted_order_id = order_id
            self._submitted_quantity = Decimal(intent.quantity)
            self._order_updates.pop(order_id, None)
            self._order_event.clear()
            self.placeOrder(order_id, official_contract, order)

        def wait_for_order_update(
            self, order_id: int, timeout: float
        ) -> OrderUpdate | None:
            if not self._order_event.wait(timeout):
                return None
            return self._order_updates.get(order_id)

        def close(self) -> None:
            connected_read, connected = _call_without_details(self.isConnected)
            if connected_read and connected:
                if self._quote_requested:
                    _call_without_details(
                        lambda: self.cancelMktData(_QUOTE_REQUEST_ID)
                    )
                _call_without_details(self.disconnect)
            if self._reader_thread is not None:
                _call_without_details(
                    lambda: self._reader_thread.join(timeout=1.0)
                )
            self._contracts.clear()
            self._bid = None
            self._ask = None

        @staticmethod
        def _to_contract(contract: ResolvedContract):
            official_contract = Contract()
            official_contract.symbol = contract.symbol
            official_contract.conId = contract.con_id
            official_contract.secType = contract.security_type
            official_contract.exchange = contract.exchange
            official_contract.currency = contract.currency
            return official_contract

        def nextValidId(self, orderId: int) -> None:
            if isinstance(orderId, int) and not isinstance(orderId, bool):
                self._next_order_id = orderId
                self._connected_event.set()

        def managedAccounts(self, accountsList: str) -> None:
            self._managed_account_count = len(
                {
                    account.strip()
                    for account in str(accountsList).split(",")
                    if account.strip()
                }
            )
            self._managed_accounts_event.set()

        def contractDetails(
            self, reqId: int, contractDetails: object
        ) -> None:
            if reqId != _CONTRACT_REQUEST_ID:
                return
            contract = getattr(contractDetails, "contract", None)
            if contract is None:
                return
            try:
                con_id = int(getattr(contract, "conId", 0))
            except (TypeError, ValueError):
                return
            self._contracts.append(
                ResolvedContract(
                    symbol=str(getattr(contract, "symbol", "")),
                    con_id=con_id,
                    security_type=str(getattr(contract, "secType", "")),
                    exchange=str(getattr(contract, "exchange", "")),
                    currency=str(getattr(contract, "currency", "")),
                )
            )

        def contractDetailsEnd(self, reqId: int) -> None:
            if reqId == _CONTRACT_REQUEST_ID:
                self._contract_event.set()

        def marketDataType(self, reqId: int, marketDataType: int) -> None:
            if reqId == _QUOTE_REQUEST_ID:
                self._market_data_type = marketDataType

        def tickPrice(
            self,
            reqId: int,
            tickType: int,
            price: float,
            attrib: object,
        ) -> None:
            del attrib
            if reqId != _QUOTE_REQUEST_ID:
                return
            if tickType == 1:
                self._bid = _positive_decimal(price)
            elif tickType == 2:
                self._ask = _positive_decimal(price)

        def tickSnapshotEnd(self, reqId: int) -> None:
            if reqId == _QUOTE_REQUEST_ID:
                self._quote_requested = False
                self._quote_event.set()

        def openOrder(
            self,
            orderId: int,
            contract: object,
            order: object,
            orderState: object,
        ) -> None:
            del contract
            if orderId != self._submitted_order_id:
                return
            quantity = _nonnegative_decimal(
                getattr(order, "totalQuantity", self._submitted_quantity)
            )
            if quantity is None:
                return
            self._order_updates[orderId] = OrderUpdate(
                broker_status=_safe_status(
                    getattr(orderState, "status", "Unknown")
                ),
                filled_quantity=Decimal("0"),
                remaining_quantity=quantity,
                average_fill_price=None,
                rejected=False,
            )
            self._order_event.set()

        def orderStatus(
            self,
            orderId: int,
            status: str,
            filled: object,
            remaining: object,
            avgFillPrice: float,
            permId: int,
            parentId: int,
            lastFillPrice: float,
            clientId: int,
            whyHeld: str,
            mktCapPrice: float,
        ) -> None:
            del permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice
            if orderId != self._submitted_order_id:
                return
            filled_value = _nonnegative_decimal(filled)
            remaining_value = _nonnegative_decimal(remaining)
            if filled_value is None or remaining_value is None:
                return
            average_fill_price = _positive_decimal(avgFillPrice)
            self._order_updates[orderId] = OrderUpdate(
                broker_status=_safe_status(status),
                filled_quantity=filled_value,
                remaining_quantity=remaining_value,
                average_fill_price=average_fill_price,
                rejected=False,
            )
            self._order_event.set()

        def error(self, reqId: int, *args: object) -> None:
            error_code: int | None = None
            if len(args) >= 2 and isinstance(args[1], int):
                error_code = args[1]
            elif args and isinstance(args[0], int):
                error_code = args[0]

            if reqId == _CONTRACT_REQUEST_ID:
                self._contract_request_failed = True
                self._contracts.clear()
                self._contract_event.set()
                return
            if reqId == _QUOTE_REQUEST_ID:
                self._quote_request_failed = True
                self._market_data_type = None
                self._bid = None
                self._ask = None
                self._quote_event.set()
                return
            if reqId != self._submitted_order_id:
                return
            if error_code == 201:
                update = OrderUpdate(
                    broker_status="Inactive",
                    filled_quantity=Decimal("0"),
                    remaining_quantity=self._submitted_quantity,
                    average_fill_price=None,
                    rejected=True,
                )
            elif error_code == 202:
                update = OrderUpdate(
                    broker_status="Cancelled",
                    filled_quantity=Decimal("0"),
                    remaining_quantity=self._submitted_quantity,
                    average_fill_price=None,
                    rejected=False,
                )
            else:
                return
            self._order_updates[reqId] = update
            self._order_event.set()

    return OfficialIbkrOrderSession()


__all__ = ["create_official_ibkr_order_session"]
