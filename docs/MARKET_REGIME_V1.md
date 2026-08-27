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

## Current limitations

Automated work did **not** read `.env`, use vendor credentials, load Tiingo history, contact a market-data provider, connect to TWS or IB Gateway, or run a current-regime calculation. Consequently, no vendor-history result and no current score, confidence, regime, or exposure is claimed here. The historical windows are supported by deterministic synthetic tests only until an authorized manual, secret-backed data run is performed.

Thresholds are transparent fixed rules, not optimized forecasts. They do not address intraday moves, data revisions, VIX, breadth, survivorship, or any future performance guarantee.
