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

The stabilization study itself has no QQQ dependency. It runs with SPY and BIL
alone. QQQ may still exist elsewhere in the repository for V1 confidence
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

Add a dedicated provider-independent research module:

`src/private_quant/backtest/regime_stabilization.py`

It consumes supplied `PriceBar` histories and obtains unchanged daily V1
results from `MarketRegimeEngine`.

The existing V1.1 evaluation module remains the source of the already-validated
portfolio simulation and performance-metric conventions. V1.2 may reuse the
existing internal interval simulation and metric helpers from
`regime_evaluation.py` rather than duplicate portfolio mathematics. Do not move
those helpers merely for cleanliness; move them only if implementation reveals
a concrete circularity or maintainability blocker.

All existing V1.1 behavior and regression tests remain unchanged.

### Research stages

V1.2 is intentionally two-stage:

1. **Candidate selection** uses only Development and Validation data ending
   2020-12-31 and selects at most one winner from the fixed 12-candidate grid.
2. **Locked evaluation** is allowed only after that winner is frozen and tests
   that exact winner from 2021-01-01 through the latest complete common
   interval.

The locked stage cannot select, mutate, or replace the winner.

If no candidate passes selection gates, the study returns
`NO_QUALIFIED_CANDIDATE` and stops. The locked period is not opened merely to
rescue the design.

## Stabilization state machine

### Allowed exposure levels

The only allowed overlay exposures are:

`0.0, 0.3, 0.7, 1.0`

On every signal date:

`overlay_exposure <= v1_maximum_long_exposure`

The overlay may delay an upgrade but can never override V1 to take more risk
than V1 permits.

### Per-session update order

For each signal date `T`, the state machine uses this exact order:

1. Read the unchanged V1 result available on `T`.
2. Update all three boundary confirmation counters from `score(T)`.
3. If `v1_maximum_long_exposure(T) < prior_overlay_exposure`, immediately set
   the overlay to the lower V1 cap and stop transition processing for `T`.
4. Otherwise, consider at most one upward exposure step using the updated
   counters and the current V1 cap.
5. Persist the resulting overlay exposure and counters for the next signal
   session.

No same-session return participates in these steps.

### Fast de-risk

Downgrades are immediate and may skip multiple levels in one session.

Examples:

- `100% -> 70%` occurs immediately when V1 caps at 70%;
- `100% -> 0%` occurs immediately when V1 caps at 0%;
- `70% -> 30%` occurs immediately when V1 caps at 30%.

No confirmation is required and no same-session upward move is allowed after a
downgrade.

### Confirmed re-entry

Upgrades use the three existing V1 score boundaries:

| Upgrade | V1 boundary | Qualifying condition |
| --- | ---: | --- |
| `0% -> 30%` | `-20` | `score >= -20 + margin` |
| `30% -> 70%` | `15` | `score >= 15 + margin` |
| `70% -> 100%` | `45` | `score >= 45 + margin` |

Equality qualifies.

Each boundary owns an independent confirmation counter. On each signal date:

- if its qualifying condition is true, increment the counter up to the
  candidate's required confirmation length;
- otherwise reset it to zero;
- counters update independently of current overlay exposure; and
- higher-boundary counters may accumulate while the overlay remains at a lower
  level.

If no downgrade occurred, the overlay may rise by **at most one exposure level
per signal session**. The next level is allowed only when:

1. V1 currently permits at least that next level; and
2. the corresponding counter has reached the confirmation requirement.

This avoids both direct `0 -> 100` jumps and a full new waiting period at every
level when higher boundaries have already been confirming in parallel.

Example: with three-session confirmation and a sustained strong BULL score, all
three counters may be qualified by session three. A portfolio at 0% can then
move `0 -> 30 -> 70 -> 100` over consecutive sessions rather than waiting
three new sessions at each level.

### Counter state

Counters are non-negative integers capped at the candidate's confirmation
length. A counter remains qualified only while its score condition remains
true. The first failing session resets it to zero. There is no calendar-day
decay, grace period, cooldown, or hidden persistence.

### Initial state and warm-up

Before the first V1-eligible signal, overlay exposure is `0.0` and all counters
are zero.

