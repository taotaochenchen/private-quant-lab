"""Framework-independent, immutable paper-order domain models."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class OrderSide(StrEnum):
    """Supported paper-order directions."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    """Supported paper-order types."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"


class QuoteSource(StrEnum):
    """Price source used for the Preview estimate."""

    IBKR_LIVE_ASK = "ibkr_live_ask"
    IBKR_LIVE_BID = "ibkr_live_bid"
    USER_LIMIT = "user_limit"


class OrderStatus(StrEnum):
    """Sanitized order lifecycle states."""

    PENDING_SUBMIT = "pending_submit"
    PRE_SUBMITTED = "pre_submitted"
    SUBMITTED = "submitted"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """A normalized paper-order request before broker validation."""

    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int = 1
    limit_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class OrderPreview:
    """A short-lived, one-time estimate bound to one exact intent."""

    preview_id: str
    intent: OrderIntent
    estimated_unit_price: Decimal
    estimated_notional: Decimal
    quote_source: QuoteSource
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class OrderResult:
    """A sanitized broker result without an account identifier."""

    preview_id: str
    broker_order_id: int
    status: OrderStatus
    filled_quantity: Decimal
    remaining_quantity: Decimal
    average_fill_price: Decimal | None


__all__ = [
    "OrderIntent",
    "OrderPreview",
    "OrderResult",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "QuoteSource",
]
