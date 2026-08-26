"""Provider-independent stock price lookup service."""

from dataclasses import dataclass
from datetime import date, timedelta

from private_quant.data.base import MarketDataProvider
from private_quant.data.models import PriceBar


class BlankTickerError(ValueError):
    """Raised when a lookup does not contain a ticker symbol."""


class NoMarketDataError(LookupError):
    """Raised when the configured provider returns no EOD history."""


@dataclass(frozen=True, slots=True)
class StockResearchResult:
    """UI-friendly, immutable result of one stock-history lookup."""

    ticker: str
    start_date: date
    end_date: date
    history: tuple[PriceBar, ...]
    latest_bar: PriceBar
    daily_change_percent: float | None


def normalize_ticker(ticker: str) -> str:
    """Trim and uppercase a ticker, rejecting a blank value."""

    normalized = ticker.strip().upper()
    if not normalized:
        raise BlankTickerError("Enter a ticker symbol.")
    return normalized


class StockLookupService:
    """Load and summarize about one year of daily EOD price history."""

    def __init__(self, provider: MarketDataProvider) -> None:
        self._provider = provider

    def lookup(
        self, ticker: str, *, as_of: date | None = None
    ) -> StockResearchResult:
        normalized_ticker = normalize_ticker(ticker)
        end_date = as_of or date.today()
        start_date = end_date - timedelta(days=365)
        history = tuple(
            sorted(
                self._provider.get_price_history(
                    normalized_ticker, start_date, end_date
                ),
                key=lambda bar: bar.trading_date,
            )
        )
        if not history:
            raise NoMarketDataError(
                f"No market data found for {normalized_ticker}."
            )

        latest_bar = history[-1]
        daily_change_percent = None
        if len(history) >= 2:
            previous_close = history[-2].close
            daily_change_percent = (
                (latest_bar.close - previous_close) / previous_close * 100.0
            )

        return StockResearchResult(
            ticker=normalized_ticker,
            start_date=start_date,
            end_date=end_date,
            history=history,
            latest_bar=latest_bar,
            daily_change_percent=daily_change_percent,
        )