The state machine **must process every eligible SPY signal date** from the first
V1-eligible signal through the session immediately before the first measured
performance signal. This state warm-up establishes the overlay exposure and
counters that exist when measured performance begins.

Warm-up uses V1 signals only. It earns no portfolio returns and uses no future
BIL return.

For portfolio accounting, the measured virtual portfolio still starts at the
first common performance interval under the V1.1 opening-cost convention: the
first simulated target exposure is charged as an opening allocation from zero
portfolio exposure. Signal-state warm-up therefore does not create a hidden
pre-period portfolio or a free opening allocation.

### Split-boundary continuity

The Development-to-Validation and Validation-to-Locked boundaries never reset
state-machine exposure or counters.

Period metrics are slices of one continuous strategy path. For reporting,
each period is rebased from its first included **pre-cost starting value** in
the same manner as V1.1 historical-window summaries. No artificial opening
allocation, liquidation, or boundary trade is created at 2015-01-01 or
2021-01-01.

## Fixed candidate grid

The search space is frozen before any V1.2 historical result is examined.

### Margins

`margin = 0, 5, 10 score points`

### Confirmation lengths

`confirmation_sessions = 1, 2, 3, 5`

### Exact 12 candidates

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
indicator, threshold, or exposure level may be introduced after observing
study results. Any such change requires a new design version.

## Baseline and portfolio assumptions

The primary baseline is unchanged **Regime V1 with BIL residual-cash proxy at
5 bps**, using V1.1 interval, cost, and metric conventions.

All candidate comparisons use:

- the identical SPY/BIL common interval sequence as baseline;
- USD 100,000 initial virtual capital for full measured paths;
- provider-supplied adjusted closes;
- BIL only as residual-cash return proxy;
- 5 bps cost on absolute changes in SPY target exposure;
- cost deducted before the interval return;
- no separate BIL trade or commission leg;
- signal at `T` applied only to `T -> T+1`; and
- zero daily hurdle for Sharpe and Sortino.

The 0/2/10 bps cases are post-selection diagnostics only and cannot influence
candidate selection.

## Fixed research periods

The date boundaries are predeclared, not parameters.

### Development

`2007-10-01 through 2014-12-31`

### Validation

`2015-01-01 through 2020-12-31`

### Locked evaluation

`2021-01-01 through latest complete common SPY/BIL interval`

The locked period is deliberately not called pristine or blind out-of-sample,
because portions were already viewed in earlier V1/V1.1 diagnostics.

A reporting period contains only complete `signal_date -> return_end_date`
intervals whose two endpoints fall within the requested boundary. If required
SPY/BIL common coverage is unavailable, the study fails explicitly rather than
silently shifting a fixed research boundary to improve results.

### Combined selection period

Ranking also uses one continuous Development + Validation path from
2007-10-01 through 2020-12-31. It is not restarted on 2015-01-01.

## Exposure-whipsaw metric

Whipsaw is measured from the **signal target schedule**, not from the virtual
portfolio's artificial opening allocation at the first measured interval.

A schedule exposure change compares one signal target with the preceding
signal target. The first measured target by itself is not a schedule change for
whipsaw purposes.

An exposure change opens a whipsaw when, within the next five signal sessions,
a subsequent opposite-direction change returns exposure to or beyond the level
that existed immediately before the opening change.

Examples:

- `70 -> 30 -> 70` within five sessions: one whipsaw;
- `30 -> 70 -> 30` within five sessions: one whipsaw;
- `0 -> 30 -> 70 -> 100`: not a whipsaw;
- `100 -> 70` without a return to 100 within five sessions: not a whipsaw.

Whipsaw pairs are non-overlapping. After an opening change is paired with the
first qualifying reversal, scanning resumes after that closing change; the
closing change is not reused as another opener for the same sequence.

Report:

- `schedule_exposure_changes`;
- `whipsaw_pairs`; and
- `whipsaw_rate = whipsaw_pairs / schedule_exposure_changes`.

If `schedule_exposure_changes == 0`, whipsaw rate is `None`.

The unchanged V1 baseline uses the identical definition.

The existing V1.1 portfolio `exposure_changes` metric may still be reported for
compatibility; it is distinct because it includes the virtual opening
allocation from zero.

