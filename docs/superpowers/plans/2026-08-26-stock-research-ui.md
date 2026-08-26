# Stock Research UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Streamlit research page that retrieves about one year of daily Tiingo EOD data for a normalized ticker and presents the latest bar, daily change, chart, table, and a fundamentals placeholder without exposing credentials or adding trading features.

**Architecture:** Keep Streamlit limited to configuration, user input, rendering, and user-facing error messages. Put ticker validation, date-range calculation, provider invocation, ordering, latest-bar selection, and daily-change calculation in an immutable research service; leave HTTP, authentication, response parsing, and Tiingo-specific status mapping in the existing Tiingo adapter.

**Tech Stack:** Python 3.11+, standard-library `unittest`, Streamlit, python-dotenv, existing `MarketDataProvider` and `TiingoMarketDataProvider`.

## Global Constraints

- Read `MARKET_DATA_PROVIDER` and `MARKET_DATA_API_KEY` from the repository-root local `.env` file.
- Never display, log, commit, or include the API key in an exception message.
- Fetch approximately one year of daily EOD data ending on the lookup date.
- Do not add trading, order-entry, broker-connection, real-time quotes, or SEC fundamentals implementation.
- Show `SEC fundamentals integration coming next` in the Fundamentals section.
- Keep UI logic separate from provider logic.

---

### Task 1: Stock lookup service

**Files:**
- Create: `src/private_quant/research/__init__.py`
- Create: `src/private_quant/research/stock_lookup.py`
- Create: `tests/test_stock_lookup.py`

**Interfaces:**
- Consumes: `MarketDataProvider.get_price_history(symbol: str, start: date, end: date) -> Sequence[PriceBar]`.
- Produces: `StockLookupService.lookup(ticker: str, *, as_of: date | None = None) -> StockResearchResult`, `normalize_ticker(ticker: str) -> str`, `BlankTickerError`, and `NoMarketDataError`.

- [ ] **Step 1: Write failing service tests**

  Add behavior tests proving whitespace/case normalization, blank rejection, the literal 365-day inclusive lookup window, chronological result ordering and latest-bar selection, daily percentage change from the two latest closes, empty-history handling, and unchanged propagation of provider exceptions.

- [ ] **Step 2: Run the service test file and verify RED**

  Run: `python -m unittest tests.test_stock_lookup -v`

  Expected: import failure because `private_quant.research.stock_lookup` does not exist.

- [ ] **Step 3: Implement the minimal immutable service**

  Define frozen `StockResearchResult` with normalized ticker, requested start/end dates, ascending history tuple, latest bar, and optional daily-change percentage. Normalize with `strip().upper()`, raise a specific blank-input error, request `as_of - timedelta(days=365)` through `as_of`, sort defensively by trading date, raise `NoMarketDataError` for an empty sequence, and do not catch provider exceptions.

- [ ] **Step 4: Run the service tests and full suite**

  Run: `python -m unittest tests.test_stock_lookup -v`

  Run: `python -m unittest discover -s tests -v`

  Expected: all tests pass.

### Task 2: Tiingo unknown-symbol error and local app configuration

**Files:**
- Modify: `src/private_quant/data/tiingo.py`
- Create: `src/private_quant/app/__init__.py`
- Create: `src/private_quant/app/config.py`
- Modify: `tests/test_tiingo_provider.py`
- Create: `tests/test_app_config.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: Tiingo HTTP status codes and `.env` keys `MARKET_DATA_PROVIDER`, `MARKET_DATA_API_KEY`.
- Produces: `TiingoSymbolNotFoundError`, `AppConfiguration`, `ConfigurationError`, `load_app_configuration()`, and `build_market_data_provider()`.

- [ ] **Step 1: Write failing provider/configuration tests**

  Add a Tiingo transport test proving HTTP 404 maps to `TiingoSymbolNotFoundError`. Add configuration tests proving case-insensitive `tiingo` selection creates `TiingoMarketDataProvider`, missing provider/key values raise safe setup messages that do not contain a supplied key, and unsupported providers are rejected without reflecting secrets.

- [ ] **Step 2: Run targeted tests and verify RED**

  Run: `python -m unittest tests.test_tiingo_provider tests.test_app_config -v`

  Expected: missing error/configuration symbols cause failures.

- [ ] **Step 3: Implement safe error mapping and configuration**

  Map only HTTP 404 to the new unknown-symbol exception, retaining existing 401/403, 429, network, and invalid-response handling. Load the repository-root `.env` with python-dotenv, read only the two required variables, validate them without interpolating their values, and construct the existing Tiingo provider only when the configured provider is `tiingo`.

- [ ] **Step 4: Add runtime dependencies and verify tests**

  Add `streamlit` and `python-dotenv` to `[project].dependencies`. Run the two targeted test modules and then the full suite; expect all tests to pass.

### Task 3: Thin Streamlit research page and usage documentation

**Files:**
- Create: `src/private_quant/app/stock_research.py`
- Modify: `README.md`
- Modify: `tests/test_package_imports.py`

**Interfaces:**
- Consumes: `load_app_configuration()`, `build_market_data_provider()`, `StockLookupService.lookup()`, and the service/provider exception types.
- Produces: a Streamlit page runnable with `python -m streamlit run src/private_quant/app/stock_research.py`.

- [ ] **Step 1: Add the app/research package import contract and verify RED**

  Extend the package-import test with `private_quant.app` and `private_quant.research`, then run it before creating the package files if Task 1/2 have not already made it green.

- [ ] **Step 2: Implement Streamlit rendering**

  Configure the page title `Private Quant Lab — Stock Research`, render a ticker input and Search button, build configuration/provider only after Search, call the lookup service, and render latest trading date, close, adjusted close, open/high/low, volume, daily percentage change, adjusted-close line chart, twenty most recent rows, and the exact Fundamentals placeholder.

- [ ] **Step 3: Add precise safe user-facing errors**

  Map blank ticker, empty history/404, missing configuration, authentication, rate limit, and network/provider failures to compact guidance. Use a generic retry message for unexpected failures and never render exception details or configuration values.

- [ ] **Step 4: Document exact local run flow**

  Update README with Windows PowerShell commands for virtual-environment creation, activation, editable dependency installation, `.env` setup, and launching Streamlit. State that the page displays latest available EOD data and has no order functionality.

- [ ] **Step 5: Install, compile, test, and smoke-check**

  Create/use a local virtual environment, install the editable project dependencies, run `python -m unittest discover -s tests -v`, run `python -m compileall -q src tests`, start Streamlit headlessly, request its health endpoint, and stop it. If a local `.env` is present, query AAPL and QQQ through the service without printing credentials; otherwise report that live-data validation was skipped because no local credentials were available.

### Task 4: Security review and pull request

**Files:**
- Review all changed files and Git metadata; no new production files are required.

**Interfaces:**
- Consumes: completed diff and repository PR template.
- Produces: pushed `codex/streamlit-stock-research` branch and a pull request targeting `main`.

- [ ] **Step 1: Review requirement coverage and secret safety**

  Inspect the staged diff, confirm `.env` remains ignored/untracked, search tracked changes for API-key-shaped values or credential output, and confirm no trading/order code was introduced.

- [ ] **Step 2: Run fresh final verification**

  Run the complete unittest suite and compile checks again after all edits. Record exact passing counts and smoke-test evidence.

- [ ] **Step 3: Commit, push, and create the PR**

  Commit the focused implementation, push `codex/streamlit-stock-research`, and create a PR to `main` using the repository template with data-source scope, test results, security confirmation, and the live-smoke-test limitation if credentials were absent.
