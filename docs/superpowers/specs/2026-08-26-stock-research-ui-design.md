# Stock Research UI Design

Date: 2026-08-26

## Goal

Add a small local web interface to Private Quant Lab so a user can enter a U.S.-listed stock or ETF ticker (for example AAPL, NVDA, MSFT, QQQ) and immediately inspect recent market data without using PowerShell commands.

The first release is a research viewer, not a trading interface. It must never place orders or expose credentials.

## Recommended approach

Use Streamlit for V1.

Why:
- It runs locally with one command and opens in the browser.
- It can call the existing `TiingoMarketDataProvider` directly.
- It avoids introducing a separate frontend/backend stack before the research workflow is proven.
- It can later grow into strategy and backtest dashboards without changing the underlying provider interfaces.

Alternatives considered:
- Flask: more flexible HTTP architecture, but more boilerplate for this stage.
- React + API backend: best long-term UI flexibility, but unnecessary complexity for V1.

## User flow

1. User starts the local Streamlit app.
2. The app reads `MARKET_DATA_PROVIDER` and `MARKET_DATA_API_KEY` from the local `.env` file.
3. User enters a ticker and clicks Search.
4. The app normalizes the ticker to uppercase and requests recent daily EOD history through the internal market-data provider.
5. The page shows:
   - ticker
   - latest available trading date
   - latest open, high, low, close
   - adjusted close
   - volume
   - recent price history table
   - adjusted-close line chart
6. A Fundamentals section is visible but marked as not yet connected until the SEC EDGAR adapter is implemented.

## Architecture

Keep the UI thin. Streamlit must not know Tiingo response fields.

Components:

- `src/private_quant/app/stock_research.py`
  - Streamlit page and UI state only.
  - Calls a small application service rather than performing HTTP work directly.

- `src/private_quant/research/stock_lookup.py`
  - Input validation and date-range selection.
  - Calls `MarketDataProvider.get_price_history()`.
  - Returns a UI-friendly immutable result object containing latest-bar and history information.

- Existing `src/private_quant/data/tiingo.py`
  - Continues to own Tiingo HTTP/authentication/payload mapping.

This separation keeps provider code reusable by backtests and prevents future UI changes from leaking into data adapters.

## Configuration and security

- Read credentials from local `.env` only.
- `.env` stays ignored by Git and must never be displayed in the app.
- Do not accept an API token through the web page.
- Do not log the token or include it in error messages.
- If required configuration is missing, show a user-facing setup message rather than a traceback.

The app should load `.env` itself so the user does not need to manually export PowerShell environment variables.

## Data scope for V1

Default history window: approximately one year of daily data ending on today's date.

V1 supports the same U.S.-listed symbols that the configured market-data provider supports. It does not promise real-time prices; all labels must say latest available EOD / trading-day data rather than "live price".

The chart uses adjusted close because it is appropriate for historical research. The latest summary card may show both raw close and adjusted close.

## Error handling

User-facing cases:
- blank ticker: ask for a symbol
- invalid/unknown ticker or empty provider response: show "No market data found"
- missing API configuration: show setup instructions without revealing secrets
- Tiingo authentication failure: explain that the local token should be checked
- rate limit: explain that the provider limit was reached and the user should retry later
- network/provider errors: show a compact retryable error

Unexpected programming errors should not be converted into misleading "ticker not found" messages.

## UI layout

Page title: `Private Quant Lab — Stock Research`

Top area:
- ticker text input
- Search button

Result area:
- four/five metric cards for latest close, adjusted close, volume, latest date, and optional daily change if enough observations are present
- adjusted-close line chart
- recent daily data table
- Fundamentals section with a clear `SEC fundamentals integration coming next` placeholder

Keep the UI functional and clean; no custom design system is required in V1.

## Dependencies

Add minimal runtime dependencies:
- `streamlit`
- `python-dotenv`

Do not add pandas unless Streamlit/chart behavior makes it materially simpler; prefer existing Python data structures where practical.

## Testing

Use TDD for implementation.

Automated tests should cover the application/service layer without launching a browser:
- ticker normalization
- blank ticker rejection
- requested date range
- latest-bar selection
- empty-history handling
- provider errors passed/mapped correctly

The Streamlit file should remain thin enough that most behavior is tested outside Streamlit.

After implementation:
- run the full existing test suite
- run Python compile checks
- perform a local smoke test with the user's Tiingo `.env`
- search AAPL and QQQ and confirm recent data renders

## Non-goals for V1

- real-time streaming quotes
- order entry or broker connection
- portfolio tracking
- user accounts/authentication
- public internet hosting
- technical indicators beyond the simple price chart
- parameterized backtests in the UI
- SEC fundamentals implementation itself

## Success criteria

From the repository root, the user can install the project dependencies and run one command to open the local stock-research page. Entering a valid ticker returns recent real EOD market data and a chart while the API token remains local and invisible.