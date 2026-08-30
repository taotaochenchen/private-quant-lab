# Market Regime V1.4 — Selective Churn Suppression Study

Date: 2026-08-30
Base: `0368fd960c23c6924a6b72b9a477f8fa39f9c0cd`
Status: Approved design; D1 diagnostic implementation not yet started

## 1. Purpose

V1.2 and V1.3 established a narrow empirical result about the existing Market Regime V1 exposure schedule:

- V1.2 reduced turnover and whipsaw only when re-entry confirmation became long enough to sacrifice too much return participation.
- V1.3 restored return participation with recovery-episode fast re-entry, but turnover and whipsaw remained close to the V1 baseline.

V1.4 therefore does **not** ask whether re-entry should be globally faster or slower. It asks:

> Which V1 de-risk/re-entry transition patterns actually generate short-horizon churn, and can a later event-driven overlay suppress only those patterns while leaving ordinary recovery mostly untouched?

V1.4 remains a downstream research overlay on frozen Market Regime V1. It is not a new classifier and does not authorize execution.

## 2. Frozen V1 boundary

The following remain unchanged throughout V1.4:

- `MarketRegimeEngine`
- V1 score construction
- V1 thresholds `45 / 15 / -20`
- V1 regime definitions
- V1 confidence behavior
- V1 QQQ confidence behavior
- V1 maximum-long-exposure mapping `1.0 / 0.7 / 0.3 / 0.0`

V1.4 diagnosis and any later candidate overlay may consume only:

- V1 `regime`
- V1 raw `score`
- V1 `maximum_long_exposure`
- V1/V1.4 transition history and V1.4-owned state

V1.4 must not add QQQ, SMA/EMA, VIX, breadth, price acceleration, volatility, momentum, or another market feature to classify churn.

## 3. Research protocol

V1.4 is split into three strictly separated stages.

### D1 — Mechanism Discovery

Period: `2007-10-01` through `2014-12-31`.

D1 produces a Whipsaw Anatomy Report only. It must not run V1.4 suppression candidates, compare candidate CAGR, search thresholds, or select parameters.

Once D1 is opened, this period is permanently a **Discovery Set** for V1.4. It may later be used only for explanation, diagnostics, and regression checks, never for candidate qualification, winner ranking, or promotion.

### V1 — Candidate Validation

Period: `2015-01-01` through `2020-12-31`.

Only after the D1 Mechanism Conclusion is reviewed and a maximum of three parameter-light candidate structures are explicitly frozen may V1 run once as the official candidate validation.

### L1 — Locked Evaluation

Period: `2021-01-01` through the latest complete common interval.

L1 remains closed until V1 produces one reviewable winner and that winner is explicitly frozen by a separate human authorization.

No 2021+ information may influence D1 diagnosis, candidate design, or V1 candidate selection.

## 4. D1 diagnostic constants

D1 constants are fixed at code level:

- initial capital: USD `100000`
- transaction cost: `5 bps`
- SPY authorized warm-up request start for the later real D1 run: `2006-09-01`
- discovery start: `2007-10-01`
- discovery end: `2014-12-31`
- inherited whipsaw window: `5 signal sessions`
- diagnostic cluster window: `10 signal sessions`
- diagnostic retry window: `10 signal sessions`

The 10-session windows are descriptive diagnostic windows, not future trading parameters. Candidate rules may not automatically use a 10-session cooldown merely because D1 uses a 10-session classification window.

## 5. Exposure change events

D1 operates on the frozen V1 target exposure schedule.

Each actual schedule change creates one immutable `V14ExposureChangeEvent` containing conceptually:

- signal index
- signal date
- from exposure
- to exposure
- direction: `UP` or `DOWN`
- primary boundary
- crossed boundaries
- V1 regime
- V1 raw score
- V1 cap

Allowed exposures are exactly:

`0.0, 0.3, 0.7, 1.0`.

A multi-level change remains one real schedule-change event. It must not be decomposed into fictional intermediate trades.

### Boundary enum

The fixed boundary set is:

- `ZERO_TO_THIRTY`
- `THIRTY_TO_SEVENTY`
- `SEVENTY_TO_FULL`

For a multi-level move, `crossed_boundaries` records all crossed boundaries in movement order. `primary_boundary` is the first boundary crossed when moving away from the opening exposure.

Example:

`1.0 -> 0.3`

has primary boundary `SEVENTY_TO_FULL` and crossed boundaries `(SEVENTY_TO_FULL, THIRTY_TO_SEVENTY)`.

## 6. Frozen whipsaw pair definition

V1.4 must preserve the existing V1.2/V1.3 non-overlapping whipsaw definition exactly.

