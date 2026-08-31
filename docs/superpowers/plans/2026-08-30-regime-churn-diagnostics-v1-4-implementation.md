# Market Regime V1.4 D1 Churn Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved provider-independent V1.4 D1 Whipsaw Anatomy engine for the frozen 2007-10-01 through 2014-12-31 Discovery Set, without running Manual D1 or creating suppression-candidate logic.

**Architecture:** One focused module consumes the unchanged V1 signal schedule and existing V1+BIL accounting helpers, then derives immutable exposure-change events, rich non-overlapping whipsaw pairs, same-boundary retries, churn clusters, and descriptive cost/return attribution. Structural classification and return attribution are separate layers. Existing V1/V1.2/V1.3 implementation files remain unchanged.

**Tech Stack:** Python 3.11+, stdlib `dataclasses` / `enum` / `statistics` / `unittest`, existing `regime_evaluation` and `regime_stabilization` helpers. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-30-regime-churn-diagnostics-v1-4-design.md`

## Global Constraints

- Approved base SHA: `0368fd960c23c6924a6b72b9a477f8fa39f9c0cd`.
- Working branch: `codex/regime-churn-diagnostics-v1-4`; approved spec commits already exist on this branch.
- D1 only. Do not implement candidate, suppression, ranking, winner, validation, locked-evaluation, or promotion contracts.
- Fixed D1 protocol: initial capital USD `100000`, transaction cost `5.0` bps, Discovery `2007-10-01` through `2014-12-31`, whipsaw window `5` signal sessions, retry/cluster windows `10` signal sessions.
- Later real Manual D1 authorization will permit SPY `2006-09-01` through `2014-12-31` and BIL `2007-10-01` through `2014-12-31`; this implementation cycle must not access Tiingo, `.env`, or any provider.
- No QQQ input. The unchanged `_build_v1_signals` call remains `qqq_bars=None` internally.
- Freeze `MarketRegimeEngine`, score construction, thresholds `45 / 15 / -20`, regimes, confidence/QQQ behavior, and exposure mapping `(0.0, 0.3, 0.7, 1.0)`.
- Preserve V1+BIL residual-cash accounting: exposure-change cost is charged on `signal_date` before the `signal_date -> return_end_date` return; BIL adds no transaction leg.
- Reuse unchanged helpers from `regime_evaluation.py` / `regime_stabilization.py` where safe. Do not refactor V1.2/V1.3 merely for reuse.
- Future-dated rows supplied to the pure API may be ignored by date without reading price content. This is an API-safety property, not authorization to request post-2014 provider data.
- Structural classification must never consume return-attribution values.
- Every implementation task uses RED -> GREEN -> review -> commit.
- Preserve `src/private_quant/backtest/__init__.py`; expose V1.4 only through the new module's exact `__all__`.
- No broker, IBKR, TWS, order, Streamlit/UI, provider registry, configuration, `.env`, `.env.example`, dependency, or market-data-adapter changes.
- No raw market data, provider payloads, console dumps, or secrets may be committed.

## File Responsibilities

- Create `src/private_quant/backtest/regime_churn_diagnostics_v1_4.py`: fixed D1 constants, immutable public report contracts, private structural extraction, descriptive attribution, and the single public analysis function.
- Create `tests/test_regime_churn_diagnostics_v1_4.py`: synthetic behavior, parity, accounting, point-in-time, export, source-safety, and release-state tests.
- Modify `docs/MARKET_REGIME_V1.md`: approved V1.4 methodology and `Manual D1 NOT RUN` state.
- Modify `docs/ROADMAP.md`: V1.4 stage checklist with only design/infrastructure complete.
- Preserve all other source files, especially `regime_evaluation.py`, `regime_stabilization.py`, `regime_reentry_v1_3.py`, `market_regime.py`, and `backtest/__init__.py`.

## Exact Final Public Contracts

The final new-module `__all__` is exactly:

```python
{
    "V14Boundary",
    "V14Direction",
    "V14Coverage",
    "V14ExposureChangeEvent",
    "V14PairReturnAttribution",
    "V14WhipsawPair",
    "V14RetryEvent",
    "V14ChurnCluster",
    "V14BoundaryCount",
    "V14LatencyCount",
    "V14DirectionCount",
    "V14RetryBoundaryStats",
    "V14ReturnSummary",
    "V14WhipsawAnatomyReport",
    "analyze_regime_churn_v1_4",
}
```

All records are `@dataclass(frozen=True, slots=True)`.

Final fields:

```python
class V14Coverage:
    symbol: str
    first_date: date
    last_date: date
    rows: int

