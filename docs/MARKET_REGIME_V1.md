# Market Regime Engine v1

## Purpose and safety boundary

Market Regime Engine v1 is a deterministic, end-of-day research aid. It classifies the broad U.S. market from SPY and maps that classification to a maximum **long** exposure and a research permission. It is not investment advice, a forecast, or an order system.

The engine has no broker dependency and never auto-trades, auto-sizes, liquidates, shorts, previews, submits, cancels, or otherwise manages orders. The displayed exposure is a research cap, not a trading instruction.

## Data and date rules

All indicators use provider-supplied **adjusted closes**. `PriceBar.trading_date` means the U.S. exchange session date supplied by the end-of-day provider; the model has no intraday timestamp. A result for session `T` is available only after that session's close.

SPY is mandatory. Before scoring, the engine filters out all bars after the requested `as_of` date, validates the SPY symbol, sorts by session date, rejects duplicate dates and non-positive/non-finite adjusted closes, and rejects a gap longer than ten calendar days inside the trailing required window. It requires at least 252 valid SPY sessions. For a current dashboard request, the most recent SPY session may be no more than four calendar days older than the requested date; this allowance covers normal weekends and long holiday weekends. Invalid, insufficient, or stale SPY data fails safely rather than being substituted or guessed.

QQQ is optional confirmation data. It needs 201 valid sessions and the same date and freshness checks. When it is missing, invalid, stale, or too short, the SPY result still stands, QQQ is `UNAVAILABLE`, and a fixed warning is shown. QQQ never adds score points or changes the selected regime.

VIX is explicitly deferred: there is not yet a reliable, source-independent VIX contract or confirmed symbol semantics. Market breadth is also deferred: the repository has no point-in-time breadth or constituent-history source, and today's index membership must not be projected backwards. Realized SPY volatility is the only volatility measure in v1.

## Score methodology

The total is the integer sum of four components, bounded from -100 to 100. Equality in a comparison contributes zero.

### Primary trend (-40 to +40)

| Evidence | Positive | Equal | Negative |
|---|---:|---:|---:|
| SPY close versus 50-session SMA | +8 | 0 | -8 |
| SPY close versus 200-session SMA | +12 | 0 | -12 |
| 50-session SMA versus 200-session SMA | +12 | 0 | -12 |
| 200-session SMA slope versus zero | +8 | 0 | -8 |

The 200-session SMA slope is the percentage change between the current 200-session SMA and the 200-session SMA ending 20 sessions earlier.

### Momentum (-20 to +20)

| Evidence | Positive | Zero | Negative |
|---|---:|---:|---:|
| 20-session adjusted-close return | +8 | 0 | -8 |
| 60-session adjusted-close return | +12 | 0 | -12 |

### Drawdown (-25 to +25)

Drawdown is `latest adjusted close / highest adjusted close in the last 252 sessions - 1`.

| Drawdown band | Score |
|---|---:|
| `>= -5%` | +25 |
| `>= -10%` and `< -5%` | +10 |
| `>= -15%` and `< -10%` | -5 |
| `>= -20%` and `< -15%` | -15 |
| `< -20%` | -25 |

### Realized volatility (-15 to +15)

Volatility is the population standard deviation of the latest 20 daily adjusted-close returns, annualized by `sqrt(252)`.

| Annualized volatility band | Score |
|---|---:|
| `<= 15%` | +15 |
| `> 15%` and `<= 20%` | +8 |
| `> 20%` and `<= 30%` | 0 |
| `> 30%` and `<= 40%` | -8 |
| `> 40%` | -15 |

## Regimes and research exposure caps

All score boundaries are inclusive as shown.

| Regime | Score range | Maximum long exposure | Permission |
|---|---:|---:|---|
| `BULL` | 45 through 100 | 100% | `NORMAL` |
| `CAUTIOUS_BULL` | 15 through 44 | 70% | `REDUCED` |
| `RISK_OFF` | -20 through 14 | 30% | `DEFENSIVE` |
| `BEAR` | -100 through -21 | 0% | `BLOCKED` |

`BEAR` is a capital-preservation state, not a short signal. None of these labels permit automatic strategy sizing or blocking.

