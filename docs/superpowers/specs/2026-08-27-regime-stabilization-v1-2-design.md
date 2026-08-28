# Market Regime Stabilization & Re-entry V1.2 Design

**Date:** 2026-08-27
**Status:** Design for review
**Scope:** Deterministic research overlay and anti-overfitting evaluation only

## Purpose

Market Regime Evaluation V1.1 showed that the existing Regime V1 framework
substantially reduces drawdown, but its long-run return gap versus SPY
buy-and-hold is associated mainly with reduced SPY participation rather than
with the residual-cash assumption or transaction costs alone. It also showed
that Regime V1 changes exposure more often than a simple 200-session trend
benchmark and can re-enter slowly after fast market recoveries.

V1.2 will test whether a stateful exposure-transition overlay can preserve the
existing fast defensive behavior while improving re-entry and reducing
whipsaw/turnover.

The primary research objective is:

> Keep maximum drawdown at or below approximately 20%, improve CAGR versus the
> unchanged Regime V1 baseline, and materially reduce turnover and exposure
> whipsaw.

This is a research study. It does not replace Market Regime V1, alter broker or
order behavior, or authorize paper/live execution.

## Frozen V1 boundary

Market Regime V1 remains the fixed classifier and source of daily raw signals.
V1.2 must not change:

- trend, momentum, drawdown, or realized-volatility components;
- component weights;
- the `45 / 15 / -20` regime thresholds;
- `BULL / CAUTIOUS_BULL / RISK_OFF / BEAR` definitions;
- `100% / 70% / 30% / 0%` V1 maximum-long-exposure mapping;
- confidence scoring or QQQ confirmation behavior; or
- the existing public Market Regime V1 result contract.

V1.2 is strictly downstream of the existing classifier. The overlay may read
only the daily V1 `score`, `regime`, and `maximum_long_exposure` needed for
exposure transitions. QQQ confidence must not control V1.2 exposure.

The stabilization study itself has no QQQ dependency. It can run with SPY and
BIL alone. QQQ may still exist elsewhere in the repository for V1 confidence
reporting, but it is outside the V1.2 state machine and candidate selection.

## Non-goals

V1.2 will not:

- change or tune any Market Regime V1 scoring rule or threshold;
- optimize indicator windows;
- introduce new technical indicators, VIX, breadth, macro data, or
  fundamentals;
- introduce short exposure, leverage, options, inverse ETFs, or position sizes
  above the unchanged V1 cap;
- use QQQ confidence to decide exposure;
- search an unbounded parameter space;
- add parameters after inspecting locked-period results;
- claim a pristine unseen out-of-sample period where one does not exist;
- add a Streamlit page in the first implementation;
- add or modify broker, IBKR, order, paper-trading, or live-trading code;
- access `.env` or a market-data provider from automated tests; or
- promote a research winner directly into an execution path.

## Architecture

### Placement

Add a dedicated research module:

`src/private_quant/backtest/regime_stabilization.py`

The module will be provider-independent and broker-independent. It will consume
`PriceBar` histories supplied by callers and obtain unchanged daily V1 results
from `MarketRegimeEngine`.

The existing V1.1 evaluation module remains the source of the already-validated
portfolio simulation and performance-metric conventions. V1.2 may reuse the
existing internal interval simulation and metric helpers from
`regime_evaluation.py` rather than duplicating portfolio mathematics. Moving
those helpers to a new shared internal module is not required for V1.2 and
should be avoided unless implementation reveals a concrete circularity or
maintainability blocker.

All existing V1.1 behavior and its regression tests must remain unchanged.

### Research stages

V1.2 is intentionally two-stage:

1. **Candidate selection stage** — use only Development and Validation data,
   ending 2020-12-31. Select at most one frozen winner from a predeclared
   12-candidate grid.
2. **Locked evaluation stage** — only after a winner is frozen, evaluate that
   exact winner from 2021-01-01 through the latest complete common interval.

The locked stage cannot select, mutate, or replace the winner.

If no candidate passes the selection gates, the study stops with
`NO_QUALIFIED_CANDIDATE` and the locked period should not be opened merely to
rescue the design.

## Stabilization state machine

