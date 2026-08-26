from datetime import date
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.data.tiingo import (
    TiingoAuthenticationError,
    TiingoMarketDataProvider,
    TiingoRateLimitError,
    TiingoSymbolNotFoundError,
)


class TiingoMarketDataProviderTests(unittest.TestCase):
    def test_maps_history_to_price_bars_and_sorts_oldest_first(self) -> None:
        calls: list[tuple[str, dict[str, str]]] = []

        def fake_get_json(url: str, headers: dict[str, str]) -> object:
            calls.append((url, headers))
            return [
                {
                    "date": "2026-08-25T00:00:00.000Z",
                    "open": 101.0,
                    "high": 103.0,
                    "low": 100.0,
                    "close": 102.0,
                    "adjClose": 101.5,
                    "volume": 1200,
                },
                {
                    "date": "2026-08-24T00:00:00.000Z",
                    "open": 99.0,
                    "high": 102.0,
                    "low": 98.0,
                    "close": 101.0,
                    "adjClose": 100.5,
                    "volume": 1000,
                },
            ]

        provider = TiingoMarketDataProvider("secret-key", get_json=fake_get_json)
        bars = provider.get_price_history(
            "QQQ", date(2026, 8, 24), date(2026, 8, 25)
        )

        self.assertEqual(
            [bar.trading_date for bar in bars],
            [date(2026, 8, 24), date(2026, 8, 25)],
        )
        self.assertEqual(bars[0].symbol, "QQQ")
        self.assertEqual(bars[0].adjusted_close, 100.5)
        self.assertEqual(bars[0].volume, 1000)
        self.assertEqual(len(calls), 1)
        self.assertIn("/tiingo/daily/QQQ/prices", calls[0][0])
        self.assertIn("startDate=2026-08-24", calls[0][0])
        self.assertIn("endDate=2026-08-25", calls[0][0])
        self.assertEqual(calls[0][1]["Authorization"], "Token secret-key")

    def test_rejects_invalid_request_before_calling_api(self) -> None:
        called = False

        def fake_get_json(url: str, headers: dict[str, str]) -> object:
            nonlocal called
            called = True
            return []

        provider = TiingoMarketDataProvider("secret-key", get_json=fake_get_json)

        with self.assertRaisesRegex(ValueError, "symbol must not be empty"):
            provider.get_price_history("   ", date(2026, 8, 24), date(2026, 8, 25))
        with self.assertRaisesRegex(ValueError, "start date cannot be after end date"):
            provider.get_price_history("QQQ", date(2026, 8, 25), date(2026, 8, 24))

        self.assertFalse(called)

    def test_requires_nonempty_api_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "Tiingo API key must not be empty"):
            TiingoMarketDataProvider("   ")

    def test_default_transport_fetches_json(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return (
                    b'[{"date":"2026-08-25T00:00:00.000Z",'
                    b'"open":1,"high":2,"low":1,"close":2,'
                    b'"adjClose":2,"volume":10}]'
                )

        captured = []

        def fake_urlopen(request, timeout):
            captured.append((request, timeout))
            return FakeResponse()

        with patch("private_quant.data.tiingo.urlopen", fake_urlopen):
            provider = TiingoMarketDataProvider("secret-key")
            bars = provider.get_price_history(
                "QQQ", date(2026, 8, 25), date(2026, 8, 25)
            )

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].close, 2.0)
        self.assertEqual(captured[0][0].get_header("Authorization"), "Token secret-key")
        self.assertEqual(captured[0][1], 30.0)

    def test_default_transport_maps_auth_and_rate_limit_errors(self) -> None:
        provider = TiingoMarketDataProvider("secret-key")

        with patch(
            "private_quant.data.tiingo.urlopen",
            side_effect=HTTPError(
                "https://example", 401, "Unauthorized", hdrs=None, fp=None
            ),
        ):
            with self.assertRaises(TiingoAuthenticationError):
                provider.get_price_history(
                    "QQQ", date(2026, 8, 25), date(2026, 8, 25)
                )

        with patch(
            "private_quant.data.tiingo.urlopen",
            side_effect=HTTPError(
                "https://example", 429, "Too Many Requests", hdrs=None, fp=None
            ),
        ):
            with self.assertRaises(TiingoRateLimitError):
                provider.get_price_history(
                    "QQQ", date(2026, 8, 25), date(2026, 8, 25)
                )

    def test_default_transport_maps_unknown_symbol_error(self) -> None:
        provider = TiingoMarketDataProvider("secret-key")

        with patch(
            "private_quant.data.tiingo.urlopen",
            side_effect=HTTPError(
                "https://example", 404, "Not Found", hdrs=None, fp=None
            ),
        ):
            with self.assertRaises(TiingoSymbolNotFoundError):
                provider.get_price_history(
                    "UNKNOWN", date(2026, 8, 25), date(2026, 8, 25)
                )


if __name__ == "__main__":
    unittest.main()