## Additional diagnostics

For baseline and each candidate, selection-period diagnostics include:

- CAGR;
- maximum drawdown;
- annualized volatility;
- Sharpe;
- Sortino;
- Calmar;
- total transaction cost;
- annualized turnover;
- V1.1 portfolio exposure-change count;
- schedule exposure-change count;
- average SPY exposure;
- exposure buckets;
- whipsaw count and rate; and
- sessions where overlay exposure is below the current V1 cap because re-entry
  is delayed.

For the frozen winner, post-selection diagnostics additionally include:

- re-entry lag in signal sessions for completed upward boundary transitions;
- mean and median re-entry lag;
- defensive-to-100% recovery durations; and
- incomplete recovery-episode count.

A boundary re-entry lag begins on the first qualifying session after that
boundary counter was last reset and ends when the overlay actually crosses
that boundary. Parallel counters and the one-level-per-session rule may make a
higher-boundary lag longer than the raw confirmation length.

A defensive-to-100% recovery episode begins when overlay exposure first falls
below 100% after having been at 100%, and completes when overlay exposure next
returns to 100%. Durations are signal-session counts. An episode open at period
end is counted as incomplete and receives no fabricated duration.

## Candidate qualification gates

A candidate must pass every gate before ranking. All comparisons use the
unchanged **Regime V1 + BIL proxy + 5 bps** baseline on identical intervals.

### Risk

- Development maximum drawdown must be no worse than `-20%`.
- Validation maximum drawdown must be no worse than `-20%`.

### Return

- Combined Development + Validation CAGR must be strictly greater than baseline
  CAGR on the same combined period.
- Development CAGR may trail baseline Development CAGR by no more than
  `0.50 percentage point`.
- Validation CAGR may trail baseline Validation CAGR by no more than
  `0.50 percentage point`.

A 9.00% baseline therefore permits no less than 8.50% under the split-specific
allowance.

### Turnover and whipsaw

On the combined Development + Validation period:

- annualized turnover must be at least `15%` lower than baseline; and
- whipsaw-pair count must be at least `20%` lower than baseline.

Percentage reductions use baseline as denominator. If a baseline metric is
zero or otherwise makes a required reduction undefined, that gate is reported
as not evaluable and the candidate cannot silently pass it.

## Deterministic winner selection

If no candidate passes all gates, return no winner and do not use locked data to
search for a rescue configuration.

If one or more candidates qualify:

1. Find the highest combined Development + Validation CAGR.
2. Treat qualified candidates within `0.05 percentage point` of that top CAGR
   as tied on return.
3. Within that return-tied set, choose the lowest combined whipsaw count.
4. If still tied, choose the better combined maximum drawdown (smaller loss in
   magnitude).
5. If still tied, choose the smaller confirmation length.
6. If still tied, choose the smaller margin.

The selected `(margin, confirmation_sessions)` is frozen. No 2021+ metric may
participate in selection.

The selection result records the full 12-candidate grid, every gate result,
ranking metrics, and either the exact frozen winner or explicit no-winner
status.

## Locked evaluation and promotion

Locked evaluation is a separate operation that accepts one already-frozen
candidate. It cannot accept a candidate grid or perform ranking.

The frozen winner and unchanged **Regime V1 + BIL proxy + 5 bps** baseline are
measured from 2021-01-01 through latest complete common interval, using
continuous pre-2021 signal state and period metrics rebased from the first
included pre-cost starting value. No artificial 2021 opening trade is added.

Research promotion requires every locked-period gate:

- maximum drawdown no worse than `-20%`;
- CAGR at least `0.25 percentage point` higher than baseline;
- annualized turnover at least `15%` lower than baseline; and
- whipsaw-pair count at least `20%` lower than baseline.

If any gate fails, return `NO_V1_2_PROMOTION`. Rules and parameters must not be
changed in response.

A successful `PROMOTE_V1_2_RESEARCH` result means only that this overlay becomes
the preferred research baseline. It does not modify V1 production behavior and
does not authorize execution integration.

## Post-selection diagnostics

Only after the winner is frozen, and without changing it, the study may run:

- transaction-cost sensitivity at `0 / 2 / 5 / 10 bps`;
- full-period baseline-versus-winner metrics;
- 2007-10-01 through 2009-06-30;
- calendar 2020;
- calendar 2022;
- 2023-01-01 through 2025-12-31;
- exposure distributions;
- turnover and transaction-cost attribution;
- whipsaw diagnostics;
- re-entry-lag diagnostics; and
- defensive-to-full recovery durations.

These are descriptive and cannot reopen candidate selection.

## Point-in-time and data-isolation rules

### Candidate selection cutoff

Candidate selection must inspect price content only for records whose canonical
date is on or before 2020-12-31, plus earlier warm-up history. A valid record
dated after 2020-12-31 cannot affect selection because of its symbol, price, or
other content.

A record whose date itself is missing or unparseable cannot be proved to lie
beyond the cutoff and fails safely rather than being guessed away.

### Locked evaluation

Locked evaluation may inspect 2021+ returns only after the candidate is frozen.
It may use pre-2021 SPY history solely to reconstruct continuous V1 indicators,
overlay exposure, and counters at the locked boundary.

### No same-session leakage

For every interval, only the V1 result available on `signal_date` controls the
overlay target. That target applies only to the next-session
`signal_date -> return_end_date` return.

## Proposed immutable contracts

Use frozen, slotted dataclasses/enums consistent with repository style. Exact
names may vary slightly, but contracts must represent:

- `StabilizationCandidate` — fixed margin and confirmation pair;
- `BoundaryConfirmationState` — three boundary counters;
- `StabilizationSignalPoint` — signal date, V1 score/regime/cap, prior overlay,
  resulting overlay, counters, and transition classification;
- `StabilizationDiagnostics` — schedule changes, whipsaw, delayed-below-cap,
  re-entry lag, and recovery summaries;
- `CandidatePeriodResult` — candidate, period, performance metrics,
  diagnostics, and gate outcomes;
- `CandidateSelectionResult` — baseline, all 12 candidates, qualification and
  ranking results, plus frozen winner or no-winner status; and
- `LockedEvaluationResult` — frozen candidate, locked baseline/candidate
  metrics, promotion gates, promotion status, and diagnostics.

No result contains provider clients, credentials, HTTP responses, account data,
broker state, or order state.

## Public orchestration boundary

Expose separate provider-independent entry points for:

1. fixed-protocol candidate selection through 2020-12-31; and
2. locked evaluation of one frozen candidate from 2021 onward.

Selection must not accept custom grids, thresholds, margins, confirmation
arrays, or split dates. Locked evaluation must require a candidate from the
fixed grid and must not perform search.

Both accept supplied histories. Neither loads `.env` nor contacts Tiingo.

## Manual Tiingo validation protocol

Automated tests use deterministic synthetic fixtures only. Secret-backed Tiingo
runs require explicit user authorization and occur in two stages.

### Manual Stage 1 — selection only

After deterministic implementation verification, stop before reading local
`.env` or contacting Tiingo.

If explicitly authorized, Stage 1 may fetch the SPY warm-up history and SPY/BIL
history required through **2020-12-31 only**. It must not request or inspect
2021+ prices. Run candidate selection, report sanitized coverage and all gate
results, state the frozen winner or no-winner result, and stop.

If no candidate qualifies, do not open the locked period to tune a replacement.

### Manual Stage 2 — locked evaluation

Only after Stage 1 results are reviewed and one winner is explicitly frozen may
Stage 2 run.

Stage 2 may fetch enough pre-2021 SPY history to reconstruct continuous V1 and
overlay state, plus SPY/BIL history required from 2021 through latest complete
common interval. It may not run the candidate grid, change the frozen winner,
or use locked metrics to choose a replacement.

Report sanitized coverage, the exact frozen winner, baseline and winner locked
metrics, each promotion gate, and final `PROMOTE_V1_2_RESEARCH` or
`NO_V1_2_PROMOTION`.

Neither stage may print API keys, `.env` contents, configuration objects, HTTP
headers, raw provider payloads, or downloaded market data. Neither stage may
connect to TWS/IBKR or touch orders.

## Error handling

