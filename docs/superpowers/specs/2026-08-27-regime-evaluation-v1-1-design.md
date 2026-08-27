# Market Regime Evaluation V1.1 Design

**Date:** 2026-08-27
**Status:** Design for review
**Scope:** Deterministic research evaluation only

## Purpose

Evaluation V1.1 will determine whether Market Regime V1's lower CAGR than SPY
buy-and-hold is primarily associated with:

1. the current zero-yield residual-cash assumption;
2. frequent exposure changes and whipsaw;
3. modeled transaction costs; or
4. the fixed `100% / 70% / 30% / 0%` exposure mapping.

This change evaluates the existing methodology. It does not alter Market
Regime V1 scores, thresholds, confidence, regime classification, or exposure
mapping. It does not create an execution path and does not change broker,
IBKR, order, paper-trading, or live-trading code.

The implementation priority is a reusable deterministic result model and
pure evaluation logic. No Streamlit page is part of V1.1.

## Assumptions and interpretation decisions

The following decisions remove ambiguity without expanding scope:

- Initial capital for full-period comparisons remains USD 100,000.
- SPY buy-and-hold, the 200-session trend benchmark, and both Regime V1
  variants are all evaluated on one common sequence of return intervals.
- The trend benchmark's `0% SPY` state earns zero cash return. Only the
  explicitly named **Regime V1 with BIL-return residual cash proxy** uses BIL
  returns.
- BIL is a return proxy for residual cash, not a held or traded security.
- Every cost scenario applies the same basis-point rate to changes in SPY
  target exposure for every strategy. There is no separate BIL commission
  leg.
- The first target SPY exposure is measured from a prior exposure of zero.
  Therefore, nonzero initial SPY allocation incurs an opening exposure-change
  cost when the selected cost rate is nonzero.
- Full-period risk ratios use a zero daily hurdle. No Treasury bill,
  risk-free-rate, or BIL series is silently subtracted from returns for
  Sharpe or Sortino.
- Historical-window summaries are slices of the continuous full evaluation,
  rebased to 100. They do not liquidate and restart the strategy at each
  window boundary.
- Optional QQQ may still be supplied to the existing regime classifier for
  confidence reporting, but confidence does not control exposure. QQQ is not
  part of the comparison date alignment and cannot change strategy returns.

## Non-goals

Evaluation V1.1 will not:

- tune, optimize, or refit any regime threshold, score, indicator window, or
  exposure level;
- select parameters using 2008, 2020, 2022, or 2023-2025 outcomes;
- claim that the portfolio actually trades or owns BIL;
- model BIL commissions, spreads, slippage, taxes, borrow, dividends outside
  provider-adjusted closes, or intraday execution;
- add a provider, HTTP client, broker dependency, Streamlit page, or order
  integration;
- access `.env` in automated tests;
- connect to TWS or IB Gateway;
- call `placeOrder` or introduce automatic trading; or
- change the existing Market Regime V1 public result or scoring contract.

## Architecture

### Placement

The work extends `src/private_quant/backtest/regime_evaluation.py` and its
tests. The regime engine remains the source of daily Regime V1 results and is
not modified.

The new comparison entry point will:

1. validate and align SPY and BIL adjusted-close histories;
2. obtain unchanged Regime V1 target exposures point-in-time;
3. independently construct SPY buy-and-hold and 200-session trend exposures;
4. apply each exposure sequence to the same next-session returns;
5. run the four requested transaction-cost scenarios;
6. calculate deterministic metrics; and
7. derive fixed historical-window summaries from the full results.

The existing `evaluate_regime_history` API remains available and unchanged.
V1.1 adds a separate orchestration function rather than changing the meaning
of existing V1 output.

### Proposed immutable result model

New models will be frozen, slotted dataclasses. Exact field names may follow
the repository's naming style, but the contract will contain only these
concepts:

- `EvaluationStrategy`: the four fixed strategy identifiers.
- `EvaluationPoint`: `signal_date`, `return_end_date`, value before modeled
  cost at the signal date, ending value at the return-end date, target SPY
  exposure, SPY return, residual-cash return, net portfolio return, exposure
  change, and transaction cost for that explicit interval. `signal_date` is
  also the interval start date; no ambiguous single `trading_date` field is
  used.
