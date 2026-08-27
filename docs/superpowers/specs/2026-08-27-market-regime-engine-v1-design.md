# Market Regime Engine v1 Design

Date: 2026-08-27

## Purpose

Market Regime Engine v1 is a deterministic research and risk-guidance
subsystem. It answers four questions from daily end-of-day market data:

1. What market regime is active?
2. How strong is the evidence for that classification?
3. What maximum long exposure is appropriate for research purposes?
4. Should normal long strategies operate normally, at reduced size,
   defensively, or remain blocked?

The engine does not submit, preview, stage, cancel, replace, or transmit any
order. It does not connect to IBKR. It does not change the PAPER Submit gates
merged in PR #12. Its v1 consumers are the Streamlit dashboard and a dedicated
historical evaluation layer only.

## Design principles

- Use a small transparent score, not machine learning or a black box.
- Make each component independently inspectable and testable.
- Use only observations available on or before the evaluation date.
- Prefer adjusted daily closes for return, trend, drawdown, and volatility
  calculations.
- Fail explicitly on unusable mandatory data; never guess or silently
  substitute values.
- Keep Streamlit and provider construction outside the calculation engine.
- Treat `BEAR` as a capital-preservation state, not a short signal.
- Treat forward returns as evaluation outputs only, never model inputs.

## Approaches considered

### Recommended: weighted deterministic score

Four independently explained components contribute to a bounded score. This
keeps the system understandable while avoiding a single-rule classifier such
as `SPY > SMA200`.

### Rejected for v1: decision tree

A rule tree is easy to read, but its first matching condition can dominate all
other evidence. Small changes around one threshold also create brittle regime
transitions.

### Rejected for v1: statistically normalized score

Rolling percentiles, z-scores, or fitted weights can adapt to changing market
distributions, but they add calibration choices and make historical behavior
harder to reproduce and explain. They may be evaluated after v1 has a stable
baseline.

## Architecture

The dependency direction is:

```text
MarketDataProvider
  -> validated SPY and optional QQQ histories
  -> indicator/component calculation
  -> deterministic regime classifier
  -> immutable RegimeResult
  -> Streamlit dashboard and historical evaluation
```

Proposed repository boundaries:

- `src/private_quant/risk/market_regime.py`
  - provider-independent enums and immutable models;
  - history validation;
  - indicator calculation;
  - component scoring;
  - regime, confidence, exposure, and explanation mapping.
- `src/private_quant/backtest/regime_evaluation.py`
  - point-in-time daily evaluation;
  - regime episodes, transitions, whipsaw, conditional forward-return and
    drawdown statistics;
  - buy-and-hold and research-only regime-capped comparison curves.
- `src/private_quant/app/market_regime.py`
  - local provider construction through existing app configuration;
  - bounded Streamlit caching of raw histories;
  - safe error mapping and dashboard rendering.
- `tests/test_market_regime.py`
  - engine behavior and point-in-time correctness.
- `tests/test_regime_evaluation.py`
  - evaluation-only metrics and next-session exposure application.
- `tests/test_market_regime_app.py`
  - mocked provider loading and Streamlit rendering.

The existing `MarketDataProvider`, `PriceBar`, Tiingo adapter, and
`AppConfiguration` remain the data boundary. No duplicate HTTP client or
market-data abstraction will be added.

## Regime states and risk mapping

The four states are:

| Regime | Score range | Maximum long exposure | Strategy permission |
|---|---:|---:|---|
| `BULL` | `45` through `100` | `100%` | `NORMAL` |
| `CAUTIOUS_BULL` | `15` through `44` | `70%` | `REDUCED` |
| `RISK_OFF` | `-20` through `14` | `30%` | `DEFENSIVE` |
| `BEAR` | `-100` through `-21` | `0%` | `BLOCKED` |

The mappings are research guidance. No consumer may convert them into an
automatic order in v1. The conservative `BEAR` allocation is zero rather than
ten percent because v1 is intended to preserve capital when evidence is
materially hostile. It does not authorize short exposure.

## Mandatory and optional inputs

### SPY

SPY adjusted daily closes are mandatory. They drive every scored component.

### QQQ

QQQ is an optional secondary confirmation series. It does not contribute
points and cannot change the regime. It may raise or lower confidence by
confirming or contradicting SPY's broad direction.

Invalid or insufficient QQQ history is treated as `UNAVAILABLE` with a fixed
warning in the result. It never causes a valid mandatory SPY evaluation to
fail.

