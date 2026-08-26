from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.data.models import PriceBar
from private_quant.data.tiingo import (
    TiingoAuthenticationError,
    TiingoRateLimitError,
    TiingoRequestError,
)
from private_quant.research.stock_lookup import (
    BlankTickerError,
    NoMarketDataError,
    StockLookupService,
    normalize_ticker,
)


def make_bar(trading_date: date, close: float, *, symbol: str = "AAPL") -> PriceBar:
    return PriceBar(
        symbol=symbol,
        trading_date=trading_date,
        open=close - 1.0,
        high=close + 1.0,
        low=close - 2.0,
        close=close,
        adjusted_close=close - 0.5,
        volume=1_000,
    )


class RecordingProvider:
    def __init__(self, bars=(), error: Exception | None = None) -> None:
        self.bars = bars
        self.error = error
        self.calls: list[tuple[str, date, date]] = []

    def get_price_history(self, symbol: str, start: date, end: date):
        self.calls.append((symbol, start, end))
        if self.error is not None:
            raise self.error
        return self.bars


class StockLookupServiceTests(unittest.TestCase):
    def test_normalizes_ticker_whitespace_and_case(self) -> None:
        self.assertEqual(normalize_ticker("  aapl  "), "AAPL")

    def test_rejects_blank_ticker_without_calling_provider(self) -> None:
        provider = RecordingProvider()

        with self.assertRaises(BlankTickerError):
            StockLookupService(provider).lookup("   ", as_of=date(2026, 8, 26))

        self.assertEqual(provider.calls, [])

    def test_requests_the_365_day_window_ending_on_as_of_date(self) -> None:
        provider = RecordingProvider([make_bar(date(2026, 8, 26), 100.0)])

        result = StockLookupService(provider).lookup(
            " msft ", as_of=date(2026, 8, 26)
        )

        self.assertEqual(
            provider.calls,
            [("MSFT", date(2025, 8, 26), date(2026, 8, 26))],
        )
        self.assertEqual(result.ticker, "MSFT")
        self.assertEqual(result.start_date, date(2025, 8, 26))
        self.assertEqual(result.end_date, date(2026, 8, 26))

    def test_sorts_history_selects_latest_bar_and_calculates_daily_change(self) -> None:
        older = make_bar(date(2026, 8, 24), 100.0)
        latest = make_bar(date(2026, 8, 25), 102.0)
        provider = RecordingProvider([latest, older])

        result = StockLookupService(provider).lookup(
            "AAPL", as_of=date(2026, 8, 26)
        )

        self.assertEqual(result.history, (older, latest))
        self.assertIs(result.latest_bar, latest)
        self.assertAlmostEqual(result.daily_change_percent, 2.0)

    def test_daily_change_is_unavailable_with_only_one_bar(self) -> None:
        provider = RecordingProvider([make_bar(date(2026, 8, 25), 102.0)])

        result = StockLookupService(provider).lookup(
            "AAPL", as_of=date(2026, 8, 26)
        )

        self.assertIsNone(result.daily_change_percent)

    def test_raises_no_market_data_for_empty_history(self) -> None:
        provider = RecordingProvider()

        with self.assertRaises(NoMarketDataError):
            StockLookupService(provider).lookup("UNKNOWN", as_of=date(2026, 8, 26))

    def test_preserves_provider_error_types(self) -> None:
        errors = (
            TiingoAuthenticationError("authentication failed"),
            TiingoRateLimitError("rate limited"),
            TiingoRequestError("network failed"),
        )

        for error in errors:
            with self.subTest(error_type=type(error).__name__):
                provider = RecordingProvider(error=error)
                with self.assertRaises(type(error)) as raised:
                    StockLookupService(provider).lookup(
                        "AAPL", as_of=date(2026, 8, 26)
                    )
                self.assertIs(raised.exception, error)


if __name__ == "__main__":
    unittest.main()
