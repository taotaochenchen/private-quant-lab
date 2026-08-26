"""Strict paper-only configuration for the local broker status page."""

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import dotenv_values

from private_quant.broker.base import BrokerConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_BROKER_NAMES = (
    "BROKER_PROVIDER",
    "BROKER_MODE",
    "BROKER_HOST",
    "BROKER_PORT",
    "BROKER_CLIENT_ID",
)
_SAFE_CONFIGURATION_MESSAGE = (
    "Invalid paper broker configuration. Required: BROKER_PROVIDER=ibkr, "
    "BROKER_MODE=paper, BROKER_HOST=127.0.0.1, BROKER_PORT=7497, and "
    "BROKER_CLIENT_ID=10."
)


@dataclass(frozen=True, slots=True)
class BrokerConfiguration:
    """Exact Phase 1 connection settings without credentials."""

    provider_name: str
    mode: str
    host: str
    port: int
    client_id: int


def load_broker_configuration(
    env_path: str | Path = PROJECT_ROOT / ".env",
    *,
    environment: Mapping[str, str] | None = None,
) -> BrokerConfiguration:
    """Load and enforce the exact loopback TWS Paper configuration."""

    values = dotenv_values(env_path)
    overrides = os.environ if environment is None else environment
    for name in _BROKER_NAMES:
        if name in overrides:
            values[name] = overrides[name]

    provider_name = str(values.get("BROKER_PROVIDER") or "").strip().lower()
    mode = str(values.get("BROKER_MODE") or "").strip().lower()
    host = str(values.get("BROKER_HOST") or "").strip()
    try:
        port = int(str(values.get("BROKER_PORT") or "").strip())
        client_id = int(str(values.get("BROKER_CLIENT_ID") or "").strip())
    except ValueError as exc:
        raise BrokerConfigurationError(_SAFE_CONFIGURATION_MESSAGE) from exc

    configuration = BrokerConfiguration(
        provider_name=provider_name,
        mode=mode,
        host=host,
        port=port,
        client_id=client_id,
    )
    if configuration != BrokerConfiguration(
        provider_name="ibkr",
        mode="paper",
        host="127.0.0.1",
        port=7497,
        client_id=10,
    ):
        raise BrokerConfigurationError(_SAFE_CONFIGURATION_MESSAGE)
    return configuration