### Exposure levels

The only allowed overlay exposure levels are the unchanged V1 levels:

`0.0, 0.3, 0.7, 1.0`

The overlay must satisfy this invariant on every signal date:

`overlay_exposure <= v1_maximum_long_exposure`

The overlay can therefore delay an upgrade but can never override V1 to take
more risk than V1 currently permits.

### Fast de-risk

Downgrades are immediate and may skip multiple levels in one session.

For signal date `T`:

- if `v1_maximum_long_exposure(T) < prior_overlay_exposure`, set
  `overlay_exposure(T)` directly to the lower V1 cap;
- no confirmation is required;
- no same-session upward move is allowed after an immediate downgrade; and
- boundary confirmations whose qualifying conditions are no longer true reset
  to zero under the counter rules below.

Examples:

- `100% -> 70%` happens immediately when V1 caps at 70%;
- `100% -> 0%` happens immediately when V1 caps at 0%;
- `70% -> 30%` happens immediately when V1 caps at 30%.

This preserves the defensive characteristic that V1.1 already demonstrated.

### Confirmed re-entry

Upgrades use three fixed score boundaries inherited from V1:

| Upgrade | V1 boundary | Qualifying condition |
| --- | ---: | --- |
| `0% -> 30%` | `-20` | `score >= -20 + margin` |
| `30% -> 70%` | `15` | `score >= 15 + margin` |
| `70% -> 100%` | `45` | `score >= 45 + margin` |

The comparison is inclusive: equality qualifies.

Each boundary has its own confirmation counter. On every signal session:

- if the boundary's qualifying condition is true, increment that counter up to
  the candidate's required confirmation length;
- otherwise reset that counter to zero;
- counters update independently of the current overlay exposure; and
- higher-level counters may accumulate while the overlay is still at a lower
  level.

If no immediate downgrade occurred, the overlay may move upward by **at most
one exposure level per signal session**. The next level is allowed only when:

1. V1 currently permits at least that next exposure level; and
2. the counter for that boundary has reached the candidate's confirmation
   requirement.

This design avoids both extremes:

- it does not jump directly from 0% to 100% on one strong session; and
- it does not restart a full confirmation wait at each level when higher
  boundaries have already been confirming in parallel.

For example, with a three-session confirmation requirement and a sustained
strong BULL score, the three boundary counters can all qualify by the third
session. A portfolio starting at 0% can then progress `0 -> 30 -> 70 -> 100`
over consecutive sessions rather than waiting three new sessions at each
level.

### Counter state and reset semantics

Counters are deterministic, non-negative integers capped at the candidate's
confirmation length.

A counter retains its qualified value only while its score condition remains
true. The first session that fails the condition resets it to zero. No
calendar-day decay, grace period, or hidden persistence is allowed.

Because the higher thresholds are nested, a material downgrade naturally
clears the counters that are no longer supported by the score. Lower-boundary
counters may remain qualified when their conditions still hold.

### Initial and split-boundary state

The state machine is path-dependent and must not be artificially reset at the
start of Development, Validation, or Locked Evaluation.

Before the first performance interval, V1.2 may process earlier eligible SPY
signal dates as **state warm-up** so that overlay exposure and counters at the
first measured signal date reflect prior V1 history. Warm-up uses V1 signals
only; it does not earn portfolio returns or use future BIL returns.

For portfolio accounting, the measured virtual portfolio still starts at the
first common performance interval using the same V1.1 opening-cost convention:
its first simulated target exposure is charged as an opening allocation from
zero exposure. Signal-state warm-up therefore does not create a hidden
pre-period portfolio or free opening allocation.

The Development-to-Validation boundary and the Validation-to-Locked boundary
must preserve state-machine exposure and counters continuously. Window metrics
may be rebased for reporting, but the signal state is never restarted and no
artificial boundary trade is invented.

## Fixed candidate grid

The candidate search space is frozen before any V1.2 historical result is
examined.

### Margin values

`margin = 0, 5, 10 score points`

### Confirmation lengths

`confirmation_sessions = 1, 2, 3, 5`

### Exact grid

The cross-product produces exactly 12 candidates:

- `(margin=0, confirmation=1)`
- `(margin=0, confirmation=2)`
- `(margin=0, confirmation=3)`
- `(margin=0, confirmation=5)`
- `(margin=5, confirmation=1)`
- `(margin=5, confirmation=2)`
- `(margin=5, confirmation=3)`
- `(margin=5, confirmation=5)`
- `(margin=10, confirmation=1)`
- `(margin=10, confirmation=2)`
- `(margin=10, confirmation=3)`
- `(margin=10, confirmation=5)`

No additional margin, confirmation length, minimum-hold rule, cooldown,
indicator, threshold, or exposure level may be introduced after seeing study
results. Any such change is a separate future design version.

## Baseline and portfolio assumptions

The primary baseline is unchanged **Regime V1 with BIL residual-cash proxy at
5 bps**, using the V1.1 interval, cost, and metric conventions.

All candidate comparisons use:

- the same SPY/BIL common interval sequence as the baseline;
- USD 100,000 initial virtual capital for full-period paths;
- provider-supplied adjusted closes;
- BIL only as the residual-cash return proxy;
- 5 bps transaction cost on absolute changes in SPY target exposure;
- cost deducted before the interval return;
- no separate BIL trade or commission leg;
- signal at `T` applied only to the `T -> T+1` return; and
- zero daily hurdle for Sharpe and Sortino, consistent with V1.1.

The 0/2/10 bps scenarios are diagnostic only after the winner is frozen. They
must not participate in candidate selection.

## Fixed research periods

The date boundaries are predeclared and are not parameters.

### Development

`2007-10-01 through 2014-12-31`

### Validation

`2015-01-01 through 2020-12-31`

### Locked final evaluation

`2021-01-01 through the latest complete common SPY/BIL interval`

The locked period is deliberately called **locked evaluation**, not pristine
or blind out-of-sample, because parts of that history have already been viewed
in earlier V1/V1.1 diagnostics.

A period includes only complete `signal_date -> return_end_date` intervals
whose two endpoints fall within the requested reporting boundary. Portfolio
and state-machine paths remain continuous across boundaries.

### Combined selection period

Candidate ranking also uses one continuous combined Development + Validation
path from 2007-10-01 through 2020-12-31. This path is not restarted on
2015-01-01.

## Exposure-whipsaw metric

V1.2 adds a deterministic exposure-whipsaw diagnostic.

An exposure change is an opening side of a whipsaw when, within the next five
signal sessions, the overlay makes an opposite-direction change that returns
the exposure to or beyond the level that existed immediately before the
opening change.

Examples:

- `70 -> 30 -> 70` within five sessions: one whipsaw;
- `30 -> 70 -> 30` within five sessions: one whipsaw;
- `0 -> 30 -> 70 -> 100`: not a whipsaw because all changes are in the same
  direction;
- `100 -> 70`, followed by no return to 100 within five sessions: not a
  whipsaw.

Whipsaw counting uses non-overlapping reversal pairs. Once an opening change
has been paired with the first qualifying reversal, that reversal closes the
pair and is not reused as the opening change of the same pair. Later distinct
changes can begin a new pair.

The study reports both whipsaw count and whipsaw rate, where the rate is:

`whipsaw_pairs / exposure_changes`

If there are no exposure changes, the rate is `None` rather than an invented
zero.

The unchanged V1 baseline is scored with the same whipsaw definition so
reductions are apples-to-apples.

## Additional diagnostics

For the baseline and each candidate, selection-period diagnostics include:

- CAGR;
- maximum drawdown;
- annualized volatility;
- Sharpe;
- Sortino;
- Calmar;
- total transaction cost;
- annualized turnover;
- exposure-change count;
- average SPY exposure;
- exposure-bucket percentages;
- exposure-whipsaw count and rate; and
- time spent below the current V1 cap because re-entry confirmation delayed an
  upgrade.

For the frozen winner, post-selection diagnostics additionally include:

- re-entry lag in signal sessions for completed upward boundary transitions;
- mean and median re-entry lag;
- completed defensive-to-100% recovery episode durations;
- count of incomplete recovery episodes; and
- fixed historical-window summaries.