- `PerformanceMetrics`: initial capital, final value, total return, CAGR,
  maximum drawdown, annualized volatility, Sharpe, Sortino, Calmar, total
  transaction cost, annualized turnover, exposure-change count,
  time-weighted average SPY exposure, and exposure-bucket percentages.
- `StrategyScenarioResult`: strategy, transaction-cost basis points, common
  interval start/end boundaries, metrics, and immutable interval
  observations.
- `HistoricalWindowResult`: requested window dates, effective first
  `signal_date`, effective final `return_end_date`, strategy, cost basis
  points, normalized start/end value, strategy return, maximum drawdown,
  exposure changes, average SPY exposure, and normalized transaction cost.
- `RegimeEvaluationV11Result`: common ordered `(signal_date,
  return_end_date)` interval boundaries, all strategy/cost results, and all
  historical-window results.

Ratios that are mathematically undefined because their denominator is zero
will be `None`, not an invented zero or infinity. User-facing consumers can
render `None` as `N/A`.

No result model contains provider objects, credentials, broker state, or
account data.

## Input validation and point-in-time boundary

### Required inputs

- SPY daily `PriceBar` history with provider-supplied adjusted closes.
- BIL daily `PriceBar` history with provider-supplied adjusted closes.
- Optional QQQ history, passed only through the existing V1 classifier.

The evaluator accepts an explicit evaluation start and end or uses the full
eligible common history. It does not load market data itself.

### Validation rules

For SPY and BIL observations that enter the requested evaluation boundary:

- symbols must normalize exactly to `SPY` and `BIL` respectively;
- dates must be valid, canonical daily session dates;
- dates must be unique;
- adjusted closes must be numeric, finite, and strictly positive; and
- observations are sorted by canonical trading date.

Fixed, sanitized evaluation errors will identify the invalid series and rule,
without including raw provider payloads or secrets.

### Point-in-time isolation

Validation and alignment occur after isolating records by their canonical
date and the requested evaluation end. A record with a valid date after the
requested end cannot affect an earlier result merely because its adjusted
close, symbol, or other value is malformed.

For an evaluation ending at `T`, the evaluator must not inspect price content
from any SPY or BIL observation dated after `T`. A future observation with a
valid future date and a missing, malformed, non-finite, non-positive, or
otherwise invalid adjusted close therefore cannot mutate or invalidate
results ending before that date.

An observation whose date itself is missing or cannot be interpreted cannot
be proved to be in the future. It fails safely instead of being guessed away.
This is an intentional boundary: point-in-time isolation requires a usable
date.

The existing regime classifier continues to receive only SPY observations on
or before each signal date. Optional QQQ retains its existing point-in-time
handling.

## Common date alignment

### Eligibility and warm-up

The SPY history may contain earlier warm-up observations that are not part of
the performance interval:

- Market Regime V1 requires its existing 252-session history.
- The simple trend benchmark requires 200 SPY sessions ending on signal date
  `T`.

The first eligible SPY signal date is the first date on which the unchanged
Regime V1 classifier can produce a result. This is also sufficient for the
200-session benchmark.

### BIL common-start truncation

Let the eligible SPY signal dates be `D0 ... Dn-1`, with next-session return
endpoints `D1 ... Dn`. Outer boundaries are discovered from canonical dates
only, before adjusted-close content is validated. The full common interval
start is the first eligible SPY `signal_date` on or after BIL's first
canonical date. If BIL begins later than eligible Regime V1 history, all four
strategies are truncated to this same first `signal_date`.

The common final `return_end_date` is the earlier of the requested SPY
evaluation end and BIL's last canonical date, rounded to a complete SPY
`T -> T+1` interval. No strategy may retain an earlier first `signal_date` or
later final `return_end_date` than another strategy. After these outer
boundaries are fixed, adjusted-close validation cannot move them. An invalid
price on a boundary date fails instead of silently shortening the period.

This start/end truncation is allowed only at the outer boundaries. Once the
common period begins, including its first and last dates, BIL must have an
exact valid observation on every SPY date used as an interval start or
endpoint. An internal missing BIL session, duplicate date, or invalid adjusted
close fails the evaluation. The evaluator does not scan forward to find a
more convenient start, intersect away a missing date, fill zero, forward-fill,
backfill, or use a nearest prior value.

SPY and BIL are aligned by exact canonical trading date. Array position,
calendar-day offsets, and implicit holiday assumptions are not used.

