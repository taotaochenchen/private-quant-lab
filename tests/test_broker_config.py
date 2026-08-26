from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.app.broker_config import (
    BrokerConfiguration,
    BrokerConfigurationError,
    build_broker_provider,
    load_broker_configuration,
)
from private_quant.broker.ibkr import IbkrBrokerProvider


VALID_CONFIGURATION = (
    "BROKER_PROVIDER=ibkr\n"
    "BROKER_MODE=paper\n"
    "BROKER_HOST=127.0.0.1\n"
    "BROKER_PORT=7497\n"
    "BROKER_CLIENT_ID=10\n"
)


class BrokerConfigurationTests(unittest.TestCase):
    def write_env(self, contents: str) -> Path:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        env_path = Path(temporary_directory.name) / ".env"
        env_path.write_text(contents, encoding="utf-8")
        return env_path

    def test_loads_exact_paper_configuration(self) -> None:
        configuration = load_broker_configuration(
            self.write_env(VALID_CONFIGURATION), environment={}
        )

        self.assertEqual(
            configuration,
            BrokerConfiguration(
                provider_name="ibkr",
                mode="paper",
                host="127.0.0.1",
                port=7497,
                client_id=10,
            ),
        )

    def test_process_environment_overrides_broker_values_only(self) -> None:
        configuration = load_broker_configuration(
            self.write_env("BROKER_PROVIDER=wrong\n"),
            environment={
                "BROKER_PROVIDER": " IBKR ",
                "BROKER_MODE": " PAPER ",
                "BROKER_HOST": "127.0.0.1",
                "BROKER_PORT": "7497",
                "BROKER_CLIENT_ID": "10",
                "MARKET_DATA_API_KEY": "must-not-affect-broker-config",
            },
        )

        self.assertEqual(configuration.provider_name, "ibkr")
        self.assertEqual(configuration.mode, "paper")

    def test_refuses_every_unsafe_or_missing_configuration(self) -> None:
        cases = (
            ("BROKER_PROVIDER", "other"),
            ("BROKER_MODE", "live"),
            ("BROKER_HOST", "localhost"),
            ("BROKER_PORT", "7496"),
            ("BROKER_CLIENT_ID", "0"),
            ("BROKER_PORT", "not-a-number"),
            ("BROKER_CLIENT_ID", "not-a-number"),
            ("BROKER_MODE", ""),
        )

        for name, value in cases:
            with self.subTest(name=name, value=value):
                values = {
                    "BROKER_PROVIDER": "ibkr",
                    "BROKER_MODE": "paper",
                    "BROKER_HOST": "127.0.0.1",
                    "BROKER_PORT": "7497",
                    "BROKER_CLIENT_ID": "10",
                }
                values[name] = value
                contents = "".join(
                    f"{key}={item}\n" for key, item in values.items()
                )

                with self.assertRaises(BrokerConfigurationError) as raised:
                    load_broker_configuration(
                        self.write_env(contents), environment={}
                    )

                self.assertIn("paper broker configuration", str(raised.exception))

    def test_safe_error_does_not_reflect_unexpected_values(self) -> None:
        sentinel = "sensitive-account-like-value"
        contents = VALID_CONFIGURATION.replace("ibkr", sentinel)

        with self.assertRaises(BrokerConfigurationError) as raised:
            load_broker_configuration(self.write_env(contents), environment={})

        self.assertNotIn(sentinel, str(raised.exception))

    def test_invalid_numeric_value_is_not_retained_in_exception_chain(self) -> None:
        sentinel = "DU1234567-sensitive-config-value"
        contents = VALID_CONFIGURATION.replace("7497", sentinel)

        with self.assertRaises(BrokerConfigurationError) as raised:
            load_broker_configuration(self.write_env(contents), environment={})

        self.assertNotIn(sentinel, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_builds_ibkr_provider_from_validated_primitive_values(self) -> None:
        configuration = BrokerConfiguration(
            provider_name="ibkr",
            mode="paper",
            host="127.0.0.1",
            port=7497,
            client_id=10,
        )

        provider = build_broker_provider(
            configuration,
            session_factory=lambda: object(),
        )

        self.assertIsInstance(provider, IbkrBrokerProvider)


if __name__ == "__main__":
    unittest.main()
