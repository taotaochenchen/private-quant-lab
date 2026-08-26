import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.social.apewisdom import (
    ApeWisdomProvider,
    ApeWisdomRequestError,
    ApeWisdomResponseError,
    fetch_apewisdom_page,
)


def buzz_row(
    ticker: str = "NVDA",
    *,
    rank: int = 1,
    mentions: int = 317,
    previous_mentions: int = 281,
    upvotes: int = 4_074,
) -> dict[str, object]:
    return {
        "rank": rank,
        "ticker": ticker,
        "name": ticker,
        "mentions": mentions,
        "mentions_24h_ago": previous_mentions,
        "upvotes": upvotes,
        "rank_24h_ago": rank,
    }


def page(
    page_number: int,
    *,
    pages: int = 1,
    results: list[object] | None = None,
) -> dict[str, object]:
    return {
        "count": len(results or []),
        "pages": pages,
        "current_page": page_number,
        "results": results or [],
    }


class ApeWisdomProviderTests(unittest.TestCase):
    def test_normalizes_ticker_and_maps_first_page_rising_buzz(self) -> None:
        calls: list[int] = []

        def get_page(page_number: int) -> object:
            calls.append(page_number)
            return page(1, results=[buzz_row()])

        result = ApeWisdomProvider(get_page=get_page).find_ticker("  nvda  ")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.ticker, "NVDA")
        self.assertEqual(result.reddit_rank, 1)
        self.assertEqual(result.mentions, 317)
        self.assertEqual(result.previous_mentions, 281)
        self.assertAlmostEqual(result.mention_change_percent, 12.8113879)
        self.assertEqual(result.upvotes, 4_074)
        self.assertEqual(result.trend, "Rising")
        self.assertEqual(calls, [1])

    def test_follows_pages_until_match_then_stops_early(self) -> None:
        calls: list[int] = []
        responses = {
            1: page(1, pages=5, results=[buzz_row("MSFT")]),
            2: page(2, pages=5, results=[buzz_row("AAPL", rank=101)]),
        }

        def get_page(page_number: int) -> object:
            calls.append(page_number)
            return responses[page_number]

        result = ApeWisdomProvider(get_page=get_page).find_ticker("AAPL")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.reddit_rank, 101)
        self.assertEqual(calls, [1, 2])

    def test_stops_at_api_reported_page_count_when_ticker_is_missing(self) -> None:
        calls: list[int] = []

        def get_page(page_number: int) -> object:
            calls.append(page_number)
            return page(page_number, pages=2, results=[buzz_row("MSFT")])

        result = ApeWisdomProvider(get_page=get_page).find_ticker("AAPL")

        self.assertIsNone(result)
        self.assertEqual(calls, [1, 2])

    def test_caps_missing_ticker_search_at_ten_pages(self) -> None:
        calls: list[int] = []

        def get_page(page_number: int) -> object:
            calls.append(page_number)
            return page(page_number, pages=99, results=[buzz_row("MSFT")])

        result = ApeWisdomProvider(get_page=get_page).find_ticker("AAPL")

        self.assertIsNone(result)
        self.assertEqual(calls, list(range(1, 11)))

    def test_calculates_falling_flat_and_zero_previous_rules(self) -> None:
        cases = (
            (50, 100, "Falling", -50.0),
            (100, 100, "Flat", 0.0),
            (25, 0, "Rising", None),
            (0, 0, "Flat", None),
        )

        for mentions, previous, expected_trend, expected_change in cases:
            with self.subTest(
                mentions=mentions,
                previous=previous,
                expected_trend=expected_trend,
            ):
                provider = ApeWisdomProvider(
                    get_page=lambda page_number: page(
                        1,
                        results=[
                            buzz_row(
                                mentions=mentions,
                                previous_mentions=previous,
                            )
                        ],
                    )
                )
                result = provider.find_ticker("NVDA")
                assert result is not None
                self.assertEqual(result.trend, expected_trend)
                if expected_change is None:
                    self.assertIsNone(result.mention_change_percent)
                else:
                    self.assertAlmostEqual(
                        result.mention_change_percent, expected_change
                    )

    def test_rejects_blank_ticker_before_loading_page(self) -> None:
        calls: list[int] = []

        with self.assertRaisesRegex(ValueError, "ticker must not be empty"):
            ApeWisdomProvider(
                get_page=lambda page_number: calls.append(page_number)
            ).find_ticker("   ")

        self.assertEqual(calls, [])

    def test_rejects_invalid_page_payloads(self) -> None:
        payloads = (
            [],
            {"pages": 1, "current_page": 1},
            {"pages": 0, "current_page": 1, "results": []},
            {"pages": 1, "current_page": 1, "results": "not-a-list"},
        )

        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ApeWisdomResponseError):
                    ApeWisdomProvider(
                        get_page=lambda page_number, value=payload: value
                    ).find_ticker("NVDA")

    def test_rejects_invalid_matching_row(self) -> None:
        rows = (
            {"ticker": "NVDA"},
            buzz_row(rank=0),
            buzz_row(mentions=-1),
            buzz_row(previous_mentions=-1),
            buzz_row(upvotes=-1),
        )

        for row in rows:
            with self.subTest(row=row):
                with self.assertRaises(ApeWisdomResponseError):
                    ApeWisdomProvider(
                        get_page=lambda page_number, value=row: page(
                            1, results=[value]
                        )
                    ).find_ticker("NVDA")