## QQQ and confidence

QQQ is `CONFIRMS_POSITIVE` when it is above its 200-session SMA and its 60-session return is positive. It is `CONFIRMS_NEGATIVE` when it is below its 200-session SMA and its 60-session return is negative. Equal or conflicting signals are `MIXED`. Positive QQQ agrees with the two bull regimes; negative QQQ agrees with `RISK_OFF` and `BEAR`. The opposite direction contradicts the SPY regime.

Confidence is a label, not a percentage. It records:

1. boundary distance: the minimum absolute distance from the total score to -20, 15, or 45;
2. component agreement: the number of component scores with the same sign as the non-zero total score; and
3. QQQ status.

| Confidence | Rule |
|---|---|
| `HIGH` | Boundary distance >= 10, at least 3 agreeing components, and QQQ confirms the direction. |
| `MEDIUM` | Boundary distance >= 5, at least 2 agreeing components, and QQQ does not contradict. |
| `LOW` | Every other case. |

Missing or mixed QQQ can support at most `MEDIUM`; contradictory QQQ produces `LOW`. A total score of exactly zero has zero agreeing components and `LOW` confidence.

## Point-in-time historical evaluation

The evaluator classifies every eligible SPY session `T` using only bars dated on or before `T`; it applies the same cutoff independently even when a complete history is supplied. QQQ is likewise restricted to data available on or before `T`. Future prices cannot influence a historical classification.

20- and 60-session forward returns are created only after classification as evaluation outputs. They are never model inputs. In the research comparison, the result produced on `T` applies its maximum long exposure to the SPY return from `T` to the next trading session, not to the return ending on `T`.

The documented analysis windows are:

| Period | Window |
|---|---|
| 2008 financial crisis | 2007-10-01 through 2009-06-30 |
| 2020 COVID crash and recovery | 2020-01-01 through 2020-12-31 |
| 2022 bear market | 2022-01-01 through 2022-12-31 |
| 2023-2025 recovery and bull period | 2023-01-01 through 2025-12-31 |

The evaluator reports regime session counts and percentages, complete-horizon 20/60-session forward-return means, contiguous episode count and durations, transitions and annualized transitions, short reversal (whipsaw) count/rate, and worst within-episode drawdown. It also compares frictionless SPY buy-and-hold with a research-only regime-capped curve. The capped curve starts with USD 100,000 virtual capital, keeps uninvested capital in zero-yield cash, uses the prior session's cap for the next-session return, and applies a default five-basis-point transaction cost to each absolute exposure change. It is a validation comparison, not a tradable strategy or sizing system.

## Market Regime Evaluation V1.1

Evaluation V1.1 is a deterministic research comparison layered on the
unchanged Market Regime V1 engine. It does not alter scoring, thresholds,
confidence, or the 100% / 70% / 30% / 0% maximum-long-exposure mapping. It
compares exactly four strategies:

1. SPY buy-and-hold at 100% exposure;
2. a simple 200-session trend benchmark at 100% SPY when the prior-session
   adjusted close is at or above its trailing 200-session SMA, otherwise 0%;
3. Regime V1 with zero-yield residual cash; and
4. Regime V1 with a BIL-return residual cash proxy.

All four strategies use one common SPY/BIL interval sequence. SPY supplies the
eligible signal and return dates after the 252-session warm-up. If BIL starts
later, every strategy is truncated to the same later common start; earlier BIL
returns are never filled with zero. SPY and BIL must both contain valid,
finite, positive provider-supplied adjusted closes for every active SPY date.
Missing or duplicate active-period BIL dates fail safely rather than being
intersected away or forward-filled.

### Explicit interval timeline

For each interval, the two boundaries are unambiguous:

1. Initial capital exists at D0 before modeled cost or return.
2. The signal produced using data through D0 (`signal_date`) determines the
   target SPY exposure.
3. Any opening or subsequent SPY exposure-change cost is charged at D0.
4. The target exposure applies only to the D0-to-D1 return.
5. The resulting ending portfolio value is dated D1 (`return_end_date`).
6. D1 becomes the next interval's starting value and the convention repeats.

