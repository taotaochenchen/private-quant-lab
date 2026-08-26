"""Tiingo end-of-day market data adapter."""

from collections.abc import Callable, Sequence
import json
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .base import MarketDataProvider
from .models import PriceBar

JsonGetter = Callable[[str, dict[str, str]], object]


class TiingoError(RuntimeError):
    """Base error for Tiingo provider failures."""


class TiingoAuthenticationError(TiingoError):
    """Raised when Tiingo rejects the API token."""


class TiingoRateLimitError(TiingoError):
    """Raised when Tiingo rate limits the request."""


class TiingoSymbolNotFoundError(TiingoError):
    """Raised when Tiingo does not recognize a requested symbol."""


class TiingoRequestError(TiingoError):
    """Raised for other transport or response failures."""


class TiingoMarketDataProvider(MarketDataProvider):
    """Map Tiingo EOD responses into the project's internal price model."""

    _BASE_URL = "https://api.tiingo.com/tiingo/daily"

    def __init__(self, api_key: str, *, get_json: JsonGetter | None = None) -> None:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise ValueError("Tiingo API key must not be empty")
        self._api_key = normalized_key
        self._get_json = get_json or self._http_get_json

    def get_price_history(self, symbol: str, start: date, end: date) -> Sequence[PriceBar]:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol must not be empty")
        if start > end:
            raise ValueError("start date cannot be after end date")

        query = urlencode({"startDate": start.isoformat(), "endDate": end.isoformat()})
        encoded_symbol = quote(normalized_symbol, safe=".-_")
        url = f"{self._BASE_URL}/{encoded_symbol}/prices?{query}"
        payload = self._get_json(
            url,
            {
                "Authorization": f"Token {self._api_key}",
                "Accept": "application/json",
            },
        )
        if not isinstance(payload, list):
            raise ValueError("Tiingo price response must be a list")

        bars = [self._to_price_bar(normalized_symbol, item) for item in payload]
        bars.sort(key=lambda bar: bar.trading_date)
        return bars

    @staticmethod
    def _to_price_bar(symbol: str, item: Any) -> PriceBar:
        if not isinstance(item, dict):
            raise ValueError("Tiingo price row must be an object")
        return PriceBar(
            symbol=symbol,
            trading_date=date.fromisoformat(str(item["date"])[:10]),
            open=float(item["open"]),
            high=float(item["high"]),
            low=float(item["low"]),
            close=float(item["close"]),
            adjusted_close=float(item["adjClose"]),
            volume=int(item["volume"]),
        )

    @staticmethod
    def _http_get_json(url: str, headers: dict[str, str]) -> object:
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=30.0) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise TiingoAuthenticationError("Tiingo authentication failed") from exc
            if exc.code == 429:
                raise TiingoRateLimitError("Tiingo rate limit exceeded") from exc
            if exc.code == 404:
                raise TiingoSymbolNotFoundError("Tiingo symbol was not found") from exc
            raise TiingoRequestError(f"Tiingo HTTP error: {exc.code}") from exc
        except URLError as exc:
            raise TiingoRequestError(f"Tiingo network error: {exc.reason}") from exc

        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TiingoRequestError("Tiingo returned invalid JSON") from exc
