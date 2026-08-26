"""Framework-agnostic adapter for ApeWisdom's public stock-discussion API."""

from collections.abc import Callable
from dataclasses import dataclass
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_BASE_URL = "https://apewisdom.io/api/v1.0/filter/all-stocks"
_DEFAULT_MAX_PAGES = 10

PageGetter = Callable[[int], object]


class ApeWisdomError(RuntimeError):
    """Base error for ApeWisdom provider failures."""


class ApeWisdomRequestError(ApeWisdomError):
    """Raised when the public ApeWisdom endpoint cannot be read."""


class ApeWisdomResponseError(ApeWisdomError):
    """Raised when ApeWisdom returns an unexpected payload."""


@dataclass(frozen=True, slots=True)
class SocialBuzz:
    """Current Reddit stock-discussion activity reported by ApeWisdom."""

    ticker: str
    reddit_rank: int
    mentions: int
    previous_mentions: int
    mention_change_percent: float | None
    upvotes: int
    trend: str


def fetch_apewisdom_page(page: int) -> object:
    """Fetch and decode one page from ApeWisdom's public JSON API."""

    if page < 1:
        raise ValueError("page must be at least 1")

    url = _BASE_URL if page == 1 else f"{_BASE_URL}/page/{page}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "PrivateQuantLab/0.1",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=15.0) as response:
            raw = response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise ApeWisdomRequestError("ApeWisdom request failed") from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApeWisdomRequestError("ApeWisdom request failed") from exc


class ApeWisdomProvider:
    """Find one ticker in ApeWisdom's bounded paginated results."""

    def __init__(
        self,
        *,
        get_page: PageGetter = fetch_apewisdom_page,
        max_pages: int = _DEFAULT_MAX_PAGES,
    ) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        self._get_page = get_page
        self._max_pages = min(max_pages, _DEFAULT_MAX_PAGES)

    def find_ticker(self, ticker: str) -> SocialBuzz | None:
        """Return current discussion activity, or None when not discussed."""

        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker:
            raise ValueError("ticker must not be empty")

        first_payload = self._get_page(1)
        reported_pages, rows = self._parse_page(first_payload)
        match = self._find_match(normalized_ticker, rows)
        if match is not None:
            return self._to_social_buzz(normalized_ticker, match)

        last_page = min(reported_pages, self._max_pages)
        for page_number in range(2, last_page + 1):
            _, rows = self._parse_page(self._get_page(page_number))
            match = self._find_match(normalized_ticker, rows)
            if match is not None:
                return self._to_social_buzz(normalized_ticker, match)
        return None

    @staticmethod
    def _parse_page(payload: object) -> tuple[int, list[object]]:
        if not isinstance(payload, dict):
            raise ApeWisdomResponseError("ApeWisdom page must be an object")

        pages = payload.get("pages")
        current_page = payload.get("current_page")
        rows = payload.get("results")
        if type(pages) is not int or pages < 1:
            raise ApeWisdomResponseError("ApeWisdom pages must be positive")
        if type(current_page) is not int or current_page < 1:
            raise ApeWisdomResponseError(
                "ApeWisdom current_page must be positive"
            )
        if not isinstance(rows, list):
            raise ApeWisdomResponseError("ApeWisdom results must be a list")
        return pages, rows

    @staticmethod
    def _find_match(ticker: str, rows: list[object]) -> dict[str, Any] | None:
        for row in rows:
            if not isinstance(row, dict):
                raise ApeWisdomResponseError("ApeWisdom result must be an object")
            row_ticker = row.get("ticker")
            if not isinstance(row_ticker, str) or not row_ticker.strip():
                raise ApeWisdomResponseError(
                    "ApeWisdom result ticker must be text"
                )
            if row_ticker.strip().upper() == ticker:
                return row
        return None

    @classmethod
    def _to_social_buzz(
        cls, ticker: str, row: dict[str, Any]
    ) -> SocialBuzz:
        reddit_rank = cls._required_int(row, "rank", minimum=1)
        mentions = cls._required_int(row, "mentions", minimum=0)
        previous_mentions = cls._required_int(
            row, "mentions_24h_ago", minimum=0
        )
        upvotes = cls._required_int(row, "upvotes", minimum=0)

        mention_change_percent = None
        if previous_mentions > 0:
            mention_change_percent = (
                (mentions - previous_mentions) / previous_mentions * 100.0
            )

        if mentions > previous_mentions:
            trend = "Rising"
        elif mentions < previous_mentions:
            trend = "Falling"
        else:
            trend = "Flat"

        return SocialBuzz(
            ticker=ticker,
            reddit_rank=reddit_rank,
            mentions=mentions,
            previous_mentions=previous_mentions,
            mention_change_percent=mention_change_percent,
            upvotes=upvotes,
            trend=trend,
        )

    @staticmethod
    def _required_int(
        row: dict[str, Any], field: str, *, minimum: int
    ) -> int:
        value = row.get(field)
        if type(value) is not int or value < minimum:
            raise ApeWisdomResponseError(
                f"ApeWisdom {field} must be an integer of at least {minimum}"
            )
        return value