class V14ExposureChangeEvent:
    signal_index: int
    signal_date: date
    from_exposure: float
    to_exposure: float
    direction: V14Direction
    primary_boundary: V14Boundary
    crossed_boundaries: tuple[V14Boundary, ...]
    v1_regime: MarketRegime
    v1_score: int | float
    v1_cap: float

class V14PairReturnAttribution:
    spy_cumulative_return: float
    baseline_portfolio_return: float
    full_spy_comparator_return: float
    transaction_cost_drag: float

class V14WhipsawPair:
    opener: V14ExposureChangeEvent
    closer: V14ExposureChangeEvent
    latency_sessions: int
    primary_boundary: V14Boundary
    crossed_boundaries: tuple[V14Boundary, ...]
    failed_reentry: bool
    failed_derisk: bool
    opening_transaction_cost: float
    closing_transaction_cost: float
    pair_transaction_cost: float
    return_attribution: V14PairReturnAttribution | None

class V14RetryEvent:
    failed_pair_index: int
    retry_event: V14ExposureChangeEvent
    primary_boundary: V14Boundary
    retry_latency_sessions: int
    failed_again: bool

class V14ChurnCluster:
    start_date: date
    end_date: date
    start_opener_index: int
    end_closer_index: int
    pair_indices: tuple[int, ...]
    pair_count: int
    schedule_change_count: int
    boundaries: tuple[V14Boundary, ...]
    dominant_boundaries: tuple[V14Boundary, ...]
    failed_reentry_count: int
    failed_derisk_count: int
    absolute_exposure_turnover: float
    transaction_cost: float

class V14BoundaryCount:
    boundary: V14Boundary
    count: int
    share: float | None

class V14LatencyCount:
    latency_sessions: int
    count: int
    share: float | None

class V14DirectionCount:
    direction: V14Direction
    count: int
    share: float | None

class V14RetryBoundaryStats:
    boundary: V14Boundary
    retry_count: int
    retry_failure_count: int
    retry_failure_rate: float | None

class V14ReturnSummary:
    mean_spy_return: float | None
    median_spy_return: float | None
    mean_baseline_return: float | None
    median_baseline_return: float | None
    mean_full_spy_return: float | None
    median_full_spy_return: float | None
    mean_transaction_cost_drag: float | None
    median_transaction_cost_drag: float | None
