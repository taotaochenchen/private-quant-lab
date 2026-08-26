from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.app.config import ConfigurationError
from private_quant.app.stock_research import (
    chart_rows,
    error_message_for,
    format_mention_change,
    load_apewisdom_page,
    lookup_ticker,
    perform_search,
    recent_price_rows,
    render_social_buzz,
    social_buzz_error_message,
)
from private_quant.data.models import PriceBar
from private_quant.data.tiingo import (
    TiingoAuthenticationError,
    TiingoRateLimitError,
    TiingoRequestError,
    TiingoSymbolNotFoundError,
)
from private_quant.research.stock_lookup import (
    BlankTickerError,
    NoMarketDataError,
    StockResearchResult,
)
from private_quant.social.apewisdom import (
    ApeWisdomRequestError,
    ApeWisdomResponseError,
    SocialBuzz,
)


def make_bar(trading_date: date, close: float) -> PriceBar:
    return PriceBar(
        symbol="AAPL",
        trading_date=trading_date,
        open=close - 1.0,
        high=close + 2.0,
        low=close - 2.0,
        close=close,
        adjusted_close=close - 0.25,
        volume=int(close * 1_000),
    )


def make_price_result() -> StockResearchResult:
    bar = make_bar(date(2026, 8, 25), 102.0)
    return StockResearchResult(
        ticker="AAPL",
        start_date=date(2025, 8, 25),
        end_date=date(2026, 8, 25),
        history=(bar,),
        latest_bar=bar,
        daily_change_percent=None,
    )


def make_social_buzz() -> SocialBuzz:
    return SocialBuzz(
        ticker="AAPL",
        reddit_rank=7,
        mentions=317,
        previous_mentions=281,
        mention_change_percent=12.8113879,
        upvotes=4_074,
        trend="Rising",
    )


class StockResearchAppTests(unittest.TestCase):
    def test_cached_apewisdom_page_reuses_raw_response(self) -> None:
        payload = {
            "pages": 1,
            "current_page": 1,
            "results": [],
        }
        load_apewisdom_page.clear()
        self.addCleanup(load_apewisdom_page.clear)

        with patch(
            "private_quant.app.stock_research.fetch_apewisdom_page",
            return_value=payload,
        ) as raw_fetch:
            first = load_apewisdom_page(1)
            second = load_apewisdom_page(1)

        self.assertEqual(first, payload)
        self.assertEqual(second, payload)
        raw_fetch.assert_called_once_with(1)

    def test_perform_search_preserves_price_when_social_lookup_fails(self) -> None:
        price_result = make_price_result()
        social_error = ApeWisdomRequestError("sensitive details")

        def fail_social(ticker: str):
            raise social_error

        outcome = perform_search(
            " aapl ",
            price_loader=lambda ticker: price_result,
            social_loader=fail_social,
        )

        self.assertEqual(outcome.ticker, "AAPL")
        self.assertIs(outcome.price_result, price_result)
        self.assertIsNone(outcome.price_error)
        self.assertIsNone(outcome.social_buzz)
        self.assertIs(outcome.social_error, social_error)

    def test_perform_search_runs_social_when_price_lookup_fails(self) -> None:
        price_error = TiingoRequestError("sensitive details")
        social_buzz = make_social_buzz()

        def fail_price(ticker: str):
            raise price_error

        outcome = perform_search(
            "AAPL",
            price_loader=fail_price,
            social_loader=lambda ticker: social_buzz,
        )

        self.assertIsNone(outcome.price_result)
        self.assertIs(outcome.price_error, price_error)
        self.assertIs(outcome.social_buzz, social_buzz)
        self.assertIsNone(outcome.social_error)

    def test_perform_search_rejects_blank_before_calling_either_source(self) -> None:
        calls: list[str] = []

        with self.assertRaises(BlankTickerError):
            perform_search(
                "   ",
                price_loader=lambda ticker: calls.append("price"),
                social_loader=lambda ticker: calls.append("social"),
            )

        self.assertEqual(calls, [])

    def test_formats_social_buzz_values_and_hides_error_details(self) -> None:
        self.assertEqual(format_mention_change(12.8113879), "+12.8%")
        self.assertEqual(format_mention_change(-50.0), "-50.0%")
        self.assertEqual(format_mention_change(0.0), "+0.0%")
        self.assertEqual(format_mention_change(None), "N/A")

        errors = (
            ApeWisdomRequestError("sensitive-token-value"),
            ApeWisdomResponseError("sensitive-token-value"),
            RuntimeError("sensitive-token-value"),
        )
        for error in errors:
            with self.subTest(error_type=type(error).__name__):
                message = social_buzz_error_message(error)
                self.assertEqual(
                    message,
                    "Social Buzz is temporarily unavailable. Please try again later.",
                )
                self.assertNotIn("sensitive-token-value", message)

    def test_blank_ticker_is_rejected_before_configuration_is_loaded(self) -> None:
        configuration_loads = 0

        def load_configuration():
            nonlocal configuration_loads
            configuration_loads += 1
            raise AssertionError("configuration must not load for a blank ticker")

        with self.assertRaises(BlankTickerError):
            lookup_ticker("   ", configuration_loader=load_configuration)

        self.assertEqual(configuration_loads, 0)

    def test_lookup_ticker_builds_provider_and_returns_research_result(self) -> None:
        expected_configuration = object()
        bar = make_bar(date(2026, 8, 25), 102.0)

        class Provider:
            def get_price_history(self, symbol, start, end):
                self.request = (symbol, start, end)
                return [bar]

        provider = Provider()

        def build_provider(configuration):
            self.assertIs(configuration, expected_configuration)
            return provider

        result = lookup_ticker(
            " aapl ",
            configuration_loader=lambda: expected_configuration,
            provider_builder=build_provider,
        )

        self.assertEqual(result.ticker, "AAPL")
        self.assertEqual(provider.request[0], "AAPL")

    def test_maps_expected_errors_to_safe_user_guidance(self) -> None:
        cases = (
            (BlankTickerError("internal"), "Enter a ticker symbol."),
            (
                NoMarketDataError("internal"),
                "No market data found. Check the ticker and try again.",
            ),
            (
                TiingoSymbolNotFoundError("internal"),
                "No market data found. Check the ticker and try again.",
            ),
            (
                TiingoAuthenticationError("internal"),
                "Tiingo authentication failed. Check MARKET_DATA_API_KEY in your local .env file.",
            ),
            (
                TiingoRateLimitError("internal"),
                "Tiingo's request limit was reached. Please try again later.",
            ),
            (
                TiingoRequestError("internal"),
                "Market data is temporarily unavailable. Check your network and try again.",
            ),
        )

        for error, expected in cases:
            with self.subTest(error_type=type(error).__name__):
                self.assertEqual(error_message_for(error), expected)

    def test_configuration_and_unexpected_error_details_are_hidden(self) -> None:
        configuration_message = error_message_for(
            ConfigurationError("sensitive-token-value must stay hidden")
        )
        self.assertEqual(
            configuration_message,
            "Market data setup is incomplete. Check MARKET_DATA_PROVIDER and "
            "MARKET_DATA_API_KEY in your local .env file.",
        )
        self.assertNotIn("sensitive-token-value", configuration_message)

        unexpected_message = error_message_for(
            RuntimeError("sensitive-token-value must stay hidden")
        )
        self.assertEqual(
            unexpected_message,
            "Something went wrong while loading market data. Please try again.",
        )
        self.assertNotIn("sensitive-token-value", unexpected_message)

    def test_chart_uses_adjusted_close_and_table_is_most_recent_first(self) -> None:
        bars = (
            make_bar(date(2026, 8, 23), 100.0),
            make_bar(date(2026, 8, 24), 101.0),
            make_bar(date(2026, 8, 25), 102.0),
        )
        result = StockResearchResult(
            ticker="AAPL",
            start_date=date(2025, 8, 25),
            end_date=date(2026, 8, 25),
            history=bars,
            latest_bar=bars[-1],
            daily_change_percent=(102.0 / 101.0 - 1.0) * 100.0,
        )

        self.assertEqual(
            chart_rows(result),
            [
                {"Trading date": date(2026, 8, 23), "Adjusted close": 99.75},
                {"Trading date": date(2026, 8, 24), "Adjusted close": 100.75},
                {"Trading date": date(2026, 8, 25), "Adjusted close": 101.75},
            ],
        )
        self.assertEqual(
            [row["Trading date"] for row in recent_price_rows(result, limit=2)],
            [date(2026, 8, 25), date(2026, 8, 24)],
        )
        self.assertEqual(recent_price_rows(result, limit=2)[0]["Volume"], 102_000)