- The first in-period target is not counted as a change.
- A change is an opener.
- Within the next five signal sessions, an opposite-direction change closes the pair if exposure returns to or crosses the opener's pre-change exposure.
- Pairs are non-overlapping.
- A closer cannot close more than one pair.

D1 requires pair-level detail, so it may introduce a richer extractor such as `_extract_v14_whipsaw_pairs`, but its pair count must have parity with the frozen V1.2/V1.3 whipsaw count for equivalent schedules.

The report's overall whipsaw rate remains exactly:

`whipsaw_pair_count / schedule_change_count`

and is `None` when the schedule-change denominator is zero.

Each immutable `V14WhipsawPair` records conceptually:

- opener event
- closer event
- latency in signal sessions
- primary boundary
- crossed boundaries
- failed re-entry flag
- failed de-risk flag
- opening transaction cost
- closing transaction cost
- total pair cost
- descriptive return attribution

Reversal latency is exactly:

`closer_signal_index - opener_signal_index`

and therefore lies in `1..5`.

## 7. Failed re-entry and failed de-risk

A whipsaw with an `UP` opener is a **failed re-entry** when the closer returns exposure to or below the opener's pre-change exposure within the frozen five-session window.

A whipsaw with a `DOWN` opener is a **failed de-risk** when the closer returns exposure to or above the opener's pre-change exposure within the frozen five-session window.

These classifications use only the target schedule. They do not use subsequent market returns to decide whether an action was a failure.

## 8. Same-boundary retry

Retries are defined only after a failed re-entry pair.

After that pair's closer, scan subsequent schedule-change events for at most 10 signal sessions. The first upward change that again crosses the same **primary boundary** is the retry.

A failed pair creates at most one retry record.

`V14RetryEvent` records conceptually:

- failed pair index/reference
- retry event
- primary boundary
- retry latency
- whether the retry itself later becomes a frozen-definition failed re-entry

Retry failure is determined by whether the retry event is the opener of a later extracted frozen-definition failed re-entry pair. Otherwise it is a retry success. This remains a structural classification, not a profitability claim.

## 9. Churn clusters

Clusters are built from the already extracted non-overlapping whipsaw pairs sorted by opener index.

The first pair opens a cluster. Each next pair joins the current cluster only when both are true:

1. its opener is at most 10 signal sessions after the **previous pair's** opener; and
2. the previous and current pairs share at least one crossed boundary.

Otherwise the current cluster closes and a new one opens.

This adjacent-pair chaining is deliberate. A sequence of opener indices 1, 9, 17 may remain one cluster when each adjacent pair is within 10 sessions and shares a boundary.

Each immutable `V14ChurnCluster` records conceptually:

- start/end dates and opener indices
- pair references
- pair count
- schedule-change count
- union of boundaries
- dominant boundary set
- failed re-entry count
- failed de-risk count
- absolute exposure turnover
- attributed transaction cost

Cluster `schedule_change_count` is the count of actual V1 schedule-change events whose signal indices fall from the first pair opener through the final pair closer, inclusive. It is not the count of fictional boundary crossings.

If multiple boundaries tie for dominance, the report must preserve all tied dominant boundaries in deterministic enum order rather than inventing a single winner.

## 10. Cost attribution

D1 uses the same continuous V1 + BIL residual-cash portfolio accounting and the same 5-bps SPY exposure-change cost model used by the frozen research protocol.

For each actual schedule change:

`abs(delta exposure) * 5 bps * current portfolio value`

D1 may aggregate cost into whipsaw pairs and churn clusters and report each group's share of Discovery-period transaction cost.

Cost attribution is descriptive and cannot alter structural classification.

## 11. Return attribution

For each whipsaw pair D1 may report descriptive values such as:

- SPY cumulative return across the pair window
- V1 baseline portfolio return across the pair window
- full-SPY comparator return
- transaction-cost drag

The classification layer and return-attribution layer must remain separate in code. Return information must never enter whipsaw extraction, retry classification, cluster formation, or boundary attribution.

D1 results must not be converted into new price-return thresholds or market signals.

## 12. D1 Whipsaw Anatomy Report

The main immutable public result is `V14WhipsawAnatomyReport`.

At minimum it must contain:

### Coverage and accounting

- analysis start/end
- sanitized SPY/BIL coverage metadata
- common evaluation interval count
- initial capital
- fixed transaction cost
- baseline schedule-change count
- baseline annualized turnover
- baseline total transaction cost

### Whipsaw summary