```

`V14WhipsawAnatomyReport` fields, in order:

```python
analysis_start: date
analysis_end: date
spy_coverage: V14Coverage
bil_coverage: V14Coverage
common_interval_count: int
initial_capital: float
transaction_cost_bps: float
schedule_change_count: int
annualized_turnover: float | None
total_transaction_cost: float
whipsaw_pair_count: int
whipsaw_rate: float | None
pairs: tuple[V14WhipsawPair, ...]
primary_boundary_breakdown: tuple[V14BoundaryCount, ...]
crossed_boundary_incidence: tuple[V14BoundaryCount, ...]
latency_breakdown: tuple[V14LatencyCount, ...]
share_within_2_sessions: float | None
share_within_3_sessions: float | None
direction_breakdown: tuple[V14DirectionCount, ...]
failed_reentry_count: int
failed_reentry_share: float | None
failed_derisk_count: int
failed_derisk_share: float | None
retries: tuple[V14RetryEvent, ...]
retry_count: int
retry_success_count: int
retry_failure_count: int
retry_failure_rate: float | None
retry_by_boundary: tuple[V14RetryBoundaryStats, ...]
clusters: tuple[V14ChurnCluster, ...]
cluster_count: int
clustered_whipsaw_count: int
clustered_whipsaw_share: float | None
multi_pair_cluster_count: int
max_pair_count_in_cluster: int
cluster_dominant_boundary_incidence: tuple[V14BoundaryCount, ...]
cluster_absolute_exposure_turnover: float
cluster_transaction_cost: float
cluster_transaction_cost_share: float | None
whipsaw_pair_transaction_cost: float
whipsaw_pair_transaction_cost_share: float | None
return_summary: V14ReturnSummary
```

`crossed_boundary_incidence` and `cluster_dominant_boundary_incidence` are explicitly non-additive; their shares use pair-count and cluster-count denominators respectively and may sum above 1.0. All other share/rate fields use `None` when their denominator is zero.

---

### Task 1: Fixed constants, enums, contracts, and exposure-change extraction

**Files:** Create new module/test file only.

**Interfaces:** Consume `ALLOWED_EXPOSURES`, `_V1Signal`, `_build_v1_signals` and `MarketRegime`. Produce private `_D1_INITIAL_CAPITAL=100_000.0`, `_D1_COST_BPS=5.0`, `_D1_START=date(2007,10,1)`, `_D1_END=date(2014,12,31)`, `_WHIPSAW_WINDOW=5`, `_RETRY_WINDOW=10`, `_CLUSTER_WINDOW=10`; enums `V14Boundary` and `V14Direction`; contracts listed above; private `_extract_change_events(signals)`.

- [ ] **Step 1: Write failing `V14ContractTests` and `ExposureChangeEventTests`.** Lock enum values, constant values, exact field order, frozen/slotted behavior, first-target-not-change semantics, strict signal validation, and movement-order boundary attribution. Include:

```python
signals = (
    _V1Signal(date(2010,1,1), 60, MarketRegime.BULL, 1.0),
    _V1Signal(date(2010,1,2), 10, MarketRegime.RISK_OFF, 0.3),
    _V1Signal(date(2010,1,3), -30, MarketRegime.BEAR, 0.0),
    _V1Signal(date(2010,1,4), 60, MarketRegime.BULL, 1.0),
)
events = module._extract_change_events(signals)
self.assertEqual(events[0].crossed_boundaries,
    (V14Boundary.SEVENTY_TO_FULL, V14Boundary.THIRTY_TO_SEVENTY))
self.assertEqual(events[2].crossed_boundaries,
    (V14Boundary.ZERO_TO_THIRTY, V14Boundary.THIRTY_TO_SEVENTY,
     V14Boundary.SEVENTY_TO_FULL))
```

Reject non-plain/non-increasing dates, bool/non-finite scores, wrong regimes, bool/non-finite/unrecognized caps, and non-`_V1Signal` spoof/subclass records.

- [ ] **Step 2: Run RED.**

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m unittest tests.test_regime_churn_diagnostics_v1_4.V14ContractTests tests.test_regime_churn_diagnostics_v1_4.ExposureChangeEventTests -v
```

Expected: missing module/contracts.

- [ ] **Step 3: Implement minimal contracts and `_extract_change_events`.** Determine crossed boundaries from indices in `ALLOWED_EXPOSURES`; never infer via free-form thresholds. Validate every signal first. Compare only measured indices `1..N-1`, so the first measured target is context and never a change.

```python
def _crossed_boundaries(start, end):
    boundary_by_upper_index = {
        1: V14Boundary.ZERO_TO_THIRTY,
        2: V14Boundary.THIRTY_TO_SEVENTY,
        3: V14Boundary.SEVENTY_TO_FULL,
    }
    a, b = ALLOWED_EXPOSURES.index(start), ALLOWED_EXPOSURES.index(end)
    if b > a:
        return tuple(boundary_by_upper_index[i] for i in range(a + 1, b + 1))
    return tuple(boundary_by_upper_index[i] for i in range(a, b, -1))
```

