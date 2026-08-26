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

## Collaboration workflow

- `main` stays reviewable and runnable.
- Use short-lived feature branches.
- Open a pull request before merging to `main`.
- Do not commit generated datasets, credentials, or licensed vendor exports unless their terms explicitly allow it.

See `CONTRIBUTING.md` for the team workflow.

## Disclaimer

This repository is for research and education. Quantitative strategies can lose money, and historical performance does not guarantee future results.
