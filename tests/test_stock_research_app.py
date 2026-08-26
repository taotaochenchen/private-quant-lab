from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.app.config import ConfigurationError
from private_quant.app.stock_research import (
    chart_rows,
    error_message_for,
    lookup_ticker,
    recent_price_rows,
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


class StockResearchAppTests(unittest.TestCase):
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

    def test_configuration_guidance_is_preserved_but_unexpected_details_are_hidden(self) -> None:
        configuration_error = ConfigurationError(
            "MARKET_DATA_API_KEY is missing. Add it to the local .env file."
        )

        self.assertEqual(error_message_for(configuration_error), str(configuration_error))
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


if __name__ == "__main__":
    unittest.main()
