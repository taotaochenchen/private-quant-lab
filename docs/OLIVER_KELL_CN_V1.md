# Oliver Kell CN V1

This experiment evaluates an Oliver Kell-inspired Cycle of Price Action strategy on A-share-style assumptions. It is a research module only and is not intended to reproduce Oliver Kell's 2020 competition return.

## V1 hypothesis

Test whether deterministic CPA entry signals combined with a simplified growth/fundamental screen can produce useful out-of-sample evidence versus CSI 300 after A-share execution constraints and transaction costs.

Default variant: `fundamental_plus_cpa`.

## Frozen fundamental screen

- quarterly revenue YoY >= 30%
- quarterly net profit YoY >= 30%
- ROE >= 8%
- EPS > 0
- float market cap RMB 5B-50B inclusive

Fundamental records are point-in-time records. A decision on date `D` can only use data whose `available_from <= D`. Future restatements must not change past eligibility.

## Technical signals

V1 provides deterministic implementations for:

- Wedge Pop
- EMA Crossback
- Base n' Break (disabled by default in the frozen config)

Signals are research events and never broker orders.

## A-share execution assumptions

The execution module models:

- long only
- no leverage
- 100-share board lots
- T+1 sell restriction
- configurable commission
- sell-side stamp duty
- configurable slippage
- suspended execution blocking
- limit-up buy blocking when a fill is unavailable
- limit-down sell blocking when a fill is unavailable

## Experiment windows

- Development: 2015-01-01 through 2021-12-31
- Out-of-sample: 2022-01-01 onward

Do not tune parameters on out-of-sample data.

## Bias controls

Automated synthetic tests cover point-in-time visibility, future restatements, universe-state dates, signal causality, T+1, board-lot rounding, and impossible limit fills.

A real historical A-share backtest is not considered valid until its data provider supplies point-in-time fundamentals, historical security state, suspensions, and tradability/limit information without survivorship or look-ahead leakage.

## Running focused tests

```bash
python -m unittest tests.test_oliver_kell_filters tests.test_oliver_kell_signals tests.test_oliver_kell_strategy tests.test_oliver_kell_backtest -v
```

Run the full regression suite before merge:

```bash
python -m unittest discover -s tests -v
```

## Current limitation

V1 establishes the research contracts, deterministic strategy logic, execution guards, frozen config, and metric primitives. It does not yet ingest a production point-in-time A-share dataset. That provider integration should be a separate change so data quality can be reviewed independently from strategy behavior.