- [ ] **Step 4: Run GREEN and commit.**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_churn_diagnostics_v1_4.V14ContractTests tests.test_regime_churn_diagnostics_v1_4.ExposureChangeEventTests -v
git add src/private_quant/backtest/regime_churn_diagnostics_v1_4.py tests/test_regime_churn_diagnostics_v1_4.py
git commit -m "feat: add V1.4 churn event contracts"
```

---

### Task 2: Rich non-overlapping whipsaw extraction with frozen-rule parity

**Files:** Modify new module/test only.

**Interfaces:** Produce `_extract_v14_whipsaw_pairs(signals, events) -> tuple[V14WhipsawPair, ...]`. Structural extraction initially sets cost fields `0.0` and `return_attribution=None`; Task 4 replaces those immutable records after accounting. Pair `crossed_boundaries` equals opener movement-order boundaries and `primary_boundary` equals opener primary boundary.

- [ ] **Step 1: Write failing `WhipsawPairTests`.** Cover latency 1/2/3/4/5 accepted, 6 rejected; wrong-direction/no-cross closers rejected; non-overlap; one closer cannot close two pairs; UP opener => failed re-entry; DOWN opener => failed de-risk.

Use parity schedule `(1.0, 0.3, 0.7, 1.0, 0.3, 1.0)` and assert 5 changes / 2 pairs. Add table:

```python
(
    (1.0, 0.3, 1.0),
    (1.0, 0.7, 0.3, 1.0),
    (0.0, 0.3, 0.0, 0.3, 0.0),
    (1.0, 0.3, 0.7, 1.0, 0.3, 1.0),
    (0.0, 0.7, 1.0, 0.3, 0.0),
)
```

For every schedule, compare `len(_extract_v14_whipsaw_pairs(...))` to unchanged `_stabilization_diagnostics(..., include_reentry_detail=False).whipsaw_pairs` using minimal state-point adapters.

- [ ] **Step 2: Run RED.**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_churn_diagnostics_v1_4.WhipsawPairTests -v
```

- [ ] **Step 3: Implement scanner exactly.** Use event positions for non-overlap but original signal indices for the five-session cutoff:

```python
position = 0
while position < len(events):
    opener = events[position]
    closer_position = None
    for candidate_position in range(position + 1, len(events)):
        closer = events[candidate_position]
        if closer.signal_index > opener.signal_index + _WHIPSAW_WINDOW:
            break
        closes = (
            closer.direction is V14Direction.UP and closer.to_exposure >= opener.from_exposure
            if opener.direction is V14Direction.DOWN
            else closer.direction is V14Direction.DOWN and closer.to_exposure <= opener.from_exposure
        )
        if closes:
            closer_position = candidate_position
            break
    if closer_position is None:
        position += 1
    else:
        # append one pair; skip opener through closer
        position = closer_position + 1
```

- [ ] **Step 4: Run GREEN, whole focused file, review parity, commit.**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_churn_diagnostics_v1_4.WhipsawPairTests -v
.\.venv\Scripts\python.exe -m unittest tests.test_regime_churn_diagnostics_v1_4 -v
git add src/private_quant/backtest/regime_churn_diagnostics_v1_4.py tests/test_regime_churn_diagnostics_v1_4.py
git commit -m "feat: extract V1.4 whipsaw anatomy pairs"
```

---

### Task 3: Same-boundary retry and churn-cluster classifiers

**Files:** Modify new module/test only.

**Interfaces:** Produce `_extract_v14_retries(events, pairs)` and `_build_v14_clusters(events, pairs)` using the exact public contracts above.

- [ ] **Step 1: Write failing `RetryTests`.** Exact 10-session closer-to-retry boundary passes; 11 fails. Retry must be `UP` and cross the same **primary** boundary. One failed pair yields at most one retry. `failed_again=True` only when the exact retry event is opener of a later extracted failed-reentry pair.

- [ ] **Step 2: Write failing `ClusterTests`.** Exact opener-to-previous-opener distance 10 joins; 11 splits. Require at least one shared crossed boundary. Assert adjacent chaining `(1,9,17)`. Assert all tied dominant boundaries retained in enum order. `schedule_change_count` counts actual events whose signal indices fall from first opener through final closer inclusive; multi-level crossings do not inflate it.

- [ ] **Step 3: Run RED.**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_churn_diagnostics_v1_4.RetryTests tests.test_regime_churn_diagnostics_v1_4.ClusterTests -v
```

- [ ] **Step 4: Implement retry extraction.** For each failed-reentry pair, scan actual events after closer until `event.signal_index > closer.signal_index + 10`; choose first `UP` event with identical primary boundary. Set latency `retry.signal_index - closer.signal_index`. Determine `failed_again` by exact opener event/index membership in later failed-reentry pairs.

- [ ] **Step 5: Implement clusters.** Join adjacent pairs only when:

```python
current.opener.signal_index - previous.opener.signal_index <= _CLUSTER_WINDOW
and bool(set(current.crossed_boundaries) & set(previous.crossed_boundaries))
```

Cluster boundary incidence counts pairs containing each crossed boundary. Keep every max-count boundary as `dominant_boundaries` in enum order. Compute inclusive actual-event schedule-change count and absolute exposure turnover. Leave cluster transaction cost at `0.0` until Task 4 replacement.

