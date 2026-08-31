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

## Market Regime Stabilization & Re-entry V1.2

V1.2 is a provider-independent research overlay downstream of the unchanged
Market Regime V1 classifier. It tests fast de-risking with stateful confirmed
re-entry; it does not alter V1 trend, momentum, drawdown, volatility, weights,
`45 / 15 / -20` thresholds, regime definitions, confidence/QQQ behavior, or
the `100% / 70% / 30% / 0%` maximum-long-exposure mapping. The overlay reads
only V1 score, regime, and cap, never exceeds that cap, de-risks immediately,
and can re-enter by at most one exposure level per signal session. The study
uses SPY and BIL only; QQQ does not control V1.2 exposure or selection.

### Frozen candidates and periods

The candidate grid is fixed before empirical selection:

| Margin | Confirmation sessions |
|---:|---|
| 0 | 1, 2, 3, 5 |
| 5 | 1, 2, 3, 5 |
| 10 | 1, 2, 3, 5 |

These are exactly 12 candidates: every pair in
`{0, 5, 10} x {1, 2, 3, 5}`. No new margin, confirmation length, hold rule,
cooldown, indicator, threshold, or exposure level may be added after results.

The fixed research periods are:

| Stage | Complete interval window |
|---|---|
| Development | 2007-10-01 through 2014-12-31 |
| Validation | 2015-01-01 through 2020-12-31 |
| Combined selection | 2007-10-01 through 2020-12-31 |
| Locked evaluation | 2021-01-01 through the latest complete common SPY/BIL interval |

Development and Validation are one continuous state and portfolio path; the
state is also reconstructed continuously into the locked boundary. The locked
period is not pristine, blind, or fully unseen because portions were viewed in
earlier V1/V1.1 diagnostics. The fixed descriptive windows remain
2007-10-01..2009-06-30, calendar 2020, calendar 2022, and
2023-01-01..2025-12-31.

### Baseline, gates, and deterministic selection

Every primary comparison uses the unchanged Regime V1 with the BIL
residual-cash proxy at 5 bps on identical SPY/BIL intervals. Selection
requires every candidate gate to pass:

- Development and Validation maximum drawdown are each no worse than -20%;
- Combined CAGR is strictly above the matching baseline;
- Development and Validation CAGR each trail baseline by no more than
  0.50 percentage point;
- Combined annualized turnover is at least 15% lower than baseline; and
- Combined whipsaw-pair count is at least 20% lower than baseline.

An undefined reduction denominator is `NOT_EVALUABLE` and cannot pass. If no
candidate qualifies, the valid selection outcome is
`NO_QUALIFIED_CANDIDATE`, and locked data must remain unopened.

Qualified candidates are ranked first by highest Combined CAGR. Candidates
within 0.05 percentage point of the top CAGR are tied on return, then ordered
by lower Combined whipsaw count, better Combined maximum drawdown, smaller
confirmation length, and smaller margin. At most one candidate is frozen;
2021+ data cannot select or replace it.

Locked research promotion requires maximum drawdown no worse than -20%, CAGR
at least 0.25 percentage point above baseline, annualized turnover at least
15% lower, and whipsaw-pair count at least 20% lower. Any failed or
not-evaluable gate returns `NO_V1_2_PROMOTION`; it does not permit retuning.
Even a `PROMOTE_V1_2_RESEARCH` result would establish only a preferred
research baseline.

### Separate manual authorization gates

Automated synthetic verification does not select an empirical winner. Manual
Stage 1 requires separate authorization and may fetch only the SPY warm-up and
SPY/BIL data needed through 2020-12-31. It runs candidate selection only,
reports all 12 candidates and gates, and stops with either one reviewable
frozen candidate or `NO_QUALIFIED_CANDIDATE`.

Manual Stage 2 requires a second, separate authorization after a Stage 1
candidate is reviewed and frozen. It evaluates only that candidate from
2021-01-01 through the latest complete common interval, reports all locked
gates, and may then run only the fixed cost and window diagnostics without
retuning. Before either manual run, provider coverage and freshness must be rechecked;
an earlier validation does not establish current freshness.

