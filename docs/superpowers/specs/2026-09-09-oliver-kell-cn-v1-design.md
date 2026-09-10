# Oliver Kell CN V1 Design

## Goal

Add an isolated, research-only A-share implementation of an Oliver Kell-inspired Cycle of Price Action (CPA) strategy to `private-quant-lab`, with explicit point-in-time controls and China-market execution assumptions. The experiment must not alter the existing ETF momentum or market-regime behavior.

## Scope

V1 evaluates whether a simplified CPA strategy plus growth/fundamental screening produces out-of-sample excess return versus CSI 300. It is a research backtest only: no live trading, broker integration, machine learning, or automatic execution.

## Architecture

The implementation follows the repository's existing provider-independent layering:

- `data/`: point-in-time A-share research records and market-state inputs.
- `research/oliver_kell/`: fundamental eligibility, universe filtering, and price-action signal logic.
- `strategies/oliver_kell_cpa.py`: strategy configuration and deterministic signal composition.
- `backtest/oliver_kell_cpa.py`: portfolio simulation, A-share execution constraints, transaction costs, and metrics.
- `configs/oliver_kell_cn_v1.json`: frozen V1 parameters.
- `tests/`: synthetic fixtures proving no future information leaks into historical decisions.

Do not add Qlib or `cn-trader` as a runtime dependency in V1. External projects may be used as references, but the experiment stays inside the existing `private_quant` architecture.

## Point-in-time data contract

Each fundamental observation must include at least:

- `ticker`
- `report_period`
- `announcement_date`
- `available_from`
- `revenue_yoy`
- `net_profit_yoy`
- `roe`
- `eps`
- `float_market_cap_rmb`

A backtest decision on date `D` may only use observations where `available_from <= D`. Restating or editing a future record must never alter an earlier eligibility result.

V1 may use synthetic fixtures for automated tests. Real-data ingestion is kept behind an interface so the provider can be replaced later without changing strategy logic.

## Fundamental screen

A stock is eligible only when the latest point-in-time record available on the decision date satisfies all of:

- quarterly revenue YoY >= 30%
- quarterly net profit YoY >= 30%
- ROE >= 8%
- EPS > 0
- float market cap between RMB 5 billion and RMB 50 billion, inclusive

## Universe filters

Exclude symbols that are not realistically tradable for the intended experiment, including:

- ST / *ST securities
- suspended securities
- IPOs younger than the configured seasoning period
- symbols failing the configured minimum liquidity threshold

The universe logic must use only state known on the decision date.

## Technical signals

V1 computes:

- EMA 10
- EMA 20
- SMA 50
- SMA 200
- relative-strength series
- volume confirmation

The first implemented entry families are:

1. `WEDGE_POP`: a deterministic breakout/reclaim condition defined entirely from historical bars up to the signal date.
2. `EMA_CROSSBACK`: a deterministic pullback-and-support condition around the configured EMA after a qualifying trend transition.
3. `BASE_N_BREAK`: a deterministic breakout from a recent consolidation range; included in the V1 module but may be disabled in the default config until its synthetic tests pass.

Every emitted signal contains:

- `ticker`
- `date`
- `signal_type`
- `signal_price`
- `stop_price`
- `reason`

Signals are research events, not broker orders.

## A-share execution model

The backtester must model at minimum:

- long-only
- no leverage
- maximum 10 concurrent positions
- 100-share board lots
- T+1: shares bought on date D cannot be sold on D
- configurable commission
- configurable stamp duty on sells
- configurable slippage
- suspension blocks execution
- limit-up blocks buys when the assumed fill is unavailable
- limit-down blocks sells when the assumed fill is unavailable

The simulator must not claim a fill that market-state inputs mark as unavailable.

## Position sizing and exits

V1 uses equal-risk sizing subject to available cash, 100-share lot rounding, and the 10-position cap.

Exit rules:

- initial protective stop derived from the entry signal
- trailing exit based on the 20 EMA

An exhaustion-extension discretionary exit is out of scope for V1.

## Experiment design

Benchmark: CSI 300.

Development window: 2015-01-01 through 2021-12-31.

Out-of-sample window: 2022-01-01 through the latest supported 2026 data available to the research dataset.

Parameters are selected/frozen using only the development window. No optimization or tuning may use the out-of-sample window.

V1 must report at least:

- total return
- CAGR
- maximum drawdown
- Sharpe ratio
- Calmar ratio
- win rate
- profit factor
- average winner
- average loser
- trades per year
- turnover
- benchmark return / excess return

## Experiment variants

The architecture must support later comparison of:

- A: CPA technical only
- B: CPA + fundamentals
- C: CPA + fundamentals + market regime

V1 default is B. Existing market-regime modules are not connected to CPA in this phase.

## Bias controls

The implementation must explicitly test for:

- look-ahead bias in fundamentals
- survivorship-sensitive universe state
- future revisions changing past signals
- impossible limit-up/limit-down fills
- same-day sell after buy under T+1

A strategy result is invalid if these controls are not satisfied.

## Testing strategy

Use deterministic synthetic datasets first. Tests must prove:

1. a fundamental record is invisible before `available_from`;
2. a later record or restatement cannot change an earlier eligibility decision;
3. known price sequences emit only the expected CPA signals;
4. T+1 is enforced;
5. 100-share lot rounding is enforced;
6. blocked limit-up buys and limit-down sells remain unfilled;
7. portfolio and metrics calculations are deterministic;
8. the new module does not break the existing test suite.

## Non-goals

- live trading
- IBKR integration for A shares
- short selling
- intraday execution
- ML/AI prediction
- Qlib migration
- parameter search on 2022-2026 data
- reproducing Oliver Kell's 2020 competition return

## Acceptance criteria

V1 is accepted when a synthetic end-to-end backtest can run from point-in-time fundamentals and daily bars through eligibility, CPA signals, A-share execution, portfolio accounting, and metrics; all bias/execution guardrail tests pass; and existing repository tests remain green.