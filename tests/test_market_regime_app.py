import ast
from datetime import date, timedelta
from pathlib import Path
import importlib
from importlib.util import resolve_name
import sys
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.app.config import ConfigurationError
from private_quant.data.models import PriceBar
from private_quant.data.tiingo import (
    TiingoAuthenticationError,
    TiingoError,
    TiingoRateLimitError,
    TiingoRequestError,
    TiingoSymbolNotFoundError,
)
from private_quant.risk import (
    ConfirmationStatus,
    MarketRegime,
    RegimeComponent,
    RegimeConfidence,
    RegimeConfidenceEvidence,
    RegimeDataQuality,
    RegimeMetric,
    RegimeResult,
    StrategyPermission,
)
from private_quant.risk.market_regime import (
    InsufficientRegimeHistoryError,
    InvalidRegimeDataError,
    StaleRegimeDataError,
)

from private_quant.app import market_regime
from private_quant.app.market_regime import (
    evaluate_current_regime,
    load_regime_histories,
    regime_error_message,
)


APP_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "private_quant"
    / "app"
    / "market_regime.py"
)
REGIME_SOURCE_PATHS = (
    Path(__file__).resolve().parents[1] / "src" / "private_quant" / "risk" / "market_regime.py",
    Path(__file__).resolve().parents[1]
    / "src"
    / "private_quant"
    / "backtest"
    / "regime_evaluation.py",
    APP_PATH,
)
REGIME_SOURCE_PACKAGES = {
    REGIME_SOURCE_PATHS[0]: "private_quant.risk",
    REGIME_SOURCE_PATHS[1]: "private_quant.backtest",
    REGIME_SOURCE_PATHS[2]: "private_quant.app",
}
_FORBIDDEN_ORDER_CALLS = {
    "placeOrder",
    "submit_order",
    "preview_order",
    "cancelOrder",
    "reqIds",
}


def _imported_modules(
    tree: ast.AST,
    *,
    package: str = "private_quant.risk",
) -> tuple[str, ...]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, package)
            if module:
                modules.append(module)
                modules.extend(
                    f"{module}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                )
    return tuple(modules)


def _direct_dotenv_accesses(tree: ast.AST) -> tuple[ast.Call, ...]:
    accesses: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function_name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else ""
        )
        if function_name not in {"open", "Path", "read_text", "read_bytes", "write_text", "write_bytes"}:
            continue
        if any(
            isinstance(argument, ast.Constant)
            and isinstance(argument.value, str)
            and ".env" in argument.value
            for argument in node.args
        ):
            accesses.append(node)
    return tuple(accesses)


class MarketRegimeSourceSafetyTests(unittest.TestCase):
    def test_broker_import_detection_covers_aliases_and_relative_forms(self) -> None:
        cases = (
            "import private_quant.broker as broker",
            "from private_quant import broker",
            "from private_quant import broker as safety_broker",
            "from ..broker import Client",
            "from .. import broker",
        )

        for source in cases:
            with self.subTest(source=source):
                self.assertIn(
                    "private_quant.broker",
                    _imported_modules(ast.parse(source)),
                )

    def test_regime_sources_keep_provider_and_order_boundaries(self) -> None:
        """Catches broker imports, direct dotenv I/O, and order-capable calls."""

        parsed_sources = {
            source_path: ast.parse(source_path.read_text(encoding="utf-8"))
            for source_path in REGIME_SOURCE_PATHS
        }
        risk_and_evaluator = REGIME_SOURCE_PATHS[:2]

        for source_path in risk_and_evaluator:
            with self.subTest(source=source_path.name, check="imports"):
                imports = _imported_modules(
                    parsed_sources[source_path],
                    package=REGIME_SOURCE_PACKAGES[source_path],
                )
                self.assertFalse(
                    any(
                        module == "streamlit" or module.startswith("streamlit.")
                        or module == "private_quant.broker"
                        or module.startswith("private_quant.broker.")
                        for module in imports
                    )
                )

        for source_path, tree in parsed_sources.items():
            with self.subTest(source=source_path.name, check="dotenv"):
                self.assertEqual(_direct_dotenv_accesses(tree), ())
            with self.subTest(source=source_path.name, check="order_calls"):
                forbidden_calls = [
                    node.func.attr
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _FORBIDDEN_ORDER_CALLS
                ]
                self.assertEqual(forbidden_calls, [])
            with self.subTest(source=source_path.name, check="paper_submit_flag"):
                self.assertNotIn(
                    "IBKR_PAPER_SUBMIT_ENABLED",
                    source_path.read_text(encoding="utf-8"),
                )