### Manual Tiingo Stage 1 outcome

Manual Tiingo Stage 1 completed on 2026-08-29 under the fixed protocol. The
sanitized source coverage was:

- SPY: 2006-09-01 through 2020-12-31, 3,608 rows;
- BIL: 2007-10-01 through 2020-12-31, 3,338 rows; and
- 3,337 common evaluation intervals from 2007-10-01 through 2020-12-31.

No 2021+ market data was fetched or inspected during Stage 1.

The primary baseline was unchanged Regime V1 with the BIL residual-cash proxy
at 5 bps. Over the combined 2007-10-01 through 2020-12-31 selection period it
reported 7.14% CAGR, -17.13% maximum drawdown, 693.88% annualized turnover, 253
schedule exposure changes, 84 whipsaws, a 33.20% whipsaw rate, and 75.84%
average SPY exposure.

The `(margin=0, confirmation_sessions=1)` candidate raised combined CAGR to
7.37% while remaining within the drawdown gate, but reduced turnover by only
6.14% and whipsaws by only 1.19%. It therefore failed the predeclared 15%
turnover-reduction and 20% whipsaw-reduction gates. Candidates with longer
confirmation periods materially reduced turnover and whipsaw, but failed one
or more frozen return gates.

The Stage 1 result is **`NO_QUALIFIED_CANDIDATE`**. Simple score-margin plus
fixed-session confirmation demonstrated a trade-off: configurations that
materially reduced churn also reduced return participation too much under the
predeclared protocol. No V1.2 winner was frozen, V1.2 is not promoted, and
Manual Stage 2 was not opened. The result was accepted without after-the-fact
parameter retuning.

V1.2 has no Streamlit, broker, TWS/IBKR, order, paper-trading, or live-trading
integration. Neither candidate selection nor research promotion creates an
execution path or authorizes an order.

## Market Regime V1.3 — Recovery-episode re-entry structure study

V1.3 infrastructure is implemented and synthetically verified. Manual Stage 1
completed with no qualified candidate; the study is closed without Stage 2
or promotion. It is a provider-independent, downstream research overlay, not
a classifier, optimizer, execution system, or promotion claim.
The V1 classifier, score construction, `45 / 15 / -20`
thresholds, regimes, confidence and QQQ behavior, and the
`100% / 70% / 30% / 0%` maximum-long-exposure mapping remain unchanged. V1.3
accepts only the V1 score, regime, maximum-long-exposure cap, and its own prior
state; it has no QQQ input.

The fixed candidate structures, in conservative order, are
`DEEP_RECOVERY`, `DEFENSIVE_RECOVERY`, and `BROAD_BULL_CATCH_UP`. A recovery
episode opens on an immediate V1 de-risking session, retaining the overlay's
origin exposure and the minimum V1 cap seen during the episode. It closes only
when the overlay regains that original exposure. A session that de-risks never
re-enters on the same day. Normal recovery advances one allowed exposure level
at a time (`0% -> 30% -> 70% -> 100%`); an eligible fast action advances at
most two levels (`0% -> 70%`, `30% -> 100%`, or `70% -> 100%`), always capped
by the unchanged V1 permission. Deep recovery requires an episode minimum of
`0%`; defensive recovery requires at most `30%`; broad catch-up permits any
active episode. All fast actions additionally require BULL, a finite score of
at least 45, and a V1 cap of 100%.

Selection retains the unchanged V1 + BIL residual-cash-proxy baseline, common
SPY/BIL intervals, 5-bps SPY exposure-change cost, continuous state and
portfolio accounting, and the frozen Development, Validation, Combined, and
locked gates. The seven selection gates are: Development and Validation
maximum drawdown each at least -20%; Combined CAGR strictly above baseline;
Development and Validation CAGR each no more than 0.005 below baseline;
Combined annualized turnover no more than 85% of baseline; and Combined
whipsaw pairs no more than 80% of baseline. An undefined or nonpositive
reduction denominator is `NOT_EVALUABLE` and cannot qualify. Qualifiers are
ranked by Combined CAGR; those within 0.0005 of the highest CAGR are ordered
by fewer whipsaws, better maximum drawdown, lower annualized turnover, then
the conservative fixed structure order. Remaining qualifiers sort by
descending CAGR with those same tie-breaks.

