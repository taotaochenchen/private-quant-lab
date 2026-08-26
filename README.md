# Private Quant Lab

Private research repository for building and validating low-frequency quantitative investing strategies before any live deployment.

## Principles

- Research first, paper trade second, live capital last.
- Prefer simple, explainable strategies over fragile complexity.
- Keep market-data providers replaceable behind stable interfaces.
- Never commit API keys, credentials, broker tokens, or private account data.
- Treat backtests as evidence to challenge, not proof of future returns.

## Initial scope

1. Data-source inventory and provider adapters.
2. ETF momentum / trend strategy research.
3. Multi-factor equity research.
4. Backtesting with transaction-cost assumptions and bias controls.
5. Portfolio and risk rules.
6. Paper-trading integration, then optional broker execution.

## Repository layout

```text
src/private_quant/data/       Data models and provider interfaces
src/private_quant/research/   Provider-independent research services
src/private_quant/app/        Local Streamlit user interfaces
src/private_quant/strategies/ Strategy implementations
src/private_quant/backtest/   Backtest engine and metrics
src/private_quant/risk/       Risk controls
src/private_quant/portfolio/  Portfolio construction
src/private_quant/broker/     Broker adapters (paper first)
tests/                        Automated tests
docs/DATA_SOURCES.md          API/vendor research matrix
docs/ROADMAP.md               Delivery roadmap
```

## Local setup

Python 3.11+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Copy `.env.example` to `.env` only when credentials are needed. `.env` is ignored by Git.

## Local stock research app (Windows PowerShell)

The app shows the latest available daily end-of-day data; it is not a live quote or a trading/order interface.

From the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
if (!(Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

In `.env`, keep `MARKET_DATA_PROVIDER=tiingo` and place your Tiingo token after `MARKET_DATA_API_KEY=`. Do not share or commit this file.

Start the app:

```powershell
python -m streamlit run src/private_quant/app/stock_research.py
```

Enter a ticker such as `AAPL`, `NVDA`, `MSFT`, or `QQQ`, then select **Search**. Stop the local app with `Ctrl+C` in PowerShell.

## Local IBKR Paper broker page (Windows PowerShell)

Phase 1 is a read-only status page. It can connect to TWS Paper and display a
sanitized account snapshot, but it has no order submission, preview,
cancellation, modification, what-if, staging, or transmit capability.

Before running the page:

- Install the official TWS Python API from IBKR's TWS API download into this
  project's active `.venv`. The project intentionally does not declare an
  `ibapi` package from PyPI. From the official download's
  `source\pythonclient` directory, install that local official source with
  `python -m pip install .` while the project environment is active.
- Log in to TWS **Paper Trading**.
- Keep TWS API socket clients and **Read-Only API** enabled.
- Keep the Phase 1 endpoint at `127.0.0.1:7497` with client ID `10`.

The guarded setup command above creates `.env` only when it does not already
exist. Add these non-secret broker settings to your local `.env` without
removing the market-data settings:

```text
BROKER_PROVIDER=ibkr
BROKER_MODE=paper
BROKER_HOST=127.0.0.1
BROKER_PORT=7497
BROKER_CLIENT_ID=10
```

Start the broker page from the repository root:

```powershell
python -m streamlit run src/private_quant/app/broker_status.py
```

Select **Connect / Refresh** to take one read-only snapshot. If open-order
information does not complete, the page reports a neutral unavailable or
timeout status unless TWS provides positive evidence of the specific cause.
Read-Only API remains enabled throughout Phase 1.

## Local IBKR Paper order Preview page (Windows PowerShell)

Phase 2 adds a manual PAPER order ticket for US stocks and ETFs. It can create
a short-lived Preview, but it cannot submit an order in this pull request:
TWS Read-Only API stays enabled, the Submit button is disabled, and the
production executor is fixed to `submission_enabled=False`.

Start the Preview page from the repository root:

```powershell
python -m streamlit run src/private_quant/app/paper_trading.py
```

Each MARKET Preview makes a new IBKR snapshot request and accepts only IBKR
live market-data type `1`: BUY uses the returned ask and SELL uses the returned
bid. The `tickPrice` snapshot callback used by this adapter has no quote
timestamp, so the age of that bid or ask cannot be independently verified.
"New snapshot request" and "IBKR live market-data type" must not be read as a
claim that quote age was checked. Delayed/frozen data types and missing,
non-positive, NaN, or infinite prices remain blocked. The app never falls back
to Tiingo, a reused quote, a closing price, or a guessed price.

The named **USD 950 MARKET Preview safety buffer** reserves USD 50 for possible
price movement below the separate **USD 1,000 Submit hard limit**. USD 950 is
not the Submit limit. A future enabled Submit would make another new IBKR live
snapshot request and enforce the USD 1,000 limit again immediately before
sending, but quote age would still not be independently verified.

LIMIT Preview uses the entered limit price and allows at most USD 1,000
estimated notional. Every Preview is bound to the exact ticket, expires after
60 seconds, and can be consumed only once by the tested execution layer.
Keep TWS Read-Only API enabled for this phase.

## Collaboration workflow

- `main` stays reviewable and runnable.
- Use short-lived feature branches.
- Open a pull request before merging to `main`.
- Do not commit generated datasets, credentials, or licensed vendor exports unless their terms explicitly allow it.

See `CONTRIBUTING.md` for the team workflow.

## Disclaimer

This repository is for research and education. Quantitative strategies can lose money, and historical performance does not guarantee future results.