A boundary re-entry lag begins on the first qualifying session after that
boundary counter was last reset and ends when the overlay actually crosses
that boundary. Parallel counters and the one-level-per-session rule may make a
higher-boundary lag longer than the raw confirmation length.

A defensive-to-100% recovery episode begins when overlay exposure first falls
below 100% after having been at 100%, and completes when overlay exposure next
returns to 100%. Durations are measured in signal sessions. An episode still
open at the end of the requested period is counted as incomplete and is not
assigned a fabricated duration.

## Candidate qualification gates

A candidate must pass every gate before ranking.

All comparisons use the 5 bps BIL-cash baseline on identical intervals.

### Risk gates

- Development maximum drawdown must be `<= 20%` in magnitude.
- Validation maximum drawdown must be `<= 20%` in magnitude.

Equivalently, reported drawdown must be no worse than `-20%` in each period.

### Return gates

- Combined Development + Validation CAGR must be strictly greater than the
  unchanged V1 baseline CAGR on that same combined period.
- Development CAGR must not trail the baseline Development CAGR by more than
  `0.50 percentage point`.
- Validation CAGR must not trail the baseline Validation CAGR by more than
  `0.50 percentage point`.

A 0.50 percentage-point allowance means, for example, that a 9.00% baseline
permits no less than 8.50% for that split.

### Turnover and whipsaw gates

On the combined Development + Validation period:

- annualized turnover must be at least `15%` lower than the unchanged V1
  baseline; and
- exposure-whipsaw count must be at least `20%` lower than the unchanged V1
  baseline.

Percentage reductions use the baseline as denominator. If the baseline metric
is zero or otherwise makes a required reduction undefined, the candidate does
not pass that gate silently; the study reports the gate as not evaluable and
stops promotion logic for that comparison.

## Deterministic winner selection

If no candidate passes all qualification gates, selection returns no winner and
locked evaluation is not used to search for a rescue configuration.

If one or more candidates qualify, choose exactly one winner using this fixed
ordering:

1. Find the highest combined Development + Validation CAGR.
2. Treat any qualified candidate within `0.05 percentage point` of that top
   CAGR as effectively tied on return.
3. Within that return-tied set, choose the lowest combined whipsaw count.
4. If still tied, choose the better combined maximum drawdown (smaller loss in
   magnitude).
5. If still tied exactly, choose the smaller confirmation length.
6. If still tied, choose the smaller margin.

The selected `(margin, confirmation_sessions)` pair is then frozen. No ranking
metric from 2021 onward may participate in this choice.

The selection result must record the complete candidate grid, pass/fail status
for every gate, the deterministic ranking values, and the exact frozen winner
or explicit no-winner status.

## Locked evaluation and promotion rule

Locked evaluation is a separate operation that accepts the already-frozen
winner. It must not accept a candidate grid or perform ranking.

The winner is evaluated from 2021-01-01 through the latest complete common
interval using the same 5 bps BIL-cash baseline and continuous pre-2021 signal
state.

To be considered a successful **research promotion to V1.2**, the frozen winner
must pass every locked-period gate:

- maximum drawdown no worse than `-20%`;
- CAGR at least `0.25 percentage point` higher than unchanged V1;
- annualized turnover at least `15%` lower than unchanged V1; and
- exposure-whipsaw count at least `20%` lower than unchanged V1.

If any gate fails, the result is `NO_V1_2_PROMOTION`. The rules and parameters
must not be changed in response to that outcome.

A research promotion means only that this overlay becomes the preferred V1.2
research baseline. It does not modify the production V1 classifier and does
not authorize broker or execution integration.

## Post-selection diagnostics

Only after the winner is frozen, and without changing the winner, the study may
run:

- transaction-cost sensitivity at `0 / 2 / 5 / 10 bps`;
- full-period baseline-versus-winner metrics;
- 2007-10-01 through 2009-06-30;
- calendar 2020;
- calendar 2022;
- 2023-01-01 through 2025-12-31;
- exposure distributions;
- turnover and transaction-cost attribution;
- exposure-whipsaw diagnostics;
- re-entry-lag diagnostics; and
- defensive-to-full-exposure recovery durations.

These outputs are descriptive. They cannot reopen candidate selection.