Locked evaluation accepts one externally reviewed frozen candidate, never a
selection search. Its four gates are maximum drawdown at least -20%, CAGR at
least baseline plus 0.0025, annualized turnover no more than 85% of baseline,
and whipsaw pairs no more than 80% of baseline; non-evaluable reduction gates
cannot pass. The locked CAGR gate compares `Decimal(str(actual))` with the
decimal-string baseline-plus-`0.0025` floor; the float field remains
display-only, so no tolerance, constant, or gate changed. BIL represents only
residual-cash return: there are no BIL trades, commission leg, execution
claim, or risk-free-rate substitution. A signal target is costed on its signal
date and applied to the following signal-date-to-return-end-date interval; no
same-session return is attributed.

Diagnostics retain the V1.2 schedule-change and non-overlapping whipsaw-pair
definition: the first in-period target is not a change, and a pair is an
opposite-direction change that returns to or crosses the pre-opening target
within five subsequent signal sessions. Whipsaw rate is pairs divided by
schedule changes, or unavailable when there are none. V1.3 additionally
reports overlapping recovery episodes (including carry-in episodes),
completed/incomplete counts, and a completed episode duration equal to closing
signal index minus opening signal index. Fast activation count includes actual
`FAST_RE_ENTRY` transitions; its rate is activations divided by overlapping
episodes (unavailable with no episodes and not a probability). Two-level fast
jumps and ordinary one-level re-entries are reported separately, along with
sessions below the V1 cap. For each 30%/70%/100% boundary, re-entry lag starts
on the first consecutive signal with V1 permission at that boundary and prior
overlay below it, resets if permission falls, and records its inclusive session
count when crossed. No later state completes or deepens an earlier diagnostic.

### Manual Stage 1 closure — 2026-08-30

Manual Stage 1 completed on 2026-08-30 under separate authorization, using
implementation HEAD `c6652b0e0fb8685bdabeba3e1aecc744149e31b1`. Exactly one
official selection run evaluated the three frozen candidates, with initial
capital USD 100,000 and the unchanged Market Regime V1 + BIL residual-cash
proxy + 5 bps qualification baseline. No QQQ was requested.

| Source | Authorized and returned date range | Rows |
|---|---|---:|
| SPY, including V1 warm-up | 2006-09-01 through 2020-12-31 | 3,608 |
| BIL | 2007-10-01 through 2020-12-31 | 3,338 |

The common evaluation contains 3,337 complete intervals, from
`2007-10-01 -> 2007-10-02` through `2020-12-30 -> 2020-12-31`. All returned
dates were on or before 2020-12-31. This establishes the authorized historical
coverage, not present-day provider freshness or historical-vintage certification.

Development is 2007-10-01 through 2014-12-31; Validation is 2015-01-01 through
2020-12-31; Combined covers both continuously. Turnover below is annualized
multiples. Costs are USD totals from the continuous USD 100,000 portfolio
path, not the internally rebased-to-100 period metric amounts. Displayed
rounding did not determine gates; the unrounded implementation results did.

| Combined V1 baseline metric | Result |
|---|---:|
| CAGR | 7.1428% |
| Maximum drawdown | -17.1298% |
| Annualized turnover | 6.938850x |
| Schedule exposure changes | 253 |
| Whipsaw pairs | 84 |
| Whipsaw rate | 33.2016% |
| Average SPY exposure | 75.8376% |
| Transaction cost | $6,828.65 |