### Identical comparison intervals

Every strategy and every cost scenario uses the identical ordered sequence:

`(D0 -> D1), (D1 -> D2), ... (Dn-1 -> Dn)`.

The result exposes these common ordered interval-boundary pairs so tests and
consumers can assert equality directly. A strategy-specific dropped boundary
or interval is an error.

Each interval result has two explicit boundaries:

- `signal_date`, which is also `interval_start_date`; and
- `return_end_date`, which is the next aligned SPY/BIL session.

For interval `D0 -> D1`, the signal uses data through `D0`, while the ending
portfolio value is dated `D1`. A consumer must never infer either boundary
from one generic `trading_date`.

## Strategy definitions

### 1. SPY buy-and-hold

- Target SPY exposure is `1.0` on every signal date.
- Residual cash exposure is zero.
- The opening change from `0.0` to `1.0` is costed under nonzero cost
  scenarios.

### 2. Simple 200-session trend benchmark

On signal date `T`:

- calculate the arithmetic mean of SPY adjusted closes for the 200 sessions
  ending on `T`;
- set target SPY exposure to `1.0` when SPY adjusted close on `T` is greater
  than or equal to that SMA; otherwise set it to `0.0`; and
- apply this target only to the SPY adjusted-close return from `T` to the next
  aligned session `T+1`.

The benchmark's residual cash earns zero. Equality is explicitly risk-on, as
required.

### 3. Regime V1 with zero-yield residual cash

- Use the unchanged `maximum_long_exposure` produced by Market Regime V1 on
  signal date `T`: `1.0`, `0.7`, `0.3`, or `0.0`.
- Apply that exposure only to SPY return `T -> T+1`.
- The residual weight `1 - exposure` earns zero.

### 4. Regime V1 with BIL-return residual cash proxy

- Use the same unchanged Regime V1 SPY exposure as strategy 3.
- Apply SPY exposure to SPY adjusted-close return `T -> T+1`.
- Apply residual weight `1 - exposure` to the exact-date BIL adjusted-close
  return over the same `T -> T+1` interval.
- Do not add a BIL exposure-change cost or a second commission leg.

This strategy is labeled **BIL-return residual cash proxy** in models and
documentation. It must never be described as a BIL execution strategy or as
proof that actual cash would have earned the exact BIL return.

## Return and transaction-cost mechanics

For each interval beginning on signal date `T`:

```text
spy_return(T)  = SPY(T+1) / SPY(T) - 1
bil_return(T)  = BIL(T+1) / BIL(T) - 1
cash_return(T) = bil_return(T) only for the BIL-proxy regime strategy;
                 otherwise 0
gross_return(T) = exposure(T) * spy_return(T)
                + (1 - exposure(T)) * cash_return(T)
exposure_change(T) = abs(exposure(T) - exposure(T-1))
```

For the first interval, `exposure(T-1)` is defined as zero.

The portfolio timeline is:

1. Initial capital exists at `D0` before any modeled cost or return.
2. The signal calculated using data through `D0` determines target SPY
   exposure for the interval whose `signal_date` and `interval_start_date`
   are `D0`.
3. The opening SPY exposure-change cost, when nonzero, is charged at `D0`.
4. The resulting target exposure applies only to adjusted-close return
   `D0 -> D1`.
5. The interval's ending portfolio value is dated `D1`, its
   `return_end_date`.
6. At `D1`, the next point begins with that ending value before the next
   modeled cost; the signal through `D1` then applies only to `D1 -> D2`.

Thus each `EvaluationPoint` is an interval record, not a single-date equity
observation. Its starting value belongs to `signal_date`; its ending value
belongs to `return_end_date`.

At cost rate `c = bps / 10,000`:

```text
cost(T) = value_before_cost(T) * exposure_change(T) * c
value_after_cost(T) = value_before_cost(T) - cost(T)
value(T+1) = value_after_cost(T) * (1 + gross_return(T))
```

The four fixed sensitivity rates are `0`, `2`, `5`, and `10` bps. They are
reported side by side and are not inputs to optimization.

This retains the V1 research abstraction: target exposure is a daily weight,
and costs are modeled only when the target SPY exposure changes. It does not
simulate shares, weight drift, bid/ask spread, or daily rebalancing trades
needed to maintain an exact fractional weight. This limitation must remain
visible in the methodology documentation.