## Point-in-time and data-isolation rules

### Candidate selection cutoff

Candidate selection must inspect only data whose canonical date is on or before
2020-12-31, plus earlier warm-up history needed to compute V1 signals. A valid
record dated after 2020-12-31 cannot affect selection because of its symbol,
price, or other content.

As in V1.1, an observation whose date itself is missing or unparseable cannot
be proven to lie beyond the cutoff and therefore fails safely rather than
being guessed away.

### Locked evaluation

Locked evaluation may inspect 2021-and-later prices only after the candidate is
frozen. It may use pre-2021 history solely to reconstruct continuous signal
state and the unchanged V1 indicators required on the first locked dates.

### No same-session leakage

For every interval, the state machine uses only the V1 result available on the
`signal_date`. The resulting overlay target applies only to the next-session
`signal_date -> return_end_date` return. No return ending on `T` can influence
an exposure decision applied to that same return.

## Proposed immutable contracts

The implementation should use frozen, slotted dataclasses and enums consistent
with the repository style. Exact names may vary slightly, but the contracts
must represent these concepts:

- `StabilizationCandidate` — fixed margin and confirmation-session pair.
- `BoundaryConfirmationState` — per-boundary deterministic counters.
- `StabilizationSignalPoint` — signal date, V1 score, V1 regime, V1 cap,
  prior overlay exposure, resulting overlay exposure, counters, and transition
  classification.
- `StabilizationDiagnostics` — whipsaw metrics, delayed-below-cap sessions,
  re-entry lag, and recovery-episode summaries.
- `CandidatePeriodResult` — candidate, period identifier, performance metrics,
  diagnostics, and qualification-gate outcomes.
- `CandidateSelectionResult` — baseline results, all 12 candidate results,
  qualification results, winner status, and frozen winner when present.
- `LockedEvaluationResult` — frozen candidate, locked baseline and candidate
  metrics, promotion-gate outcomes, promotion status, and diagnostics.

No result object contains provider clients, credentials, HTTP responses,
account data, broker state, or order state.

## Public orchestration boundary

The V1.2 module should expose separate provider-independent entry points for:

1. candidate selection through the fixed 2020-12-31 cutoff; and
2. locked evaluation of one already-frozen candidate from 2021 onward.

The selection entry point must not accept arbitrary candidate grids, custom
thresholds, custom margins, custom confirmation arrays, or custom split dates.
The fixed research protocol belongs to the implementation, not caller input.

The locked entry point must require a concrete frozen candidate returned by or
identical to the predeclared grid and must not perform candidate search.

Both entry points accept already-supplied price histories. Neither loads `.env`
or contacts Tiingo itself.

## Manual Tiingo validation protocol

Automated tests use deterministic synthetic fixtures only.

Any secret-backed Tiingo run requires explicit user authorization and occurs in
two manual stages.

### Manual Stage 1 — selection only

After implementation and deterministic verification are complete, Codex must
stop and request authorization before reading local `.env` or contacting
Tiingo.

If authorized, Stage 1 may fetch only the history needed through 2020-12-31,
run candidate selection, return sanitized coverage and candidate results, state
the frozen winner or no-winner result, and stop.

If no candidate qualifies, do not fetch/open the locked period merely to tune a
replacement.

### Manual Stage 2 — locked evaluation

Only after the Stage 1 winner has been reviewed and explicitly frozen may a
second authorized run fetch/read 2021-to-latest data and run locked evaluation.

Stage 2 must report sanitized source coverage, the frozen winner, baseline and
winner locked-period metrics, each promotion gate, and final
`PROMOTE_V1_2_RESEARCH` or `NO_V1_2_PROMOTION` status.

Neither stage may print API keys, `.env` contents, configuration objects, HTTP
headers, raw provider payloads, or downloaded market data.

Neither stage may connect to TWS/IBKR or touch orders.

## Error handling

The V1.2 research layer fails with fixed, sanitized messages for invalid
required SPY/BIL data or impossible state transitions. It must never include
raw provider values, credentials, file-system secrets, or account information
in exceptions.

An impossible overlay state, exposure above the V1 cap, exposure outside the
four allowed levels, invalid candidate outside the fixed grid, or attempt to
run locked promotion logic without a frozen candidate is a hard deterministic
failure rather than a silently repaired state.