QQQ confirmation is:

- `CONFIRMS_POSITIVE` when QQQ is above its 200-session SMA and its 60-session
  return is positive;
- `CONFIRMS_NEGATIVE` when QQQ is below its 200-session SMA and its 60-session
  return is negative;
- `MIXED` when those signals disagree or equal their reference;
- `UNAVAILABLE` when valid optional history is not supplied.

Positive confirmation agrees with `BULL` and `CAUTIOUS_BULL`. Negative
confirmation agrees with `RISK_OFF` and `BEAR`. The opposite direction is a
contradiction.

### VIX

VIX is deferred. The current provider layer supports generic daily symbols,
but the repository has not established reliable VIX coverage, symbol
semantics, or a source-independent volatility-index contract. Realized SPY
volatility is the sole v1 volatility input. A future optional VIX component
must not make the engine unusable when VIX is missing.

### Market breadth

Breadth is deferred to v2. The repository has no point-in-time constituent or
breadth series. Today's index membership must never be projected backward to
create a misleading historical indicator.

## History validation and date semantics

The engine accepts complete sequences of `PriceBar` values and an explicit
`as_of` date. Before calculation it:

1. discards every observation after `as_of`;
2. verifies the mandatory symbol is SPY after normalization;
3. sorts observations by `trading_date`;
4. rejects duplicate trading dates;
5. rejects non-finite, non-positive adjusted closes;
6. rejects an internal calendar gap greater than ten days within the required
   trailing window;
7. requires at least 252 valid SPY trading sessions; and
8. rejects current-dashboard data whose latest trading date is more than four
   calendar days before the requested date.

The four-day dashboard allowance permits ordinary weekends and long holiday
weekends. Historical evaluation sets `as_of` to an actual SPY trading date, so
the latest observation must be that date.

`PriceBar.trading_date` is treated as the U.S. exchange session date supplied
by the EOD provider. The model has no intraday timestamp. A regime for session
`T` is therefore considered available after that session's close. Historical
exposure comparisons apply it no earlier than the next trading session.

Validation failures use typed, fixed-message exceptions:

- `InsufficientRegimeHistoryError`;
- `InvalidRegimeDataError`;
- `StaleRegimeDataError`.

Exceptions must not contain credentials, raw provider payloads, or guessed
replacement values.

## Indicator definitions

All calculations use adjusted closes and only the filtered history ending on
the evaluation session.

- SMA50: arithmetic mean of the latest 50 adjusted closes.
- SMA200: arithmetic mean of the latest 200 adjusted closes.
- SMA200 slope: percentage change between the current SMA200 and the SMA200
  ending 20 trading sessions earlier.
- 20-session return: `latest / close_20_sessions_ago - 1`.
- 60-session return: `latest / close_60_sessions_ago - 1`.
- Drawdown: `latest / max(last_252_adjusted_closes) - 1`.
- Realized volatility: population standard deviation of the latest 20 daily
  adjusted-close returns multiplied by `sqrt(252)`.

The 50/200 windows are established medium- and long-term trend references.
The 20/60 windows represent roughly one and three trading months. The
252-session high represents approximately one trading year. Twenty-session
realized volatility responds more quickly than the long moving average during
market stress.

## Component scoring

The total score is the integer sum of four components and is bounded from
`-100` to `100`.

### Primary trend: `-40` to `40`

| Evidence | Above/positive | Equal | Below/negative |
|---|---:|---:|---:|
| SPY close vs SMA50 | `+8` | `0` | `-8` |
| SPY close vs SMA200 | `+12` | `0` | `-12` |
| SMA50 vs SMA200 | `+12` | `0` | `-12` |
| 20-session SMA200 slope | `+8` | `0` | `-8` |

The long-term price and moving-average relationship receive the largest share
of the total score without becoming the entire classifier.

### Momentum: `-20` to `20`

| Evidence | Positive | Zero | Negative |
|---|---:|---:|---:|
| 20-session return | `+8` | `0` | `-8` |
| 60-session return | `+12` | `0` | `-12` |

The longer momentum window receives more weight to reduce sensitivity to one
short reversal.

### Drawdown/stress: `-25` to `25`

| SPY drawdown from 252-session high | Score |
|---|---:|
| `drawdown >= -5%` | `+25` |
| `-10% <= drawdown < -5%` | `+10` |
| `-15% <= drawdown < -10%` | `-5` |
| `-20% <= drawdown < -15%` | `-15` |
| `drawdown < -20%` | `-25` |