## Metric definitions

All metrics use the net value path after modeled SPY exposure-change costs.
The path consists of initial capital dated at the first `signal_date` before
cost/return, followed by each interval's ending value dated at its
`return_end_date`. Daily returns are the net interval returns between those
explicit boundaries.

### Capital and return

- **Initial capital:** configured capital, default USD 100,000.
- **Final value:** last net equity value.
- **Total return:** `final_value / initial_capital - 1`.
- **CAGR:** `(final_value / initial_capital) ** (365.25 / elapsed_calendar_days) - 1`.
  It is `None` when elapsed days are zero or either endpoint is non-positive.

### Drawdown and volatility

- **Maximum drawdown:** minimum of `value / running_peak - 1`, including the
  initial value as the first peak. It is zero when there is no decline.
- **Annualized volatility:** population standard deviation of net daily
  returns multiplied by `sqrt(252)`. It is `None` with fewer than two daily
  returns.

### Sharpe, Sortino, and Calmar

No external or BIL risk-free-rate series is used in these ratios. The daily
hurdle is exactly zero.

- **Sharpe:** `mean(daily_returns) / population_stddev(daily_returns) *
  sqrt(252)`. It is `None` when there are fewer than two returns or volatility
  is zero.
- **Sortino:** `mean(daily_returns) / downside_deviation * sqrt(252)`, where
  `downside_deviation = sqrt(mean(min(return, 0) ** 2))` over **all** daily
  observations. It is `None` when there are no returns or downside deviation
  is zero.
- **Calmar:** `CAGR / abs(maximum_drawdown)`. It is `None` when CAGR is
  undefined or maximum drawdown is zero.

These are deterministic research definitions, not a claim that zero is the
appropriate economic risk-free rate.

### Costs, turnover, and exposure changes

- **Total transaction cost:** sum of the dollar `cost(T)` values.
- **Traded notional:** `value_before_cost(T) * exposure_change(T)`.
- **Annualized turnover:**
  `(sum(traded_notional) / mean(value_before_cost)) /
  (number_of_return_intervals / 252)`.
  It is `None` when there are no intervals or mean equity is non-positive.
- **Number of exposure changes:** count of interval starts where target
  exposure differs from the preceding target, including a nonzero opening
  allocation from the defined prior exposure of zero.
- **Time-weighted average SPY exposure:** arithmetic mean of target SPY
  exposure across common return intervals. It is not value-weighted.
- **Exposure-bucket percentage:** number of return intervals assigned to a
  target exposure divided by the total interval count.

SPY buy-and-hold reports 100%; the trend benchmark reports 0% and 100%; both
Regime V1 variants report 0%, 30%, 70%, and 100%. Non-applicable buckets are
omitted rather than implying the strategy could use them. Percentages for a
strategy must sum to 100% within floating-point tolerance.

## Historical-window summaries

The fixed windows are:

| Label | Requested start | Requested end |
|---|---|---|
| Global financial crisis | 2007-10-01 | 2009-06-30 |
| Calendar 2020 | 2020-01-01 | 2020-12-31 |
| Calendar 2022 | 2022-01-01 | 2022-12-31 |
| Recent recovery/bull period | 2023-01-01 | 2025-12-31 |

For each window, strategy, and cost scenario, include every complete common
return interval whose `signal_date` and `return_end_date` both fall inside the
requested window. The effective start is the first included `signal_date`;
the effective end is the last included `return_end_date`. Both are reported
explicitly.

Window equity is the continuous full-period strategy path rebased so the
value before cost/return at the first effective `signal_date` equals 100. The
ending value of the first included interval is dated at its
`return_end_date`. The strategy is not reset to zero exposure, and no
artificial entry or liquidation cost is introduced at a window boundary.
Costs charged at included `signal_date` values remain included and are scaled
by the same rebasing factor for the normalized-dollar transaction-cost field.

Each window reports at minimum:

- normalized starting value `100`;
- normalized ending value;
- strategy return;
- maximum drawdown of the rebased window path;
- exposure-change count for interval starts in the window;
- time-weighted average SPY exposure;
- normalized transaction cost; and
- effective signal/start date, effective return-end date, and interval count.

If a requested window has fewer than one complete common return interval, its
result is present with an explicit unavailable status and no invented
performance values. Strategies are never given different effective
`signal_date` or `return_end_date` boundaries within the same window.

