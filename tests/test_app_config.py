from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.app.config import (
    AppConfiguration,
    ConfigurationError,
    build_market_data_provider,
    load_app_configuration,
)
from private_quant.data.tiingo import TiingoMarketDataProvider


class AppConfigurationTests(unittest.TestCase):
    def write_env(self, contents: str) -> Path:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        env_path = Path(temporary_directory.name) / ".env"
        env_path.write_text(contents, encoding="utf-8")
        return env_path

    def test_loads_and_normalizes_local_env_without_exposing_key_in_repr(self) -> None:
        env_path = self.write_env(
            "MARKET_DATA_PROVIDER= TiInGo \n"
            "MARKET_DATA_API_KEY=sensitive-token-value\n"
        )

        configuration = load_app_configuration(env_path)

        self.assertEqual(configuration.provider_name, "tiingo")
        self.assertEqual(configuration.api_key, "sensitive-token-value")
        self.assertNotIn("sensitive-token-value", repr(configuration))

    def test_missing_configuration_raises_safe_setup_message(self) -> None:
        cases = (
            ("MARKET_DATA_API_KEY=sensitive-token-value\n", "MARKET_DATA_PROVIDER"),
            ("MARKET_DATA_PROVIDER=tiingo\n", "MARKET_DATA_API_KEY"),
        )

        for contents, missing_name in cases:
            with self.subTest(missing_name=missing_name):
                env_path = self.write_env(contents)
                with self.assertRaises(ConfigurationError) as raised:
                    load_app_configuration(env_path)
                self.assertIn(missing_name, str(raised.exception))
                self.assertNotIn("sensitive-token-value", str(raised.exception))

    def test_builds_existing_tiingo_provider_case_insensitively(self) -> None:
        configuration = AppConfiguration(
            provider_name=" TiInGo ", api_key="sensitive-token-value"
        )

        provider = build_market_data_provider(configuration)

        self.assertIsInstance(provider, TiingoMarketDataProvider)

    def test_rejects_unsupported_provider_without_reflecting_key(self) -> None:
        configuration = AppConfiguration(
            provider_name="unsupported", api_key="sensitive-token-value"
        )

        with self.assertRaises(ConfigurationError) as raised:
            build_market_data_provider(configuration)

        self.assertIn("MARKET_DATA_PROVIDER=tiingo", str(raised.exception))
        self.assertNotIn("sensitive-token-value", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
