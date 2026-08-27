from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.app.broker_config import (
    BrokerConfiguration,
    BrokerConfigurationError,
    build_broker_provider,
    build_paper_order_executor,
    load_broker_configuration,
)
from private_quant.broker.ibkr import IbkrBrokerProvider
from private_quant.broker.order_base import OrderSubmissionDisabledError
from private_quant.broker.ibkr_orders import IbkrPaperOrderExecutor
from private_quant.broker.order_base import OrderPreviewRequiredError
from private_quant.broker.order_models import (
    OrderIntent,
    OrderPreview,
    OrderSide,
    OrderType,
    QuoteSource,
)


VALID_CONFIGURATION = (
    "BROKER_PROVIDER=ibkr\n"
    "BROKER_MODE=paper\n"
    "BROKER_HOST=127.0.0.1\n"
    "BROKER_PORT=7497\n"
    "BROKER_CLIENT_ID=10\n"
)


def make_external_preview() -> OrderPreview:
    created_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    return OrderPreview(
        preview_id="external-preview",
        intent=OrderIntent(
            "AAPL", OrderSide.BUY, OrderType.LIMIT,
            limit_price=Decimal("100"),
        ),
        estimated_unit_price=Decimal("100"),
        estimated_notional=Decimal("100"),
        quote_source=QuoteSource.USER_LIMIT,
        created_at=created_at,
        expires_at=created_at + timedelta(seconds=60),
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

    def test_paper_submit_flag_is_fail_closed(self) -> None:
        cases = {
            None: False,
            "": False,
            "   ": False,
            "false": False,
            "1": False,
            "yes": False,
            "on": False,
            "truthy": False,
            "true false": False,
            "true": True,
            " TRUE ": True,
            "TrUe": True,
        }

        for raw_value, expected in cases.items():
            with self.subTest(raw_value=raw_value):
                contents = VALID_CONFIGURATION
                if raw_value is not None:
                    contents += f"IBKR_PAPER_SUBMIT_ENABLED={raw_value}\n"
                configuration = load_broker_configuration(
                    self.write_env(contents), environment={}
                )
                self.assertIs(configuration.paper_submit_enabled, expected)

    def test_process_environment_can_only_enable_with_exact_true(self) -> None:
        configuration = load_broker_configuration(
            self.write_env(
                VALID_CONFIGURATION + "IBKR_PAPER_SUBMIT_ENABLED=false\n"
            ),
            environment={"IBKR_PAPER_SUBMIT_ENABLED": "  TRUE  "},
        )
        self.assertTrue(configuration.paper_submit_enabled)

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

    def test_builds_production_order_executor_with_submission_disabled(self) -> None:
        configuration = BrokerConfiguration(
            provider_name="ibkr",
            mode="paper",
            host="127.0.0.1",
            port=7497,
            client_id=10,
        )
        session_created = False

        def create_session():
            nonlocal session_created
            session_created = True
            return object()

        executor = build_paper_order_executor(
            configuration,
            session_factory=create_session,
        )

        self.assertIsInstance(executor, IbkrPaperOrderExecutor)
        with self.assertRaises(OrderSubmissionDisabledError):
            executor.submit_order(object())
        self.assertFalse(session_created)

    def test_enabled_builder_reaches_preview_validation_not_disabled_gate(self) -> None:
        configuration = BrokerConfiguration(
            provider_name="ibkr",
            mode="paper",
            host="127.0.0.1",
            port=7497,
            client_id=10,
            paper_submit_enabled=True,
        )
        executor = build_paper_order_executor(
            configuration, session_factory=lambda: object()
        )

        with self.assertRaises(OrderPreviewRequiredError):
            executor.submit_order(make_external_preview())

    def test_disabled_builder_still_fails_before_session_creation(self) -> None:
        session_created = False

        def create_session():
            nonlocal session_created
            session_created = True
            return object()

        configuration = BrokerConfiguration(
            provider_name="ibkr",
            mode="paper",
            host="127.0.0.1",
            port=7497,
            client_id=10,
            paper_submit_enabled=False,
        )
        executor = build_paper_order_executor(
            configuration, session_factory=create_session
        )

        with self.assertRaises(OrderSubmissionDisabledError):
            executor.submit_order(make_external_preview())
        self.assertFalse(session_created)

    def test_builder_fails_closed_for_non_boolean_truthy_submit_values(
        self,
    ) -> None:
        for raw_value in ("yes", 1):
            with self.subTest(raw_value=raw_value):
                session_created = False

                def create_session():
                    nonlocal session_created
                    session_created = True
                    return object()

                configuration = BrokerConfiguration(
                    provider_name="ibkr",
                    mode="paper",
                    host="127.0.0.1",
                    port=7497,
                    client_id=10,
                    paper_submit_enabled=raw_value,
                )
                executor = build_paper_order_executor(
                    configuration, session_factory=create_session
                )

                with self.assertRaises(OrderSubmissionDisabledError):
                    executor.submit_order(make_external_preview())
                self.assertFalse(session_created)

    def test_enabled_builder_rejects_every_unsafe_endpoint_before_session_creation(
        self,
    ) -> None:
        cases = (
            {"provider_name": "other"},
            {"mode": "live"},
            {"host": "localhost"},
            {"port": 7496},
            {"client_id": 0},
        )

        for overrides in cases:
            with self.subTest(overrides=overrides):
                session_created = False

                def create_session():
                    nonlocal session_created
                    session_created = True
                    return object()

                values = {
                    "provider_name": "ibkr",
                    "mode": "paper",
                    "host": "127.0.0.1",
                    "port": 7497,
                    "client_id": 10,
                    "paper_submit_enabled": True,
                }
                values.update(overrides)
                configuration = BrokerConfiguration(**values)

                with self.assertRaises(BrokerConfigurationError):
                    build_paper_order_executor(
                        configuration, session_factory=create_session
                    )
                self.assertFalse(session_created)

    def test_order_executor_rejects_wrong_provider_name(self) -> None:
        configuration = BrokerConfiguration(
            provider_name="other",
            mode="paper",
            host="127.0.0.1",
            port=7497,
            client_id=10,
        )

        with self.assertRaises(BrokerConfigurationError):
            build_paper_order_executor(configuration)


if __name__ == "__main__":
    unittest.main()