## Diagnosing the four hypotheses

The evaluation reports measurements; it does not automatically declare a
causal winner. Interpretation is based on fixed, predeclared contrasts:

- **Zero-yield cash effect:** compare Regime V1 BIL-proxy residual cash with
  Regime V1 zero-yield residual cash at the same cost rate.
- **Transaction-cost effect:** compare each strategy across 0, 2, 5, and 10
  bps while also reviewing turnover and exposure-change count.
- **Turnover/whipsaw effect:** review exposure changes, annualized turnover,
  the existing regime transition/whipsaw diagnostics, and difficult
  historical windows. No smoothing rule is added.
- **Exposure-mapping effect:** compare zero-cost Regime V1 with SPY
  buy-and-hold and the binary 200-session trend benchmark, alongside average
  exposure and exposure-bucket time. This shows association with lower market
  participation; it does not prove an alternative mapping is better.

No threshold, SMA length, cost rate, cash proxy, historical window, or
exposure value is selected after viewing performance.

The required four comparisons do not fully identify the causal effect of the
exposure mapping separately from the timing of Regime V1 signals. They can
show how much return coincides with reduced SPY participation, but proving a
mapping-specific effect would require a separately approved, predeclared
counterfactual mapping study using the same signals. V1.1 will not invent that
extra comparison after seeing results.

## Error handling

Evaluation fails closed with fixed, sanitized errors when:

- SPY does not provide enough history for unchanged Regime V1 warm-up;
- BIL has no usable overlap with the eligible SPY period;
- SPY or BIL has a duplicate date in the active boundary;
- an active-period adjusted close is missing, malformed, non-finite, or
  non-positive;
- BIL is missing an internal exact SPY-aligned date after common start;
- strategies would otherwise receive different `(signal_date,
  return_end_date)` interval pairs; or
- numeric configuration such as capital or cost basis points is invalid.

The evaluator never guesses, forward-fills, silently drops an internal date,
or replaces a BIL return with zero. Errors do not include raw provider
responses, secrets, `.env` values, account data, or broker errors.

## Testing strategy

Development will use deterministic synthetic fixtures and mocked inputs. No
test reads `.env`, calls a market-data service, imports broker execution, or
connects to TWS.

Required tests include:

### Alignment and point-in-time integrity

- exact SPY/BIL canonical-date alignment;
- BIL starting later truncates all four strategies to one common start;
- all strategy and cost results expose identical ordered `(signal_date,
  return_end_date)` interval pairs;
- an internal missing BIL date fails rather than being intersected away;
- duplicate, non-finite, non-positive, and malformed active-period BIL data
  fails safely;
- appending a valid future BIL observation cannot alter earlier results;
- appending a future BIL observation with a valid date but malformed,
  missing, NaN, infinite, zero, or negative adjusted close cannot alter
  results ending before that date;
- equivalent future SPY contamination tests at the V1.1 boundary;
- missing or unparseable observation dates fail safely because their temporal
  position cannot be established; and
- signal on `T` is applied exactly once to return `T -> T+1`, never to return
  ending at `T`.
- every interval record exposes `signal_date` and `return_end_date`, with no
  generic date from which consumers could infer the wrong side of the
  interval;
- initial capital is dated at `D0` before opening cost, the `D0` signal and
  opening cost belong to `D0`, and the first ending value is dated `D1`; and
- consecutive records satisfy `previous.return_end_date ==
  current.signal_date` with no skipped or duplicated return interval.

### Strategy and cash mechanics

- SPY buy-and-hold remains 100% exposed;
- the 200-session benchmark uses only prices through `T`, treats equality as
  risk-on, and lags by one return interval;
- unchanged Regime V1 exposures are used without remapping;
- zero-yield residual cash contributes no return;
- BIL residual cash uses the exact same interval and only the uninvested
  weight;
- no extra BIL commission leg is charged; and
- BIL returns do not affect fully invested sessions.

### Costs, turnover, and metrics

- exact cost arithmetic at 0, 2, 5, and 10 bps;
- the opening exposure is costed from zero and unchanged exposures do not
  create extra costs;
- exposure-change count and annualized turnover match hand-calculated
  fixtures;
