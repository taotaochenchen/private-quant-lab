"""Framework-independent, account-safe broker snapshot models."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """One sanitized account summary value."""

    name: str
    value: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    """One position without an account identifier."""

    symbol: str
    security_type: str
    currency: str
    quantity: Decimal
    average_cost: Decimal


@dataclass(frozen=True, slots=True)
class BrokerOpenOrder:
    """One visible open order without IBKR or account identifiers."""

    symbol: str
    side: str
    quantity: Decimal
    order_type: str
    limit_price: Decimal | None
    status: str


class OpenOrdersAvailability(StrEnum):
    """Whether TWS supplied the open-order snapshot."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    UNAVAILABLE_READ_ONLY = "unavailable_read_only"


@dataclass(frozen=True, slots=True)
class BrokerSnapshot:
    """One bounded, read-only broker snapshot."""

    connected: bool
    mode: str
    balances: tuple[AccountBalance, ...]
    positions: tuple[BrokerPosition, ...]
    open_orders: tuple[BrokerOpenOrder, ...]
    open_orders_availability: OpenOrdersAvailability