| Candidate metric | DEEP_RECOVERY | DEFENSIVE_RECOVERY | BROAD_BULL_CATCH_UP |
|---|---:|---:|---:|
| Development CAGR | 7.2781% | 7.3400% | 7.3400% |
| Development maximum drawdown | -17.1298% | -17.1298% | -17.1298% |
| Validation CAGR | 7.5251% | 7.5294% | 7.5294% |
| Validation maximum drawdown | -13.1482% | -13.1482% | -13.1482% |
| Combined CAGR | 7.3824% | 7.4182% | 7.4182% |
| Combined maximum drawdown | -17.1298% | -17.1298% | -17.1298% |
| Combined annualized turnover | 6.618489x | 6.645430x | 6.645430x |
| Turnover reduction vs baseline | 4.6169% | 4.2286% | 4.2286% |
| Combined schedule exposure changes | 256 | 252 | 252 |
| Combined whipsaw pairs | 83 | 83 | 83 |
| Whipsaw reduction vs baseline | 1.1905% | 1.1905% | 1.1905% |
| Combined whipsaw rate | 32.4219% | 32.9365% | 32.9365% |
| Combined average SPY exposure | 75.7357% | 75.7896% | 75.7896% |
| Combined transaction cost | $6,585.26 | $6,639.39 | $6,639.39 |

| Frozen selection gate | DEEP_RECOVERY | DEFENSIVE_RECOVERY | BROAD_BULL_CATCH_UP |
|---|---|---|---|
| Development max DD >= -20% | PASS | PASS | PASS |
| Validation max DD >= -20% | PASS | PASS | PASS |
| Combined CAGR > baseline | PASS | PASS | PASS |
| Development CAGR >= baseline - 0.50pp | PASS | PASS | PASS |
| Validation CAGR >= baseline - 0.50pp | PASS | PASS | PASS |
| Combined turnover <= 85% of baseline | FAIL | FAIL | FAIL |
| Combined whipsaws <= 80% of baseline | FAIL | FAIL | FAIL |
| Overall qualification | NOT QUALIFIED | NOT QUALIFIED | NOT QUALIFIED |

The exact turnover qualification ceiling was `5.8980222521628525x`; the
whipsaw ceiling was `67.2` pairs. No close misses were reinterpreted.
Official selection status: `NO_QUALIFIED_V1_3_CANDIDATE`; `winner = None`;
qualifier ranking `()`. There is no empirical winner and no V1.3 promotion.
V1.3 research promotion is rejected; Stage 2 closed without running because
no candidate qualified.

Recovery-episode fast re-entry improved realized return participation relative
to the V1 baseline, as measured by CAGR, but did not materially reduce turnover
or whipsaw under the frozen requirements. DEEP_RECOVERY reached 7.3824%
Combined CAGR with only 4.6169% turnover reduction and 1.1905% whipsaw
reduction. DEFENSIVE_RECOVERY and BROAD_BULL_CATCH_UP reached 7.4182% CAGR
with only 4.2286% turnover reduction and the same 1.1905% whipsaw reduction.
All three therefore failed both churn gates. The Stage 1 evidence suggests
that re-entry speed alone is not the main source of churn; it does not prove
that any future mechanism will work.

BROAD_BULL_CATCH_UP produced the same portfolio performance path as
DEFENSIVE_RECOVERY despite more fast-transition classifications. Their actual
two-level fast re-entry count was identical (11), so broader eligibility added
classifications without materially changing realized exposure behavior.

The result is accepted without after-the-fact retuning. No real 2021+ V1.3
data was fetched or inspected. V1.3 implementation remains unchanged by this
documentation closure, as do MarketRegimeEngine and V1.2. No raw market data,
provider payloads, console dumps, or secrets are committed. There is no
broker, TWS/IBKR, order, paper-trading, or live-trading implication.
Any successor research requires a new separately approved design.

## Market Regime V1.4 - Selective Churn Diagnostics