- CAGR, maximum drawdown, population annualized volatility, zero-hurdle
  Sharpe, Sortino, and Calmar match deterministic fixtures;
- zero-denominator ratios return `None`;
- average exposure and exposure-bucket percentages match fixed sequences and
  sum correctly; and
- changing only the cost rate never changes signal dates or target exposure.

### Historical windows and isolation

- fixed calendar boundaries select only complete intervals within each
  window;
- each strategy has identical effective signal/start and return-end dates in
  a window;
- normalized starting value is exactly 100 before cost/return at the first
  included `signal_date`;
- the first normalized ending value is dated at the first included
  `return_end_date`;
- window results use continuous prior exposure and do not add a synthetic
  boundary trade;
- unavailable windows report no invented values; and
- source-level safety checks prove V1.1 does not import broker/order modules,
  access `.env`, call TWS, or expose an execution method.

The full repository test suite, bytecode compilation, dependency consistency,
and Git diff checks remain required before any implementation PR is ready.

## Documentation changes during implementation

Implementation will update `docs/MARKET_REGIME_V1.md` or add a focused
evaluation methodology document containing:

- the four strategy definitions;
- the BIL cash-return-proxy disclaimer;
- common-date and point-in-time rules;
- cost and turnover formulas;
- exact metric definitions and the zero-hurdle ratio assumption;
- historical-window rebasing semantics;
- the four predeclared diagnostic contrasts; and
- the limitations of target-weight and adjusted-close research modeling.

`docs/ROADMAP.md` may receive one narrowly scoped Evaluation V1.1 item. It
must not suggest that the regime methodology or trading system changed.

## Safety and integrity invariants

1. Market Regime V1 scoring, thresholds, confidence, and exposure mapping are
   unchanged.
2. A signal produced using data through `T` is first applied to `T -> T+1`.
3. No SPY, BIL, or QQQ information dated after `T` enters the signal for `T`.
4. Future valid-dated malformed price content cannot mutate an earlier
   bounded result.
5. Every strategy and cost scenario uses the same common return intervals.
6. BIL is described only as a residual-cash return proxy.
7. Costs are charged once on SPY target-exposure changes; no BIL leg is added.
8. Historical periods and cost rates are sensitivity slices, not tuning data.
9. Results are deterministic for identical inputs and configuration.
10. No implementation dependency reaches broker, IBKR, orders, `.env`, TWS,
    paper trading, or live trading.

## Self-review

### Look-ahead risk

The design makes signal and return dates explicit: data through `T` produces
an exposure used only for `T -> T+1`. Future valid-dated malformed SPY/BIL
content is outside an earlier bounded evaluation. Forward returns are never
passed into the regime classifier or trend signal.

### Date alignment

All strategies share an exposed common date sequence. BIL may truncate the
outer start/end but cannot create internal intersection-based date dropping.
Exact canonical dates, not sequence positions, define both SPY and BIL
returns.

### BIL assumptions

BIL is explicitly a cash return proxy, not an executed asset or a risk-free
rate. Only residual weight receives its return, and no extra commission leg
is modeled. The design discloses that actual cash may earn a different return.

### Cost double-counting

Each interval has one SPY exposure-change charge calculated before that
interval's return. No cost is embedded in the adjusted-close return and no
BIL cost is added. Continuous window slices reuse those already modeled costs
and do not create boundary trades.

### Metric ambiguity

Every requested metric has a formula, annualization convention, zero-hurdle
assumption, and defined behavior for insufficient or zero-denominator data.
Exposure percentages use return intervals, not equity-curve endpoints.

### Parameter optimization

The design fixes strategies, cost rates, dates, windows, and diagnostic
contrasts before results exist. It adds no selector for the best rate,
threshold, SMA length, exposure mapping, or historical period.

## Acceptance criteria for a future implementation

Evaluation V1.1 will be ready for implementation review when:

1. unchanged Market Regime V1 outputs feed both regime comparison variants;
2. all four strategies and four costs use exactly identical dates;
3. BIL common-start truncation and active-period failure rules are enforced;
4. no future SPY or BIL value can alter an earlier bounded result;
5. all requested metrics and windows follow the definitions above;
6. deterministic synthetic tests cover alignment, lag, costs, turnover,
   ratios, and window slicing;
7. broker/order source-safety tests remain green; and
8. the complete repository test suite passes without accessing secrets or
   external services.