Undefined ratios remain `None`, consistent with V1.1.

## Testing requirements

Implementation is test-driven. Required deterministic coverage includes:

### State machine

- immediate one-level and multi-level de-risk;
- no same-session re-upgrade after de-risk;
- inclusive margin boundary comparisons;
- independent confirmation counters;
- counter reset on failed qualifying condition;
- one-level-per-session maximum re-entry;
- parallel higher-boundary counter accumulation;
- overlay exposure never exceeds V1 cap;
- exact allowed exposure levels only; and
- deterministic repeated runs.

### Path continuity

- pre-period signal-state warm-up;
- opening simulated cost still measured from zero exposure;
- no state reset at Development/Validation boundary;
- no state reset at Validation/Locked boundary;
- no artificial boundary trade in window summaries; and
- locked state reconstructed from pre-2021 signals without using pre-2021
  returns as locked-period performance.

### Candidate protocol

- exactly 12 fixed candidates;
- no arbitrary candidate-grid input;
- selection ignores valid future-dated 2021+ price content;
- Development and Validation risk gates;
- combined return/turnover/whipsaw gates;
- exact 0.50 percentage-point split-return allowance;
- exact 0.05 percentage-point CAGR tie band;
- deterministic tie-break order;
- explicit no-winner result; and
- locked evaluator cannot search or replace the winner.

### Diagnostics

- whipsaw examples and non-examples;
- non-overlapping whipsaw pairing;
- `None` whipsaw rate when no exposure changes exist;
- re-entry lag calculation;
- completed and incomplete recovery episodes; and
- unchanged V1 baseline scored with the same whipsaw definition.

### Point-in-time safety

- signal at `T` applies only to `T -> T+1`;
- future valid-dated malformed SPY/BIL content cannot change selection ending
  before that date;
- unparseable dates fail safely;
- no QQQ/confidence dependency in the stabilization module; and
- no provider, `.env`, broker, IBKR, or order imports.

### Regression safety

- all existing Market Regime V1 tests remain green;
- all existing V1.1 evaluation tests remain green;
- the existing 269-test repository baseline must not regress; and
- automated tests never contact Tiingo, TWS, IB Gateway, or any order API.

## Documentation requirements

Implementation should update the Market Regime research documentation and
roadmap to describe V1.2 as a research study, the frozen candidate grid, the
two-stage anti-leak protocol, and the distinction between research promotion
and execution deployment.

Before manual Stage 1, documentation must not claim a V1.2 winner.

After Stage 1, documentation may record a sanitized frozen winner only if one
exists. It must not claim locked-period success until Stage 2 is explicitly
authorized and completed.

After Stage 2, documentation records the actual promotion result, including a
failure outcome without parameter retuning.

## Acceptance criteria

V1.2 implementation is complete for deterministic review when:

- the unchanged V1 classifier is untouched;
- the fixed 12-candidate state machine is implemented as specified;
- candidate selection is structurally isolated from 2021+ result data;
- locked evaluation requires an already-frozen winner;
- all required metrics and gate decisions are deterministic;
- V1.1 portfolio conventions remain unchanged;
- the full repository test suite, compileall, pip check, and `git diff --check`
  pass;
- source-safety review confirms no broker/order/configuration/`.env` coupling;
  and
- implementation stops before manual Tiingo Stage 1 until explicitly
  authorized.

A successful deterministic implementation does **not** itself mean V1.2 is
promoted. Promotion is an empirical result governed by the predeclared Stage 1
and Stage 2 rules above.

## Design summary

V1.2 freezes the existing Market Regime V1 classifier and tests one narrowly
scoped idea: **fast de-risk, stateful confirmed re-entry**.

The research search space is intentionally small and fixed: three score margins
by four confirmation lengths. Candidate selection ends in 2020, the winner is
frozen before any 2021+ evaluation, and failure is an allowed final result.

This design is intended to answer whether transition mechanics can improve
participation and stability without sacrificing the drawdown protection that
made V1 useful, while keeping the research process reproducible and resistant
to after-the-fact parameter tuning.
