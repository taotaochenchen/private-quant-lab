"""Local Streamlit page for end-of-day stock research."""

from collections.abc import Callable
from dataclasses import dataclass

import streamlit as st

from private_quant.app.config import (
    AppConfiguration,
    ConfigurationError,
    build_market_data_provider,
    load_app_configuration,
)
from private_quant.data.base import MarketDataProvider
from private_quant.data.tiingo import (
    TiingoAuthenticationError,
    TiingoRateLimitError,
    TiingoRequestError,
    TiingoSymbolNotFoundError,
)
from private_quant.research.stock_lookup import (
    BlankTickerError,
    NoMarketDataError,
    StockLookupService,
    StockResearchResult,
    normalize_ticker,
)
from private_quant.social.apewisdom import (
    ApeWisdomProvider,
    SocialBuzz,
    fetch_apewisdom_page,
)


@st.cache_data(ttl="5m", max_entries=10, show_spinner=False)
def load_apewisdom_page(page: int) -> object:
    """Load one public ApeWisdom page through Streamlit's short-lived cache."""

    return fetch_apewisdom_page(page)


def error_message_for(error: Exception) -> str:
    """Return safe, actionable guidance without reflecting provider details."""

    if isinstance(error, BlankTickerError):
        return "Enter a ticker symbol."
    if isinstance(error, (NoMarketDataError, TiingoSymbolNotFoundError)):
        return "No market data found. Check the ticker and try again."
    if isinstance(error, ConfigurationError):
        return (
            "Market data setup is incomplete. Check MARKET_DATA_PROVIDER and "
            "MARKET_DATA_API_KEY in your local .env file."
        )
    if isinstance(error, TiingoAuthenticationError):
        return (
            "Tiingo authentication failed. Check MARKET_DATA_API_KEY in your "
            "local .env file."
        )
    if isinstance(error, TiingoRateLimitError):
        return "Tiingo's request limit was reached. Please try again later."
    if isinstance(error, TiingoRequestError):
        return (
            "Market data is temporarily unavailable. Check your network and "
            "try again."
        )
    return "Something went wrong while loading market data. Please try again."


def lookup_ticker(
    ticker: str,
    *,
    configuration_loader: Callable[[], AppConfiguration] = load_app_configuration,
    provider_builder: Callable[
        [AppConfiguration], MarketDataProvider
    ] = build_market_data_provider,
) -> StockResearchResult:
    """Validate input, construct the local provider, and perform one lookup."""

    normalized_ticker = normalize_ticker(ticker)
    configuration = configuration_loader()
    provider = provider_builder(configuration)
    return StockLookupService(provider).lookup(normalized_ticker)


def lookup_social_buzz(
    ticker: str,
    *,
    page_loader: Callable[[int], object] = load_apewisdom_page,
) -> SocialBuzz | None:
    """Find public ApeWisdom discussion activity for one ticker."""

    return ApeWisdomProvider(get_page=page_loader).find_ticker(ticker)


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """Independent price and Social Buzz outcomes for one normalized ticker."""

    ticker: str
    price_result: StockResearchResult | None
    price_error: Exception | None
    social_buzz: SocialBuzz | None
    social_error: Exception | None


def perform_search(
    ticker: str,
    *,
    price_loader: Callable[[str], StockResearchResult] = lookup_ticker,
    social_loader: Callable[[str], SocialBuzz | None] = lookup_social_buzz,
) -> SearchOutcome:
    """Run price and social lookups without letting either suppress the other."""

    normalized_ticker = normalize_ticker(ticker)

    price_result = None
    price_error = None
    try:
        price_result = price_loader(normalized_ticker)
    except Exception as error:
        price_error = error

    social_buzz = None
    social_error = None
    try:
        social_buzz = social_loader(normalized_ticker)
    except Exception as error:
        social_error = error

    return SearchOutcome(
        ticker=normalized_ticker,
        price_result=price_result,
        price_error=price_error,
        social_buzz=social_buzz,
        social_error=social_error,
    )


def chart_rows(result: StockResearchResult) -> list[dict[str, object]]:
    """Build Streamlit-compatible adjusted-close chart data."""

    return [
        {
            "Trading date": bar.trading_date,
            "Adjusted close": bar.adjusted_close,
        }
        for bar in result.history
    ]


def recent_price_rows(
    result: StockResearchResult, *, limit: int = 20
) -> list[dict[str, object]]:
    """Build the most recent daily rows in reverse chronological order."""

    return [
        {
            "Trading date": bar.trading_date,
            "Open": bar.open,
            "High": bar.high,
            "Low": bar.low,
            "Close": bar.close,
            "Adjusted close": bar.adjusted_close,
            "Volume": bar.volume,
        }
        for bar in reversed(result.history[-limit:])
    ]


