"""Local Streamlit page for end-of-day stock research."""

from collections.abc import Callable

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
            result = lookup_ticker(ticker)
        except Exception as error:
            st.error(error_message_for(error))
        else:
            render_result(result)

    st.header("Fundamentals")
    st.info("SEC fundamentals integration coming next")


if __name__ == "__main__":
    main()