- [ ] **Step 6: Run GREEN and commit.**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_churn_diagnostics_v1_4.RetryTests tests.test_regime_churn_diagnostics_v1_4.ClusterTests -v
git add src/private_quant/backtest/regime_churn_diagnostics_v1_4.py tests/test_regime_churn_diagnostics_v1_4.py
git commit -m "feat: classify V1.4 retries and churn clusters"
```

---

### Task 4: Fixed D1 alignment, accounting, descriptive attribution, and report assembly

**Files:** Modify new module/test only.

**Interfaces:** Consume unchanged `_align_evaluation_history`, `_simulate_intervals`, `_performance_metrics`, `EvaluationStrategy.REGIME_BIL_CASH_PROXY`, `InvalidEvaluationDataError`, `_build_v1_signals`, `ALLOWED_EXPOSURES`. Produce the exact summary/report contracts above and only public function:

```python
analyze_regime_churn_v1_4(spy_bars, bil_bars, *, engine=None) -> V14WhipsawAnatomyReport
```

No caller-configurable dates, capital, cost, whipsaw, retry, or cluster windows.

- [ ] **Step 1: Write failing `D1OrchestrationTests`.** Synthetic bars must include enough pre-D1 SPY warm-up, exact D1 start/end, and matching BIL active dates. `ProtocolEngine.evaluate` asserts `qqq_bars is None` and records `as_of`. Test exact boundaries; every engine call `<= 2014-12-31`; exact public signature; duplicate/wrong-symbol/missing-BIL/non-positive/non-finite active values fail; insufficient warm-up fails; missing D1 start or end fails; no common intervals fail.

Append valid-dated 2015 objects whose `adjusted_close` property raises and assert report unchanged/no property read. A malformed future date must fail before any classifier call.

- [ ] **Step 2: Write failing accounting tests.** Hand-calculate a short synthetic path. Opening allocation cost is included in baseline `total_transaction_cost` but never becomes a schedule-change event. For each whipsaw pair, opening/closing costs equal matching `EvaluationPoint.transaction_cost` and pair cost is their sum. Cluster cost sums every actual change-event cost in the inclusive cluster span.

- [ ] **Step 3: Write failing structural/return isolation test.** Two datasets with identical dates and V1 target schedule but different SPY/BIL returns must produce identical event structural fields, pair structural fields, retries, and cluster memberships while return-attribution values differ.

- [ ] **Step 4: Implement fixed orchestration.**

```python
aligned = _align_evaluation_history(
    spy_bars, bil_bars,
    evaluation_start=_D1_START,
    evaluation_end=_D1_END,
)
if not aligned.intervals:
    raise InvalidEvaluationDataError("V1.4 D1 has no complete intervals")
if aligned.intervals[0].signal_date != _D1_START:
    raise InvalidEvaluationDataError("V1.4 D1 start boundary is missing")
if aligned.intervals[-1].return_end_date != _D1_END:
    raise InvalidEvaluationDataError("V1.4 D1 end boundary is missing")
