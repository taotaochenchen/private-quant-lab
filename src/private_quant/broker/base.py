"""Broker contracts that do not depend on any vendor or UI framework."""

from typing import Protocol

from private_quant.broker.models import BrokerSnapshot


class BrokerError(RuntimeError):
    """Base error for safe broker failures."""


class BrokerConfigurationError(BrokerError):
    """Raised before connection when the paper-only configuration is unsafe."""


class OfficialIbapiUnavailableError(BrokerError):
    """Raised when IBKR's separately installed official package is unavailable."""


class BrokerConnectionError(BrokerError):
    """Raised when the local TWS connection cannot complete."""


class BrokerDataTimeoutError(BrokerError):
    """Raised when required read-only account data does not complete."""


class BrokerAccountScopeError(BrokerError):
    """Raised when a snapshot spans more than one broker account."""


class BrokerProvider(Protocol):
    """Framework-independent read-only broker provider."""

    def get_read_only_snapshot(self) -> BrokerSnapshot:
        """Return one sanitized snapshot without account identifiers."""


__all__ = [
    "BrokerAccountScopeError",
    "BrokerConfigurationError",
    "BrokerConnectionError",
    "BrokerDataTimeoutError",
    "BrokerError",
    "BrokerProvider",
    "OfficialIbapiUnavailableError",
]