- total whipsaw pairs
- whipsaw rate
- pair records
- boundary breakdown by primary boundary
- all-crossed-boundary incidence breakdown, explicitly labeled non-additive because one pair may cross multiple boundaries
- latency counts for 1, 2, 3, 4, 5 sessions
- share within 2 sessions
- share within 3 sessions
- UP-opener count/share
- DOWN-opener count/share
- failed re-entry count/share
- failed de-risk count/share

### Retry summary

- retry count
- retry success count
- retry failure count
- retry failure rate when defined
- retry counts and failure rates by boundary

### Cluster summary

- cluster records
- number of clusters
- clustered whipsaw count/share
- multi-pair cluster count
- maximum pair count in one cluster
- dominant-boundary distribution
- turnover attributable to clusters
- transaction cost attributable to clusters

### Cost and return attribution

- whipsaw-pair transaction-cost total/share
- cluster transaction-cost total/share
- descriptive pair return attribution summaries

Undefined rates use `None`/unavailable semantics, not a fabricated zero. A valid period with zero whipsaws returns a valid zero-count report with empty pair/retry/cluster tuples rather than raising an error.

D1 must not output candidate performance, winner status, candidate ranking, promotion status, or hypothetical suppression results.

## 13. Mechanism Conclusion gate

After one official D1 run, the report is reviewed before any candidate design.

The conclusion may use structural facts such as:

- dominant boundaries
- UP vs DOWN opener composition
- reversal latency distribution
- same-boundary retry frequency
- repeated retry frequency
- cluster concentration
- defensive depth
- failed re-entry vs failed de-risk composition
- turnover/cost concentration

It must not derive trading rules from observed optimal score values, returns, calendar periods, best cooldown lengths, best latency cutoffs, or other empirical threshold searches.

Before candidate design begins, a short Mechanism Conclusion must be frozen and supported by report statistics. Every later candidate must state which frozen mechanism it targets.

## 14. Candidate-design constraints after D1

After the Mechanism Conclusion is frozen:

- at most 2–3 candidate structures may be defined;
- no broad parameter grid is allowed;
- candidates should be event-driven and parameter-light;
- first-attempt, failed-retry, repeated-retry, same-boundary, new-boundary, cap-change, and recovery-completion events are preferred building blocks;
- score margins, confirmation grids, cooldown grids, SMA/VIX/QQQ/breadth features, and other classifier-like inputs are prohibited unless a future separately approved design explicitly replaces this one.

Candidate implementation is **not part of the first V1.4 implementation cycle**.

## 15. V1 candidate validation gates

The future frozen candidates will be evaluated exactly once on `2015-01-01` through `2020-12-31` against the matching Market Regime V1 + BIL residual-cash baseline at 5 bps.

A candidate qualifies only if all four gates pass:

1. maximum drawdown `>= -20%`;
2. CAGR `>= baseline CAGR - 0.0025`;
3. annualized turnover `<= baseline turnover * 0.85`;
4. whipsaw pairs `<= baseline whipsaws * 0.80`.

Undefined/non-positive reduction denominators are `NOT_EVALUABLE` and cannot qualify.

If no candidate qualifies, the official result is:

`NO_QUALIFIED_V1_4_CANDIDATE`

with `winner = None`, and L1 remains closed.

Among multiple qualifiers, the winner is selected by:

1. highest Validation CAGR;
2. candidates within `0.0005` CAGR of the top candidate form the return-tied group;
3. within the tie: fewer whipsaw pairs;
4. better maximum drawdown;
5. lower annualized turnover;
6. narrower/more conservative mechanism scope.

Only one winner may be frozen.

## 16. L1 locked promotion gates

A separately authorized real 2021+ evaluation may occur only after one Validation winner is externally reviewed and frozen.

The candidate must pass all four:

1. maximum drawdown `>= -20%`;
2. CAGR `>= locked V1 baseline CAGR + 0.0025`;
3. annualized turnover `<= baseline turnover * 0.85`;
4. whipsaw pairs `<= baseline whipsaws * 0.80`.

All pass: `PROMOTE_V1_4_RESEARCH`.

Any fail or `NOT_EVALUABLE`: `NO_V1_4_PROMOTION`.

No retuning is allowed after locked results.

## 17. First implementation cycle: D1 only

The first implementation cycle creates only the provider-independent diagnosis infrastructure.

Preferred new files:

- `src/private_quant/backtest/regime_churn_diagnostics_v1_4.py`
- `tests/test_regime_churn_diagnostics_v1_4.py`

Documentation may update `docs/MARKET_REGIME_V1.md` and `docs/ROADMAP.md` only to describe the approved V1.4 protocol and implementation state.

It must **not** create:

- a V1.4 suppression candidate type;
- a suppression state machine;
- candidate qualification or ranking code;
- locked evaluation code;
- candidate performance diagnostics;
- broker, TWS, IBKR, order, paper, live, or UI integration.

The preferred narrow public API is conceptually:

```python
analyze_regime_churn_v1_4(
    spy_bars,
    bil_bars,
    *,
    engine=None,
) -> V14WhipsawAnatomyReport
```

The research constants remain internal and fixed rather than caller-configurable.

Reuse existing provider-independent V1 signal/accounting helpers when safe. Do not alter V1.2/V1.3 historical behavior merely to improve reuse. A small thin adapter or limited duplication is preferable to a large historical refactor.

## 18. Point-in-time and input safety

The D1 implementation must be safe before content access.

Real D1 authorization, when separately granted later, will allow only:

- SPY from `2006-09-01` through `2014-12-31`, including V1 warm-up;
- BIL from `2007-10-01` through `2014-12-31`;
- no QQQ;
- no 2015+ discovery requests.

Future-dated rows supplied to the pure analysis API may be date-filtered without reading their price content. A synthetic row whose date is after the D1 cutoff and whose price property raises if accessed must not affect the report. This safety behavior does not authorize a real provider request beyond the fixed D1 cutoff.

Fail closed before classifier use for malformed or unparseable dates.

For in-scope data, fail deterministically on:

- duplicate dates;
- non-increasing dates where ordering is required;
- non-finite or non-positive adjusted closes;
- insufficient V1 warm-up/history;
- missing required D1 outer boundaries;
- insufficient BIL coverage;
- missing common evaluation intervals.

No silent boundary shifting is allowed.

## 19. D1 official run integrity

The implementation task itself must not access Tiingo or `.env` and must not run Manual D1.

After implementation review/merge, Manual D1 requires a separate authorization and exactly one official diagnostic run.

The run may not be repeated merely because the result is weak or ambiguous. A rerun is allowed only to invalidate and replace a demonstrably defective run caused by an implementation/data-processing defect, which must be documented.

D1 may not alter:

- cluster definition;
- retry definition;
- latency buckets;
- whipsaw window;
- D1 period;
- candidate count or structure, because candidates do not yet exist.

## 20. Testing requirements

The D1 implementation must use TDD and include focused synthetic tests for at least:

1. exposure-change extraction;
2. the exact four allowed exposures;
3. single-level boundary attribution;
4. multi-level primary/crossed-boundary attribution;
5. parity with frozen V1.2/V1.3 whipsaw counts;
6. non-overlapping whipsaw pairs;
7. exact five-session closer boundary;
8. latency 1 through 5;
9. failed re-entry classification;
10. failed de-risk classification;
11. exact 10-session retry boundary;
12. same-primary-boundary retry requirement;
13. at most one retry per failed pair;
14. retry success/failure semantics;
15. exact 10-session cluster boundary;
16. shared-boundary cluster requirement;
17. adjacent-pair cluster chaining;
18. deterministic dominant-boundary ties;
19. cluster schedule-change-count semantics;
20. exposure turnover attribution;
21. transaction-cost attribution;
22. descriptive return attribution;
23. proof that return attribution cannot affect structural classification;
24. zero-whipsaw valid-report behavior;
25. undefined-rate semantics;
26. future-content exclusion before price access;
27. malformed future/input dates fail before classifier use;
28. no QQQ input;
29. no provider/network/config/`.env`/broker/order/UI coupling;
30. fixed D1 period, fixed SPY/BIL authorized ranges, and 5-bps protocol;
31. narrow public exports;
32. absence of candidate/winner/promotion contracts in the D1 module;
33. release-state documentation that Manual D1 remains unrun after implementation.

The full repository test suite, `compileall`, `pip check`, and `git diff --check` are required before the implementation branch is considered reviewable.

## 21. Roadmap state after D1 infrastructure only

After the first implementation cycle, ROADMAP should represent:

- `[x]` V1.4 design / D1 diagnostic infrastructure;
- `[ ]` Manual D1 Whipsaw Anatomy;
- `[ ]` Mechanism Conclusion frozen;
- `[ ]` Candidate design;
- `[ ]` 2015–2020 Candidate Validation;
- `[ ]` 2021+ Locked Evaluation.

No V1.4 candidate definition or empirical mechanism conclusion may be documented before Manual D1 is actually run and reviewed.

## 22. Non-goals and safety

V1.4 does not authorize:

- broker connectivity changes;
- TWS/IBKR order work;
- paper or live trading;
- Streamlit/UI work;
- `.env` or credential changes;
- provider configuration changes;
- new market-data subscriptions;
- a V2 classifier.

The study remains research-only and execution-free.