```

Build V1 signals only through `_D1_END`, map by date, require every interval signal date, and use `maximum_long_exposure` as the baseline target. Then simulate once:

```python
points = _simulate_intervals(
    aligned.intervals,
    exposures,
    strategy=EvaluationStrategy.REGIME_BIL_CASH_PROXY,
    initial_capital=_D1_INITIAL_CAPITAL,
    transaction_cost_bps=_D1_COST_BPS,
)
metrics = _performance_metrics(
    _D1_INITIAL_CAPITAL, points, applicable_exposures=ALLOWED_EXPOSURES
)
```

- [ ] **Step 5: Attach accounting only after structural extraction.** Map `signal_date -> EvaluationPoint`, use `dataclasses.replace` to fill pair opening/closing/pair costs and cluster costs. Cost must never be an input to whipsaw/retry/cluster membership.

- [ ] **Step 6: Implement pair return attribution.** Pair window includes points from opener signal through the point whose signal date is closer signal date, inclusive. Compute:

```python
spy_return = prod(1.0 + p.spy_return for p in window) - 1.0
baseline_return = window[-1].ending_value / window[0].starting_value - 1.0
full_spy_return = spy_return
cost_drag = sum(p.transaction_cost for p in window) / window[0].starting_value
```

Keep the separately named `full_spy_comparator_return` even though its numeric path equals compounded SPY return; it is an explicitly labeled comparator in the report contract.

- [ ] **Step 7: Assemble report with exact denominator rules.** Enum-ordered boundary rows are always present. Latency rows 1..5 are always present. Primary boundary share denominator = pair count. Crossed-boundary incidence share denominator = pair count and is non-additive. Direction/failure shares denominator = pair count. Retry failure rate denominator = retry count. Retry-by-boundary rate denominator = that boundary's retry count. Clustered-whipsaw share denominator = pair count. Cluster-dominant-boundary incidence share denominator = cluster count and is non-additive. Cost shares denominator = baseline total transaction cost. Every zero denominator => `None`. Empty-pair case returns empty pair/retry/cluster tuples and a `V14ReturnSummary` containing all `None` fields.

Return summary uses `fmean` and `median` across pair attribution fields; no pairs => all `None`.

- [ ] **Step 8: Run GREEN and commit.**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_churn_diagnostics_v1_4.D1OrchestrationTests -v
.\.venv\Scripts\python.exe -m unittest tests.test_regime_churn_diagnostics_v1_4 -v
git add src/private_quant/backtest/regime_churn_diagnostics_v1_4.py tests/test_regime_churn_diagnostics_v1_4.py
git commit -m "feat: assemble V1.4 whipsaw anatomy report"
```

---

### Task 5: Exact exports, source-safety, and release-state documentation

**Files:** Modify new module/test plus `docs/MARKET_REGIME_V1.md` and `docs/ROADMAP.md` only.

**Interfaces:** Final `__all__` must equal the 15-name set in **Exact Final Public Contracts**. Do not modify package `backtest/__init__.py`.

- [ ] **Step 1: Write failing `V14PublicExportTests`, `V14SourceSafetyTests`, `V14ReleaseStateTests`.** Assert exact 15-name `__all__`; private constants/helpers excluded. AST-test new module for no provider/config/environment/broker/order/streamlit/network coupling and no QQQ input. Inspect unchanged `_build_v1_signals` and require exactly one `qqq_bars=None` keyword use with no QQQ parameter exposed by V1.4 API.

Release-state assertions require:

```text
[x] V1.4 design / D1 diagnostic infrastructure
[ ] Manual D1 Whipsaw Anatomy
[ ] Mechanism Conclusion frozen
[ ] Candidate design
[ ] 2015–2020 Candidate Validation
[ ] 2021+ Locked Evaluation
```

and explicit methodology text: Manual D1 unrun; no empirical mechanism conclusion; no candidate/winner/promotion; no real 2015+ or 2021+ V1.4 result.

- [ ] **Step 2: Run RED.** Expected: missing final exports/docs state.

- [ ] **Step 3: Add exact module `__all__`.** Do not touch `src/private_quant/backtest/__init__.py`.

- [ ] **Step 4: Update methodology.** Add concise V1.4 section to `docs/MARKET_REGIME_V1.md`: diagnosis-only purpose, frozen V1 boundary, fixed D1 constants, event/whipsaw/retry/cluster definitions, non-additive incidence semantics, structural-vs-return isolation, API future-row safety versus provider authorization, predeclared future V1/L1 gates, and explicit `Manual D1 NOT RUN`. Do not rewrite V1.2/V1.3 closure history.

- [ ] **Step 5: Update Roadmap.** Insert V1.4 before Phase 3; only design/infrastructure is checked. State candidate structures are intentionally undefined until Manual D1 is run and Mechanism Conclusion is reviewed/frozen.

- [ ] **Step 6: Run GREEN plus historical guards and commit.**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_churn_diagnostics_v1_4 -v
.\.venv\Scripts\python.exe -m unittest tests.test_regime_stabilization tests.test_regime_reentry_v1_3
git add src/private_quant/backtest/regime_churn_diagnostics_v1_4.py tests/test_regime_churn_diagnostics_v1_4.py docs/MARKET_REGIME_V1.md docs/ROADMAP.md
git commit -m "docs: expose V1.4 D1 diagnostic protocol"
```

---

### Task 6: Whole-branch verification, scope audit, independent review, and PR handoff

**Files:** No planned new files. Any repair requires a failing regression first.

- [ ] **Step 1: Run focused and full test suites fresh.**

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m unittest tests.test_regime_churn_diagnostics_v1_4 -v
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Expected: zero failures/errors.

- [ ] **Step 2: Run compile/dependency/diff checks.**

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pip check
git diff --check
git diff --check 0368fd960c23c6924a6b72b9a477f8fa39f9c0cd...HEAD
```