def make_bar(symbol: str, trading_date: date, close: float = 100.0) -> PriceBar:
    return PriceBar(
        symbol=symbol,
        trading_date=trading_date,
        open=close,
        high=close,
        low=close,
        close=close,
        adjusted_close=close,
        volume=1_000_000,
    )


def make_result(*, qqq_available: bool = True) -> RegimeResult:
    as_of = date(2026, 8, 26)
    qqq_status = (
        ConfirmationStatus.CONFIRMS_POSITIVE
        if qqq_available
        else ConfirmationStatus.UNAVAILABLE
    )
    components = (
        RegimeComponent(
            "Primary trend",
            40,
            40,
            (
                RegimeMetric("SPY close", 650.25, "price", "Latest adjusted close"),
                RegimeMetric("SMA200 slope", 0.081, "ratio", "SMA200 comparison"),
            ),
            "Primary trend score +40 from price and moving averages.",
        ),
        RegimeComponent(
            "Momentum",
            20,
            20,
            (RegimeMetric("60-session return", 0.091, "ratio", "Trailing return"),),
            "Momentum score +20 from recent returns.",
        ),
    )
    return RegimeResult(
        evaluation_date=as_of,
        regime=MarketRegime.BULL,
        score=60,
        confidence=RegimeConfidence.HIGH,
        confidence_evidence=RegimeConfidenceEvidence(15, 2, qqq_status),
        maximum_long_exposure=1.0,
        strategy_permission=StrategyPermission.NORMAL,
        components=components,
        reasons=(
            "Primary trend is positive.",
            "QQQ confirms the positive regime.",
        ),
        data_quality=RegimeDataQuality(
            requested_date=as_of,
            latest_spy_date=as_of,
            data_age_days=0,
            observations_used=252,
            required_observations=252,
            is_valid=True,
            qqq_status=qqq_status,
            warnings=("QQQ confirmation unavailable.",) if not qqq_available else (),
        ),
    )


def make_valid_spy_history(as_of: date) -> tuple[PriceBar, ...]:
    return tuple(
        make_bar("SPY", as_of - timedelta(days=251 - index), 100.0 + index * 0.2)
        for index in range(252)
    )


class MarketRegimeAppLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        load_regime_histories.clear()
        self.addCleanup(load_regime_histories.clear)

    def test_loader_requests_spy_and_qqq_for_the_fixed_window(self) -> None:
        as_of = date(2026, 8, 26)
        expected_configuration = object()

        class Provider:
            def __init__(self) -> None:
                self.requests: list[tuple[str, date, date]] = []

            def get_price_history(self, symbol: str, start: date, end: date):
                self.requests.append((symbol, start, end))
                return (make_bar(symbol, as_of),)

        provider = Provider()
        with patch.object(
            market_regime, "load_app_configuration", return_value=expected_configuration
        ), patch.object(
            market_regime, "build_market_data_provider", return_value=provider
        ):
            histories = load_regime_histories(as_of)

        self.assertEqual(histories, ((make_bar("SPY", as_of),), (make_bar("QQQ", as_of),)))
        self.assertEqual(
            provider.requests,
            [
                ("SPY", as_of - timedelta(days=550), as_of),
                ("QQQ", as_of - timedelta(days=550), as_of),
            ],
        )

    def test_spy_failure_propagates_to_fixed_safe_error_message(self) -> None:
        as_of = date(2026, 8, 26)

        class Provider:
            def get_price_history(self, symbol: str, start: date, end: date):
                raise TiingoRequestError("internal network detail")

        with patch.object(market_regime, "load_app_configuration", return_value=object()), patch.object(
            market_regime, "build_market_data_provider", return_value=Provider()
        ):
            with self.assertRaises(TiingoRequestError) as raised:
                load_regime_histories(as_of)

        self.assertEqual(
            regime_error_message(raised.exception),
            "Market data is temporarily unavailable. Check your network and try again.",
        )
        self.assertNotIn("internal network detail", regime_error_message(raised.exception))

    def test_qqq_provider_failure_becomes_empty_optional_history(self) -> None:
        as_of = date(2026, 8, 26)

        class Provider:
            def get_price_history(self, symbol: str, start: date, end: date):
                if symbol == "QQQ":
                    raise TiingoError("optional history failure")
                return make_valid_spy_history(as_of)

        with patch.object(market_regime, "load_app_configuration", return_value=object()), patch.object(
            market_regime, "build_market_data_provider", return_value=Provider()
        ):
            spy, qqq = load_regime_histories(as_of)

        self.assertEqual(spy, make_valid_spy_history(as_of))
        self.assertEqual(qqq, ())
        result = evaluate_current_regime(as_of, history_loader=lambda _: (spy, qqq))
        self.assertTrue(result.data_quality.is_valid)
        self.assertIs(result.regime, MarketRegime.BULL)
        self.assertIs(result.data_quality.qqq_status, ConfirmationStatus.UNAVAILABLE)

    def test_evaluator_forwards_the_exact_requested_date(self) -> None:
        requested = date(2026, 8, 26)
        result = make_result()
        spy = (make_bar("SPY", requested),)
        qqq = (make_bar("QQQ", requested),)

        class Engine:
            def __init__(self) -> None:
                self.calls: list[tuple[tuple[PriceBar, ...], date, tuple[PriceBar, ...]]] = []

            def evaluate(self, spy_bars, *, as_of, qqq_bars):
                self.calls.append((spy_bars, as_of, qqq_bars))
                return result

        engine = Engine()
        with patch.object(market_regime, "MarketRegimeEngine", return_value=engine):
            actual = evaluate_current_regime(requested, history_loader=lambda _: (spy, qqq))

        self.assertIs(actual, result)
        self.assertEqual(engine.calls, [(spy, requested, qqq)])

    def test_importing_page_does_not_load_configuration_or_provider(self) -> None:
        module_name = "private_quant.app.market_regime"
        original = sys.modules.pop(module_name, None)
        try:
            with patch(
                "private_quant.app.config.load_app_configuration",
                side_effect=AssertionError("configuration must not load"),
            ) as configuration_loader, patch(
                "private_quant.app.config.build_market_data_provider",
                side_effect=AssertionError("provider must not build"),
            ) as provider_builder:
                importlib.import_module(module_name)
            configuration_loader.assert_not_called()
            provider_builder.assert_not_called()
        finally:
            sys.modules.pop(module_name, None)
            if original is not None:
                sys.modules[module_name] = original

    def test_expected_failures_have_fixed_safe_messages(self) -> None:
        sentinel = "sensitive provider detail"
        cases = (
            (ConfigurationError(sentinel), "Market data setup is incomplete. Check MARKET_DATA_PROVIDER and MARKET_DATA_API_KEY in your local .env file."),
            (TiingoAuthenticationError(sentinel), "Tiingo authentication failed. Check MARKET_DATA_API_KEY in your local .env file."),
            (TiingoRateLimitError(sentinel), "Tiingo's request limit was reached. Please try again later."),
            (TiingoSymbolNotFoundError(sentinel), "No market data found. Please try again later."),
            (TiingoRequestError(sentinel), "Market data is temporarily unavailable. Check your network and try again."),
            (InsufficientRegimeHistoryError(sentinel), "Not enough SPY history is available to evaluate the market regime."),
            (InvalidRegimeDataError(sentinel), "Market regime data is invalid. Please try again later."),
            (StaleRegimeDataError(sentinel), "Market regime data is stale. Please try again after market data updates."),
        )
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                message = regime_error_message(error)
                self.assertEqual(message, expected)
                self.assertNotIn(sentinel, message)


