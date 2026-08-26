# Contributing

## Branches

Create a branch per focused change:

- `feature/data-api`
- `feature/fundamental-data`
- `feature/etf-momentum`
- `feature/backtest-engine`
- `fix/<short-description>`

Avoid long-lived personal branches.

## Pull requests

Before opening a PR:

1. Run `python -m unittest discover -s tests -v`.
2. Confirm no `.env`, API key, account identifier, licensed dataset, or raw broker export is staged.
3. Explain the data source, assumptions, and any known limitations.
4. For strategy changes, include the test period and specify whether results are in-sample, validation, or out-of-sample.

## Data-source changes

Every candidate API belongs in `docs/DATA_SOURCES.md` before the project depends on it. Record pricing, coverage, historical depth, point-in-time behavior, rate limits, redistribution restrictions, and accessibility from both Canada and mainland China where relevant.

## Research hygiene

- Never use future information in a historical decision.
- Record transaction-cost and slippage assumptions.
- Do not judge a strategy only by CAGR; include drawdown and risk-adjusted metrics.
- Prefer reproducible scripts over notebook-only logic.