This component responds to sharp losses before slow moving averages fully
turn. The tiers correspond to contained pullback, correction, material
stress, and bear-market-scale drawdown bands.

### Realized volatility: `-15` to `15`

| Annualized 20-session realized volatility | Score |
|---|---:|
| `volatility <= 15%` | `+15` |
| `15% < volatility <= 20%` | `+8` |
| `20% < volatility <= 30%` | `0` |
| `30% < volatility <= 40%` | `-8` |
| `volatility > 40%` | `-15` |

These bands distinguish contained, elevated, and crisis-like realized
volatility without fitting them to particular historical episodes.

Every component exposes its raw inputs, component score, maximum absolute
weight, and a fixed human-readable explanation.

## Confidence

Confidence is categorical: `HIGH`, `MEDIUM`, or `LOW`. It is not presented as
an arbitrary percentage.

The calculation uses three measurable facts:

1. **Boundary distance:** absolute score distance to the nearest regime
   threshold among `-20`, `15`, and `45`.
2. **Component agreement:** number of non-zero components whose sign agrees
   with the total score's sign.
3. **Optional confirmation:** whether valid QQQ evidence confirms,
   contradicts, is mixed, or is unavailable.

Rules:

- `HIGH`: boundary distance is at least 10 points, at least three components
  agree, and QQQ confirms the direction.
- `MEDIUM`: boundary distance is at least 5 points, at least two components
  agree, and QQQ does not contradict the direction.
- `LOW`: every other case, including a boundary distance below 5, one or fewer
  agreeing components, or a QQQ contradiction.

Missing QQQ does not prevent classification, but it caps confidence at
`MEDIUM`. The result exposes boundary distance, agreement count, and QQQ
status so the label is reproducible.

When the total score is exactly zero, component agreement is defined as zero
and confidence is `LOW`; there is no positive or negative total-score
direction to confirm.

## Stable result model

The risk module defines frozen, slotted dataclasses and enums:

- `MarketRegime`: `BULL`, `CAUTIOUS_BULL`, `RISK_OFF`, `BEAR`.
- `RegimeConfidence`: `HIGH`, `MEDIUM`, `LOW`.
- `StrategyPermission`: `NORMAL`, `REDUCED`, `DEFENSIVE`, `BLOCKED`.
- `ConfirmationStatus`: positive, negative, mixed, unavailable.
- `RegimeMetric`: name, value, unit, and reference description.
- `RegimeComponent`: name, score, maximum absolute score, metrics, and
  explanation.
- `RegimeDataQuality`: latest SPY date, requested date, age in calendar days,
  observations used, required observations, validity, QQQ status, and fixed
  warnings.
- `RegimeResult`: evaluation date, regime, total score, confidence, confidence
  evidence, maximum long exposure, strategy permission, components, reasons,
  and data quality.

`maximum_long_exposure` is a ratio from `0.0` to `1.0`. Consumers format it as
a percentage. The engine does not know about Streamlit or IBKR.

## Historical evaluation

The dedicated evaluator accepts SPY history, optional QQQ history, and an
optional engine configuration. It evaluates every eligible SPY trading day by
calling the same classifier with `as_of=T`. The classifier independently
filters future observations, so passing a complete history cannot leak later
prices into day `T`.

### Evaluation outputs

- observation count and percentage of sessions in each regime;
- 20- and 60-session forward adjusted-close returns grouped by regime;
- contiguous regime episode count, mean duration, median duration, and maximum
  duration;
- total transitions and annualized transitions;
- transitions reversed within ten trading sessions and their rate;
- worst peak-to-trough SPY drawdown inside contiguous episodes of each regime;
- a frictionless buy-and-hold SPY comparison; and
- a research-only regime-capped exposure comparison.

Forward returns use prices after `T` only in the evaluator's output stage.
They are never passed into the engine.

### Regime-capped research comparison

The comparison starts with USD 100,000 virtual capital. It applies the maximum
long exposure from the prior trading session to the next session's SPY return,
with the remainder in zero-yield cash. Exposure changes only after a regime
change and incur a configurable default transaction cost of five basis points
on the absolute exposure change.

This is a validation tool, not a strategy integration or order-sizing path.
It exists to measure whether the guidance reduces severe drawdowns without
constantly abandoning healthy bull markets.

