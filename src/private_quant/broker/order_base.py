"""Provider-independent paper-order execution contract and safe errors."""

from typing import Protocol

from private_quant.broker.order_models import (
    OrderIntent,
    OrderPreview,
    OrderResult,
)


class PaperOrderError(RuntimeError):
    """Base class for safe paper-order failures."""


class OrderConfigurationError(PaperOrderError):
    """Raised when a paper-order endpoint is unsafe."""


class InvalidOrderIntentError(PaperOrderError):
    """Raised when an order intent is malformed."""


class UnsupportedContractError(PaperOrderError):
    """Raised when a unique US stock or ETF cannot be resolved."""


class OrderQuoteUnavailableError(PaperOrderError):
    """Raised when a requested IBKR live snapshot price is unavailable."""


class OrderNotionalLimitError(PaperOrderError):
    """Raised when a paper order exceeds its safety threshold."""


class OrderPreviewRequiredError(PaperOrderError):
    """Raised when Submit lacks the exact issued Preview."""


class OrderPreviewExpiredError(PaperOrderError):
    """Raised when a Preview is no longer current."""


class DuplicateOrderSubmissionError(PaperOrderError):
    """Raised when a Preview has already been consumed."""


class OrderSubmissionDisabledError(PaperOrderError):
    """Raised while the production submission safety lock is active."""


class OrderConnectionError(PaperOrderError):
    """Raised when the local paper-order session cannot become ready."""


class OrderStatusTimeoutError(PaperOrderError):
    """Raised when no sanitized initial order status arrives in time."""


class PaperOrderExecutionProvider(Protocol):
    """Separate PAPER-only Preview and execution interface."""

    def preview_order(self, intent: OrderIntent) -> OrderPreview:
        """Validate and issue a short-lived, one-time Preview."""

    def submit_order(self, preview: OrderPreview) -> OrderResult:
        """Consume an issued Preview and return a sanitized result."""


__all__ = [
    "DuplicateOrderSubmissionError",
    "InvalidOrderIntentError",
    "OrderConfigurationError",
    "OrderConnectionError",
    "OrderNotionalLimitError",
    "OrderPreviewExpiredError",
    "OrderPreviewRequiredError",
    "OrderQuoteUnavailableError",
    "OrderStatusTimeoutError",
    "OrderSubmissionDisabledError",
    "PaperOrderError",
    "PaperOrderExecutionProvider",
    "UnsupportedContractError",
]
