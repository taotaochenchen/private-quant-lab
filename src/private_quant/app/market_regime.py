"""Standalone Streamlit page for deterministic, read-only market regimes."""

from collections.abc import Callable
from datetime import date, timedelta

import streamlit as st

from private_quant.app.config import (
    ConfigurationError,
    build_market_data_provider,
    load_app_configuration,
)
from private_quant.data import PriceBar
from private_quant.data.tiingo import (
    TiingoAuthenticationError,
    TiingoError,
    TiingoRateLimitError,
    TiingoRequestError,
    TiingoSymbolNotFoundError,
)
from private_quant.risk import (
    InsufficientRegimeHistoryError,
    InvalidRegimeDataError,
    MarketRegimeEngine,
    RegimeComponent,
    RegimeMetric,
    RegimeResult,
    StaleRegimeDataError,
)


@st.cache_data(ttl="15m", max_entries=8, show_spinner=False)
def load_regime_histories(
    as_of: date,
) -> tuple[tuple[PriceBar, ...], tuple[PriceBar, ...]]:
    """Load the bounded SPY history and optional QQQ confirmation history."""

    configuration = load_app_configuration()
    provider = build_market_data_provider(configuration)
    start = as_of - timedelta(days=550)
    spy = tuple(provider.get_price_history("SPY", start, as_of))
    try:
        qqq = tuple(provider.get_price_history("QQQ", start, as_of))
    except (TiingoError, ValueError):
        qqq = ()
    return spy, qqq


def evaluate_current_regime(
    as_of: date,
    *,
    history_loader: Callable[
        [date], tuple[tuple[PriceBar, ...], tuple[PriceBar, ...]]
    ] = load_regime_histories,
) -> RegimeResult:
    """Evaluate one requested date from app-loaded price histories."""

    spy_bars, qqq_bars = history_loader(as_of)
    return MarketRegimeEngine().evaluate(spy_bars, as_of=as_of, qqq_bars=qqq_bars)


def regime_error_message(error: Exception) -> str:
    """Return fixed user guidance without exposing provider or config details."""

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
    if isinstance(error, TiingoSymbolNotFoundError):
        return "No market data found. Please try again later."
    if isinstance(error, (TiingoRequestError, TiingoError)):
        return "Market data is temporarily unavailable. Check your network and try again."
    if isinstance(error, InsufficientRegimeHistoryError):
        return "Not enough SPY history is available to evaluate the market regime."
    if isinstance(error, InvalidRegimeDataError):
        return "Market regime data is invalid. Please try again later."
    if isinstance(error, StaleRegimeDataError):
        return "Market regime data is stale. Please try again after market data updates."
    if isinstance(error, ValueError):
        return "Market regime data is invalid. Please try again later."
    return "Something went wrong while evaluating the market regime. Please try again."


def format_score(score: int) -> str:
    """Format a bounded component or regime score with a visible sign."""

    return f"{score:+d}"


def format_exposure(exposure: float) -> str:
    """Format a maximum long exposure as a whole percentage."""

    return f"{exposure:.0%}"


def format_metric_value(metric: RegimeMetric) -> str:
    """Format one raw metric according to its immutable engine unit."""

    if metric.unit == "ratio":
        return f"{metric.value:.1%}"
    if metric.unit == "price":
        return f"{metric.value:,.2f}"
    return f"{metric.value:,.2f}"


def component_rows(components: tuple[RegimeComponent, ...]) -> list[dict[str, str]]:
    """Convert components to concise, read-only evidence table rows."""

    return [
        {
            "Component": component.name,
            "Raw values": "; ".join(
                f"{metric.name}: {format_metric_value(metric)}"
                for metric in component.metrics
            ),
            "Score": format_score(component.score),
            "Explanation": component.explanation,
        }
        for component in components
    ]


def render_regime_result(result: RegimeResult) -> None:
    """Render immutable regime output without any trading action or broker path."""

    with st.container(horizontal=True):
        st.metric("Regime", result.regime.value, border=True)
        st.metric("Score", format_score(result.score), border=True)
        st.metric("Confidence", result.confidence.value, border=True)
        st.metric("Maximum exposure", format_exposure(result.maximum_long_exposure), border=True)
        st.metric("Strategy permission", result.strategy_permission.value, border=True)

    st.subheader("Component evidence")
    st.dataframe(component_rows(result.components), hide_index=True)

    st.subheader("Reasons")
    for reason in result.reasons:
        st.write(f"- {reason}")

    st.subheader("Data quality")
    quality = result.data_quality
    st.write(f"Requested date: {quality.requested_date.isoformat()}")
    st.write(f"Latest SPY date: {quality.latest_spy_date.isoformat()}")
    st.write(f"Data age: {quality.data_age_days} day(s)")
    st.write(
        f"Observations used: {quality.observations_used} of "
        f"{quality.required_observations} required"
    )
    st.write(f"QQQ confirmation: {quality.qqq_status.value}")
    for warning in quality.warnings:
        st.warning(warning)


def main() -> None:
    """Render the safe page chrome before any configuration or data access."""

    st.set_page_config(
        page_title="Market Regime",
        page_icon=":material/monitoring:",
        layout="wide",
    )
    st.title("Market Regime")
    st.warning(
        "Research guidance only — this deterministic regime estimate is not "
        "investment advice or certainty, and it cannot place orders."
    )
    st.caption(
        "Method: SPY trend, momentum, drawdown, and realized volatility are "
        "combined with optional QQQ confirmation using end-of-day history."
    )

    evaluate_clicked = st.button(
        "Evaluate regime",
        type="primary",
        icon=":material/analytics:",
        key="evaluate_regime",
    )
    result_slot = st.container()

    if evaluate_clicked:
        try:
            with st.spinner("Evaluating the current market regime..."):
                result = evaluate_current_regime(date.today())
        except Exception as error:
            with result_slot:
                st.error(regime_error_message(error))
        else:
            with result_slot:
                render_regime_result(result)


if __name__ == "__main__":
    main()