V1.4 D1 is diagnosis-only infrastructure for understanding short-horizon
churn in the frozen Market Regime V1 schedule. It is a downstream research
overlay, not a new classifier, optimizer, execution system, or promotion
claim. The frozen V1 boundary remains unchanged: `MarketRegimeEngine`, score
construction, `45 / 15 / -20` thresholds, regime definitions, confidence and
QQQ behavior, and the `100% / 70% / 30% / 0%` maximum-long-exposure mapping.
D1 consumes only the V1 regime, raw score, cap, and transition history.

### D1 protocol and fixed constants

D1 uses the fixed Discovery Set from `2007-10-01` through `2014-12-31`.
The fixed protocol uses initial capital USD 100,000, a 5 bps SPY
exposure-change cost, and the existing V1 plus BIL residual-cash accounting.
The later authorized SPY warm-up request may begin on `2006-09-01`; later
real D1 authorization would allow SPY through `2014-12-31` and BIL from
`2007-10-01` through `2014-12-31`. The inherited whipsaw window is five signal
sessions. The diagnostic retry and cluster windows are each ten signal
sessions; they are descriptive windows, not future trading parameters.

Manual D1 NOT RUN. No real 2015+ or 2021+ V1.4 result exists, and there is no
empirical mechanism conclusion. This implementation makes no candidate,
winner, or promotion claim.

### D1 diagnostic definitions

Each actual change in the V1 target schedule is one immutable exposure-change
event. Allowed exposures are exactly `0.0`, `0.3`, `0.7`, and `1.0`; a
multi-level move remains one event rather than fictional intermediate trades.
The event records its direction, primary boundary, every crossed boundary in
movement order, and the V1 regime, score, and cap. The first in-period target
is context and is not counted as a change.

A whipsaw pair is a non-overlapping opposite-direction change that returns to
or crosses the opener's pre-change exposure within the next five signal
sessions. A closer cannot close more than one pair. An UP opener is a failed
re-entry when its closer returns to or below the pre-change exposure; a DOWN
opener is a failed de-risk when its closer returns to or above it. These are
structural schedule classifications and do not use subsequent returns.

After a failed re-entry pair, the first later upward change crossing the same
primary boundary within ten signal sessions is one same-boundary retry. A
failed pair creates at most one retry. A retry fails again only when it opens
another frozen-definition failed re-entry pair; otherwise it is a retry
success.

Churn clusters are formed only from extracted non-overlapping pairs. Adjacent
pairs join when their opener indices are at most ten signal sessions apart and
share a crossed boundary. Cluster schedule-change counts include each actual
event from the first opener through the final closer, inclusive. Tied
dominant boundaries are all retained in deterministic boundary order.

Boundary-incidence shares are explicitly non-additive: one pair or cluster
may contain more than one boundary, so crossed-boundary and dominant-boundary
shares use their respective pair and cluster denominators and may sum above
one. Structural classification and return attribution remain separate. Pair
return values and transaction-cost attribution are descriptive outputs only;
returns never enter pair extraction, retry classification, cluster formation,
or boundary attribution.

The pure analysis API may date-filter future-dated rows before reading their
price content. That is an API future-row safety property and does not
authorize post-2014 provider data. The implementation has no provider,
configuration, environment, broker, order, TWS, or UI integration.

### Predeclared future gates

V1 candidate validation is a future, single run on `2015-01-01` through
`2020-12-31`, only after the D1 Mechanism Conclusion is reviewed and at most
three parameter-light candidate structures are explicitly frozen. Each
candidate must pass maximum drawdown at least -20%, CAGR at least baseline
CAGR minus 0.0025, annualized turnover no more than 85% of baseline, and
whipsaw pairs no more than 80% of baseline. Undefined reduction denominators
are `NOT_EVALUABLE` and cannot qualify.

L1 locked evaluation is a separately authorized future run from
`2021-01-01` through the latest complete common interval. It remains closed
until one Validation winner is externally reviewed and frozen. Its gates are
maximum drawdown at least -20%, CAGR at least locked-baseline CAGR plus
0.0025, annualized turnover no more than 85% of baseline, and whipsaw pairs
no more than 80% of baseline. No retuning is allowed after locked results.
Neither future gate has been run for V1.4, and neither permits execution.

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