class ApeWisdomTransportTests(unittest.TestCase):
    class FakeResponse:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return self.payload

    def test_fetches_base_and_paginated_json_endpoints(self) -> None:
        captured: list[tuple[object, float]] = []
        payload = page(1, results=[buzz_row()])

        def fake_urlopen(request, timeout):
            captured.append((request, timeout))
            return self.FakeResponse(json.dumps(payload).encode("utf-8"))

        with patch("private_quant.social.apewisdom.urlopen", fake_urlopen):
            first = fetch_apewisdom_page(1)
            second = fetch_apewisdom_page(2)

        self.assertEqual(first, payload)
        self.assertEqual(second, payload)
        self.assertEqual(
            captured[0][0].full_url,
            "https://apewisdom.io/api/v1.0/filter/all-stocks",
        )
        self.assertEqual(
            captured[1][0].full_url,
            "https://apewisdom.io/api/v1.0/filter/all-stocks/page/2",
        )
        self.assertEqual(captured[0][0].get_header("Accept"), "application/json")
        self.assertEqual([timeout for _, timeout in captured], [15.0, 15.0])

    def test_rejects_page_numbers_below_one_without_network_call(self) -> None:
        with patch("private_quant.social.apewisdom.urlopen") as mocked_urlopen:
            with self.assertRaisesRegex(ValueError, "page must be at least 1"):
                fetch_apewisdom_page(0)
        mocked_urlopen.assert_not_called()

    def test_maps_transport_and_invalid_json_errors(self) -> None:
        failures = (
            HTTPError("https://example", 500, "Server Error", None, None),
            URLError("offline"),
            TimeoutError("timed out"),
        )

        for failure in failures:
            with self.subTest(failure_type=type(failure).__name__):
                with patch(
                    "private_quant.social.apewisdom.urlopen", side_effect=failure
                ):
                    with self.assertRaisesRegex(
                        ApeWisdomRequestError, "ApeWisdom request failed"
                    ):
                        fetch_apewisdom_page(1)

        with patch(
            "private_quant.social.apewisdom.urlopen",
            return_value=self.FakeResponse(b"not-json"),
        ):
            with self.assertRaisesRegex(
                ApeWisdomRequestError, "ApeWisdom request failed"
            ):
                fetch_apewisdom_page(1)


if __name__ == "__main__":
    unittest.main()