class MarketRegimeRenderingTests(unittest.TestCase):
    def test_renders_result_metrics_evidence_reasons_and_data_quality(self) -> None:
        app = AppTest.from_string(
            """
from private_quant.app.market_regime import render_regime_result
from tests.test_market_regime_app import make_result
render_regime_result(make_result())
"""
        ).run(timeout=20)

        self.assertEqual(
            [(metric.label, metric.value) for metric in app.metric],
            [
                ("Regime", "BULL"),
                ("Score", "+60"),
                ("Confidence", "HIGH"),
                ("Maximum exposure", "100%"),
                ("Strategy permission", "NORMAL"),
            ],
        )
        self.assertEqual(len(app.dataframe), 1)
        evidence = app.dataframe[0].value
        self.assertEqual(len(evidence), 2)
        self.assertEqual(list(evidence.columns), ["Component", "Raw values", "Score", "Explanation"])
        self.assertIn("SPY close: 650.25", evidence.iloc[0]["Raw values"])
        self.assertEqual(evidence.iloc[0]["Score"], "+40")
        self.assertIn(
            "Primary trend is positive.",
            " ".join(item.value for item in app.markdown),
        )
        rendered = " ".join(item.value for item in app.markdown)
        self.assertIn("Requested date", rendered)
        self.assertIn("Observations used", rendered)
        self.assertEqual(len(app.warning), 0)
        self.assertEqual(len(app.exception), 0)

    def test_renders_qqq_unavailable_warning(self) -> None:
        app = AppTest.from_string(
            """
from private_quant.app.market_regime import render_regime_result
from tests.test_market_regime_app import make_result
render_regime_result(make_result(qqq_available=False))
"""
        ).run(timeout=20)

        self.assertEqual(app.warning[0].value, "QQQ confirmation unavailable.")
        self.assertEqual(len(app.exception), 0)

    def test_page_starts_safe_and_has_no_trading_controls(self) -> None:
        app = AppTest.from_file(str(APP_PATH)).run(timeout=20)

        self.assertEqual(app.title[0].value, "Market Regime")
        self.assertIn(
            "Research guidance only — this deterministic regime estimate is not investment advice or certainty, and it cannot place orders.",
            " ".join(item.value for item in app.warning),
        )
        self.assertEqual([button.label for button in app.button], ["Evaluate regime"])
        self.assertEqual(len(app.metric), 0)
        self.assertEqual(len(app.exception), 0)
        rendered = repr(app).upper()
        for forbidden in ("BUY", "SELL", "SUBMIT ORDER", "LIVE TRADING"):
            self.assertNotIn(forbidden, rendered)

    def test_fake_history_loader_is_used_only_after_evaluate_button_click(self) -> None:
        source = """
import streamlit as st
from private_quant.app import market_regime
from tests.test_market_regime_app import make_valid_spy_history

st.session_state.setdefault("_fake_history_loader_calls", 0)
def fake_history_loader(as_of):
    st.session_state["_fake_history_loader_calls"] += 1
    return make_valid_spy_history(as_of), ()

def evaluate_with_fake_history(as_of):
    return market_regime.evaluate_current_regime(
        as_of,
        history_loader=fake_history_loader,
    )

market_regime.main(regime_evaluator=evaluate_with_fake_history)
"""
        app = AppTest.from_string(source).run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["_fake_history_loader_calls"], 0)
        app.button(key="evaluate_regime").click().run(timeout=20)
        self.assertEqual(app.session_state["_fake_history_loader_calls"], 1)
        self.assertEqual(len(app.metric), 5)
        self.assertEqual(len(app.exception), 0)


if __name__ == "__main__":
    unittest.main()