Expected: exit 0; `pip check` reports no broken requirements.

- [ ] **Step 3: Audit exact complete-diff allowlist.**

```powershell
git diff --name-only 0368fd960c23c6924a6b72b9a477f8fa39f9c0cd...HEAD
```

Expected exactly:

```text
docs/MARKET_REGIME_V1.md
docs/ROADMAP.md
docs/superpowers/plans/2026-08-30-regime-churn-diagnostics-v1-4-implementation.md
docs/superpowers/specs/2026-08-30-regime-churn-diagnostics-v1-4-design.md
src/private_quant/backtest/regime_churn_diagnostics_v1_4.py
tests/test_regime_churn_diagnostics_v1_4.py
```

Protected paths must have empty diff:

```powershell
git diff --exit-code 0368fd960c23c6924a6b72b9a477f8fa39f9c0cd...HEAD -- `
  src/private_quant/backtest/regime_evaluation.py `
  src/private_quant/backtest/regime_stabilization.py `
  src/private_quant/backtest/regime_reentry_v1_3.py `
  src/private_quant/backtest/__init__.py `
  src/private_quant/risk `
  src/private_quant/data `
  src/private_quant/broker `
  src/private_quant/app `
  .env .env.example pyproject.toml
```

- [ ] **Step 4: Verify source safety manually.** New module must contain no Tiingo/provider registry/config/`.env`/dotenv/`os.environ`/broker/IBKR/TWS/order/Streamlit/HTTP/network access; no QQQ input; no candidate/winner/ranking/validation/locked/promotion implementation. Synthetic post-2014 fixtures in tests are permitted; real post-2014 data access is not.

- [ ] **Step 5: Run independent whole-branch review against the spec.** Resolve every Critical/Important finding via RED -> GREEN regression, then re-review only the repaired scope. No unrelated refactor.

- [ ] **Step 6: Re-run every verification command after the final repair.** Do not claim green based on output that predates the final change.

- [ ] **Step 7: Confirm clean branch/base and push.**

```powershell
git status --short
git status --branch --short
git rev-parse HEAD
git merge-base HEAD 0368fd960c23c6924a6b72b9a477f8fa39f9c0cd
git push -u origin codex/regime-churn-diagnostics-v1-4
```

Working tree must be clean; merge base must equal approved base.

- [ ] **Step 8: Open/update one PR against `main`.** Body must say: `V1.4 D1 diagnostic infrastructure only. Manual D1 has NOT been run.` Include actual local test counts/check results; distinguish local verification from GitHub CI when no status checks exist. Do not merge.

- [ ] **Step 9: Return implementation report and STOP.** Return branch, base, final HEAD, exact changed files, focused/full test counts, compileall/pip/diff results, exact public API, review findings/repairs, and explicit confirmations: no Tiingo, no `.env`, no QQQ, no real 2015+, no 2021+, Manual D1 not run, no candidate/winner/promotion code, no protected-path changes, PR open/unmerged.

## Self-Review

- **Spec coverage:** Tasks 1-5 cover all required D1 domains: fixed protocol, point-in-time input safety, change/boundary extraction, exact inherited whipsaw parity, retries, clusters, cost/return attribution, structural-return isolation, zero/undefined semantics, exact exports, and release state. Task 6 covers full verification/scope audit.
- **Placeholder scan:** No `TBD`, `TODO`, generic "handle errors" steps, conditional public-contract decisions, or undefined neighboring interfaces remain.
- **Type consistency:** Every public nested field type is named and exported. Task 1 creates contracts used by Tasks 2-5; Task 2 creates pair records; Task 3 fills retry/cluster semantics; Task 4 fills accounting/report values; Task 5 freezes exports/docs.
- **Scope:** One subsystem only: provider-independent D1 diagnosis infrastructure. Manual D1, Mechanism Conclusion, candidate design, 2015-2020 validation, and 2021+ locked evaluation are outside this plan.