Use fixed sanitized errors for invalid required SPY/BIL data or impossible
state transitions. Exceptions must not include raw provider values,
credentials, secrets, or account information.

Exposure above V1 cap, exposure outside the four allowed levels, invalid
candidate outside the fixed grid, impossible counter state, or locked
promotion without a frozen candidate is a hard deterministic failure rather
than a silently repaired state.

Undefined ratios remain `None`, consistent with V1.1.

## Testing requirements

Implementation is test-driven.

### State machine

- exact per-session update order;
- immediate one-level and multi-level de-risk;
- no same-session re-upgrade after de-risk;
- inclusive score/margin boundaries;
- independent counters and reset behavior;
- one-level-per-session maximum re-entry;
- parallel higher-boundary accumulation;
- overlay never exceeds V1 cap;
- exact allowed exposure levels; and
- repeated-run determinism.

### Path continuity

- initial `0%`/zero-counter state before first eligible signal;
- processing of every eligible warm-up signal;
- opening simulated cost still measured from zero portfolio exposure;
- no state reset at Development/Validation;
- no state reset at Validation/Locked;
- period metrics rebased without artificial trades; and
- locked state reconstructed from pre-2021 signals without counting pre-2021
  returns as locked performance.

### Candidate protocol

- exactly 12 fixed candidates;
- no arbitrary-grid input;
- selection cannot inspect valid-dated 2021+ price content;
- Development/Validation risk gates;
- combined return/turnover/whipsaw gates;
- exact `0.50 pp` split-return allowance;
- exact `0.05 pp` CAGR tie band;
- deterministic tie-break order;
- explicit no-winner result; and
- locked evaluator cannot search or replace the winner.

### Diagnostics

- whipsaw examples and non-examples;
- opening virtual allocation excluded from schedule-whipsaw logic;
- non-overlapping pair semantics;
- `None` whipsaw rate with zero schedule changes;
- re-entry lag;
- complete/incomplete recovery episodes; and
- unchanged V1 baseline scored with identical whipsaw logic.

### Point-in-time safety

- `T` signal applies only to `T -> T+1`;
- future valid-dated malformed SPY/BIL content cannot change earlier selection;
- unparseable dates fail safely;
- no QQQ/confidence dependency in stabilization; and
- no provider, `.env`, broker, IBKR, or order imports.

### Regression safety

- existing Market Regime V1 tests remain green;
- existing V1.1 tests remain green;
- the merged 269-test repository baseline does not regress; and
- automated tests never contact Tiingo, TWS, IB Gateway, or order APIs.

## Documentation requirements

Update Market Regime research docs and roadmap to describe V1.2 as research,
the frozen grid, the two-stage anti-leak protocol, and the distinction between
research promotion and execution deployment.

Before Manual Stage 1, docs must not claim a winner. After Stage 1, docs may
record a sanitized frozen winner only if one exists. Locked success must not be
claimed until explicitly authorized Stage 2 is complete. After Stage 2, record
the actual promotion or failure result without retuning.

## Acceptance criteria

Deterministic implementation is ready for review when:

- Market Regime V1 classifier behavior is untouched;
- the fixed 12-candidate state machine is implemented exactly;
- selection is structurally isolated from 2021+ result data;
- locked evaluation requires a frozen winner;
- metrics and gate outcomes are deterministic;
- V1.1 portfolio conventions remain unchanged;
- full tests, compileall, pip check, and `git diff --check` pass;
- source-safety review shows no broker/order/configuration/`.env` coupling; and
- implementation stops before Manual Stage 1 until explicit authorization.

A deterministic implementation does **not** itself promote V1.2. Promotion is
an empirical result governed by the predeclared Stage 1 and Stage 2 rules.

## Design summary

V1.2 freezes Market Regime V1 and tests one narrow idea: **fast de-risk,
stateful confirmed re-entry**.

The search space is fixed at three margins by four confirmation lengths.
Selection ends in 2020, the winner is frozen before any 2021+ evaluation, and
failure is an allowed final result.

The design is intended to determine whether transition mechanics can improve
participation and stability without sacrificing the drawdown protection that
made V1 useful, while keeping the research process reproducible and resistant
to after-the-fact tuning.