Both comparison curves begin on the first session after the first eligible
regime result. Buy-and-hold uses that same starting price. Forward-return
observations without the complete requested future horizon are excluded, and
annualized transition frequency uses 252 trading sessions per year.

### Historical periods

The evaluator and documentation provide explicit analysis windows for:

- 2008 financial crisis when provider history is available;
- 2020 COVID crash and recovery;
- 2022 bear market; and
- subsequent recovery/bull periods.

Thresholds are not optimized to label these periods perfectly. Automated
tests use compact deterministic synthetic fixtures rather than committing a
large or licensed vendor dataset.

Because implementation must not read the real `.env`, automated PR work will
not load Tiingo history or claim current/period-specific live results. The
final PR report will state that the current regime is unavailable unless a
fresh provider result can be obtained without violating that boundary.

## Streamlit dashboard

`src/private_quant/app/market_regime.py` is a standalone page consistent with
the repository's existing app files.

It renders immediately without a provider call. Selecting **Evaluate regime**
loads approximately 550 calendar days of SPY and optional QQQ data through the
existing provider builder. Raw serializable histories are cached in the app
layer for 15 minutes with a bounded entry count; the risk module has no
Streamlit import.

The page displays:

- regime;
- score;
- categorical confidence;
- maximum long exposure;
- normal long-strategy permission;
- component evidence for SPY vs SMA50, SPY vs SMA200, SMA50 vs SMA200, SMA200
  slope, momentum, drawdown, realized volatility, and QQQ confirmation;
- concise plain-English reasons; and
- latest data date, requested date, data age, observation count, and optional
  input warnings.

The page states that output is deterministic research guidance, not certainty
or investment advice. It contains no order, broker, automatic-sizing,
liquidation, or shorting control.

Provider/authentication/rate-limit/network errors map to fixed safe messages.
Raw provider errors and credentials are never rendered.

## Testing strategy

Development follows TDD. Tests cover:

- canonical bull, cautious-bull, risk-off, and bear histories;
- exact component and regime threshold boundaries;
- exact volatility and drawdown band boundaries;
- insufficient history;
- missing mandatory data;
- duplicate dates and excessive internal gaps;
- NaN, infinity, zero, and negative adjusted closes;
- filtering of every observation after `as_of`;
- identical results when arbitrary future observations are appended;
- deterministic repeated results;
- exposure and permission mapping;
- component metrics and explanations;
- confidence boundary distance, component agreement, QQQ confirmation,
  contradiction, and absence;
- forward-return calculations remaining evaluator-only;
- next-session exposure application;
- transition, duration, whipsaw, and episode-drawdown summaries;
- buy-and-hold comparison;
- mocked provider loading and optional QQQ failure;
- dashboard rendering and safe errors; and
- source-safety regression proving the regime modules do not import broker
  order execution or call order methods.

The full repository suite, bytecode compilation, dependency check, and branch
diff check run before PR creation.

## Documentation

The implementation updates:

- `README.md` with Windows PowerShell launch instructions and methodology
  summary;
- `docs/DATA_SOURCES.md` with adjusted-close, date, freshness, and optional
  input semantics;
- `docs/ROADMAP.md` with Market Regime Engine v1 status; and
- a focused `docs/MARKET_REGIME_V1.md` methodology and validation guide.

The documentation distinguishes model inputs from evaluation-only forward
returns and states the current limitations.

## Explicitly out of scope

- machine learning, fitted weights, neural networks, or parameter optimization;
- VIX scoring in v1;
- breadth without a reliable point-in-time source;
- automatic strategy sizing or blocking;
- automatic IBKR PAPER or LIVE submission;
- live trading;
- automatic liquidation;
- automatic shorting;
- changes to `IBKR_PAPER_SUBMIT_ENABLED` or PR #12 safety controls;
- provider replacement or a second market-data HTTP stack; and
- claims of historical or current performance without fresh valid data.

## Success criteria

The work is complete when:

1. the same valid history always produces the same explained result;
2. no observation after the requested date can change that result;
3. all four regimes and risk mappings are reachable and covered by tests;
4. invalid, insufficient, or stale mandatory data fails safely;
5. historical evaluation reports behavior without feeding future returns into
   classification;
6. the dashboard renders the result without depending on broker code;
7. PR #12 broker safety behavior remains unchanged;
8. the complete repository test suite passes; and
9. a reviewed PR targets `main` and remains unmerged.