class SocialBuzzRenderingTests(unittest.TestCase):
    def test_renders_found_social_buzz_metrics_and_source(self) -> None:
        app = AppTest.from_string(
            """
from private_quant.app.stock_research import render_social_buzz
from private_quant.social.apewisdom import SocialBuzz

render_social_buzz(
    "NVDA",
    SocialBuzz("NVDA", 1, 317, 281, 12.8113879, 4074, "Rising"),
)
"""
        ).run(timeout=20)

        self.assertEqual(app.header[0].value, "Social Buzz")
        self.assertEqual(app.subheader[0].value, "NVDA Social Buzz")
        self.assertEqual(
            [(metric.label, metric.value) for metric in app.metric],
            [
                ("Reddit rank", "#1"),
                ("24h mentions", "317"),
                ("Previous 24h", "281"),
                ("Mention change", "+12.8%"),
                ("Upvotes", "4,074"),
                ("Buzz trend", "Rising"),
            ],
        )
        self.assertEqual(
            app.caption[0].value,
            "Source: ApeWisdom — Reddit stock communities",
        )
        self.assertEqual(len(app.warning), 0)
        self.assertEqual(len(app.exception), 0)

    def test_renders_not_discussed_state_and_source(self) -> None:
        app = AppTest.from_string(
            """
from private_quant.app.stock_research import render_social_buzz
render_social_buzz("QQQ", None)
"""
        ).run(timeout=20)

        self.assertEqual(app.header[0].value, "Social Buzz")
        self.assertIn("QQQ", app.info[0].value)
        self.assertIn("not currently discussed", app.info[0].value)
        self.assertEqual(
            app.caption[0].value,
            "Source: ApeWisdom — Reddit stock communities",
        )
        self.assertEqual(len(app.exception), 0)

    def test_renders_safe_provider_error_and_source(self) -> None:
        app = AppTest.from_string(
            """
from private_quant.app.stock_research import render_social_buzz
from private_quant.social.apewisdom import ApeWisdomRequestError
render_social_buzz("AAPL", None, ApeWisdomRequestError("sensitive-token-value"))
"""
        ).run(timeout=20)

        self.assertEqual(app.header[0].value, "Social Buzz")
        self.assertEqual(
            app.warning[0].value,
            "Social Buzz is temporarily unavailable. Please try again later.",
        )
        self.assertNotIn("sensitive-token-value", app.warning[0].value)
        self.assertEqual(
            app.caption[0].value,
            "Source: ApeWisdom — Reddit stock communities",
        )
        self.assertEqual(len(app.exception), 0)


if __name__ == "__main__":
    unittest.main()
