"""Safe local configuration for the stock research app."""

from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from private_quant.data.base import MarketDataProvider
from private_quant.data.tiingo import TiingoMarketDataProvider

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ConfigurationError(RuntimeError):
    """Raised when local market-data configuration is unusable."""


@dataclass(frozen=True, slots=True)
class AppConfiguration:
    """Required provider settings with the credential redacted from repr."""

    provider_name: str
    api_key: str = field(repr=False)


def load_app_configuration(
    env_path: str | Path = PROJECT_ROOT / ".env",
) -> AppConfiguration:
    """Read the market-data provider and credential from a local .env file."""

    values = dotenv_values(env_path)
    provider_name = str(values.get("MARKET_DATA_PROVIDER") or "").strip().lower()
    api_key = str(values.get("MARKET_DATA_API_KEY") or "").strip()

    if not provider_name:
        raise ConfigurationError(
            "MARKET_DATA_PROVIDER is missing. Add it to the local .env file."
        )
    if not api_key:
        raise ConfigurationError(
            "MARKET_DATA_API_KEY is missing. Add it to the local .env file."
        )

    return AppConfiguration(provider_name=provider_name, api_key=api_key)


def build_market_data_provider(
    configuration: AppConfiguration,
) -> MarketDataProvider:
    """Construct the configured provider without exposing its credential."""

    if configuration.provider_name.strip().lower() != "tiingo":
        raise ConfigurationError(
            "Unsupported market data provider. Set MARKET_DATA_PROVIDER=tiingo."
        )
    return TiingoMarketDataProvider(configuration.api_key)