def format_mention_change(change_percent: float | None) -> str:
    """Format mention change without inventing a zero-denominator percentage."""

    if change_percent is None:
        return "N/A"
    return f"{change_percent:+.1f}%"


def social_buzz_error_message(error: Exception) -> str:
    """Return fixed public copy without reflecting provider exception details."""

    return "Social Buzz is temporarily unavailable. Please try again later."


def render_result(result: StockResearchResult) -> None:
    """Render one successful stock lookup."""

    latest = result.latest_bar
    st.subheader(result.ticker)
    st.caption("Latest available end-of-day data; this is not a live quote.")

    date_card, close_card, adjusted_card, volume_card, change_card = st.columns(5)
    date_card.metric("Latest trading date", latest.trading_date.isoformat())
    close_card.metric("Latest close", f"${latest.close:,.2f}")
    adjusted_card.metric("Adjusted close", f"${latest.adjusted_close:,.2f}")
    volume_card.metric("Volume", f"{latest.volume:,}")
    change_card.metric(
        "Daily change",
        (
            f"{result.daily_change_percent:+.2f}%"
            if result.daily_change_percent is not None
            else "N/A"
        ),
    )

    open_card, high_card, low_card = st.columns(3)
    open_card.metric("Open", f"${latest.open:,.2f}")
    high_card.metric("High", f"${latest.high:,.2f}")
    low_card.metric("Low", f"${latest.low:,.2f}")

    st.subheader("Adjusted-close history")
    st.line_chart(
        chart_rows(result),
        x="Trading date",
        y="Adjusted close",
        x_label="Trading date",
        y_label="Adjusted close (USD)",
    )

    st.subheader("Recent daily prices")
    st.dataframe(
        recent_price_rows(result),
        hide_index=True,
        column_config={
            "Open": st.column_config.NumberColumn(format="dollar"),
            "High": st.column_config.NumberColumn(format="dollar"),
            "Low": st.column_config.NumberColumn(format="dollar"),
            "Close": st.column_config.NumberColumn(format="dollar"),
            "Adjusted close": st.column_config.NumberColumn(format="dollar"),
            "Volume": st.column_config.NumberColumn(format="compact"),
        },
    )


def render_social_buzz(
    ticker: str,
    buzz: SocialBuzz | None,
    error: Exception | None = None,
) -> None:
    """Render found, missing, or unavailable Social Buzz states."""

    st.header("Social Buzz")
    if error is not None:
        st.warning(social_buzz_error_message(error))
    elif buzz is None:
        st.info(
            f"{ticker} is not currently discussed in ApeWisdom's tracked "
            "Reddit stock communities."
        )
    else:
        st.subheader(f"{ticker} Social Buzz")
        with st.container(horizontal=True):
            st.metric("Reddit rank", f"#{buzz.reddit_rank}", border=True)
            st.metric("24h mentions", f"{buzz.mentions:,}", border=True)
            st.metric(
                "Previous 24h", f"{buzz.previous_mentions:,}", border=True
            )
            st.metric(
                "Mention change",
                format_mention_change(buzz.mention_change_percent),
                border=True,
            )
            st.metric("Upvotes", f"{buzz.upvotes:,}", border=True)
            st.metric("Buzz trend", buzz.trend, border=True)

    st.caption("Source: ApeWisdom — Reddit stock communities")


def main() -> None:
    """Run the local stock research page."""

    st.set_page_config(
        page_title="Private Quant Lab — Stock Research",
        page_icon="📊",
        layout="wide",
    )
    st.title("Private Quant Lab — Stock Research")
    st.write("Look up approximately one year of daily market data.")

    with st.form("stock-search"):
        ticker = st.text_input(
            "Ticker",
            placeholder="AAPL, NVDA, MSFT, or QQQ",
        )
        search_clicked = st.form_submit_button("Search", type="primary")

    if search_clicked:
        try:
            outcome = perform_search(ticker)
        except Exception as error:
            st.error(error_message_for(error))
        else:
            if outcome.price_result is not None:
                render_result(outcome.price_result)
            elif outcome.price_error is not None:
                st.error(error_message_for(outcome.price_error))
            render_social_buzz(
                outcome.ticker,
                outcome.social_buzz,
                outcome.social_error,
            )

    st.header("Fundamentals")
    st.info("SEC fundamentals integration coming next")


if __name__ == "__main__":
    main()