No observation after `signal_date` enters that interval's signal. In
particular, a signal produced on T never receives the return ending on T.

### BIL cash-return proxy and costs

BIL is a return proxy for the uninvested portion of the portfolio. This is not a claim that the strategy trades BIL.
It is not treated as a risk-free-rate series and does not create a broker or
execution path. The zero-yield version assigns a zero return to residual cash;
the BIL version uses:

`gross return = SPY exposure * SPY return + (1 - SPY exposure) * BIL return`

Transaction-cost sensitivity is fixed at 0, 2, 5, and 10 basis points. For
each interval:

`cost = starting value * abs(target SPY exposure - prior SPY exposure) * bps / 10,000`

The opening allocation is measured from zero exposure. Cost is deducted before
the interval return. There is no extra BIL transaction-cost leg because BIL is
only a cash return proxy. These scenarios are sensitivity analysis, not tuned
parameters.

### Deterministic metrics

Metrics use the continuous net portfolio path and these fixed definitions:

- initial capital is the value before the first interval's cost and return;
- final value is the ending value at the final `return_end_date`;
- CAGR is `(final / initial) ** (365.25 / elapsed calendar days) - 1`;
- maximum drawdown is the worst ending-value decline from the running peak,
  with initial capital included as the first peak;
- annualized volatility is the population standard deviation of interval net
  returns multiplied by `sqrt(252)`;
- Sharpe ratio is mean interval net return divided by its population standard
  deviation, multiplied by `sqrt(252)`;
- Sortino ratio is mean interval net return divided by
  `sqrt(mean(min(return, 0) ** 2))`, multiplied by `sqrt(252)`;
- Sharpe and Sortino use a zero daily hurdle. No risk-free-rate series is
  silently substituted;
- Calmar ratio is CAGR divided by the absolute maximum drawdown;
- total transaction cost is the sum of stored interval SPY exposure-change
  costs;
- annualized turnover is total SPY traded notional divided by mean interval
  starting value, then divided by `interval_count / 252`;
- exposure changes count intervals whose absolute SPY exposure change exceeds
  `1e-12`;
- average SPY exposure is the arithmetic mean of interval targets; and
- exposure-bucket percentages are the percentage of intervals at the
  applicable 0%, 30%, 70%, and 100% targets (only applicable buckets are
  reported for buy-and-hold and the trend benchmark).

Undefined ratio denominators produce no ratio rather than an invented value.

### Fixed historical windows and interpretation

The four existing historical windows remain fixed. A window includes only an
interval whose `signal_date` and `return_end_date` both fall inside the window.
The strategy path is not restarted and no boundary trade is invented. For
readability, reported window values are rebased from the first included
pre-cost starting value to 100; stored costs are scaled by the same factor.

The comparison is intended to diagnose four contrasts without optimizing any
parameter:

- buy-and-hold versus the 200-session trend benchmark shows the effect of the
  simple risk-on/risk-off signal;
- Regime V1 zero-yield cash versus its BIL cash proxy shows cash-assumption
  drag;
- 0/2/5/10-basis-point rows show transaction-cost sensitivity associated with
  SPY exposure turnover; and
- Regime V1 versus the benchmarks shows the combined behavior of its signal
  timing and exposure schedule.

The last contrast does not fully isolate the causal effect of the exposure mapping.
The regime signal dates and the 100% / 70% / 30% / 0% targets change together.
The evaluation is descriptive sensitivity research, not parameter
optimization, data snooping, or evidence of future performance.

## Current limitations

Automated tests do **not** read `.env`, use vendor credentials, contact a
market-data provider, or connect to TWS or IB Gateway. An authorized,
sanitized Tiingo validation was completed on 2026-08-27 using SPY, BIL, and
QQQ history through 2026-08-26. That validation established freshness only
for that run; every future run must check its own source coverage and latest
common complete interval before claiming current freshness. No downloaded
market data, raw provider responses, validation console dumps, credentials,
API keys, or `.env` contents are committed.

Thresholds are transparent fixed rules, not optimized forecasts. They do not address intraday moves, data revisions, VIX, breadth, survivorship, or any future performance guarantee.
