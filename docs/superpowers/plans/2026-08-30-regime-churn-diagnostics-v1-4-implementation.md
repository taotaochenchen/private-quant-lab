# Market Regime V1.4 D1 Churn Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved provider-independent V1.4 D1 Whipsaw Anatomy engine for the frozen 2007-10-01 through 2014-12-31 Discovery Set, without running Manual D1 or creating any suppression candidate logic.

**Architecture:** One new focused module consumes the unchanged V1 signal schedule and existing V1+BIL accounting helpers, then derives immutable exposure-change events, rich non-overlapping whipsaw pairs, same-boundary retries, churn clusters, and descriptive cost/return attribution. Structural classification and return attribution remain separate. Existing V1/V1.2/V1.3 implementation files remain unchanged.

**Tech Stack:** Python 3.11+, stdlib `dataclasses` / `enum` / `statistics` / `unittest`, existing `regime_evaluation` and `regime_stabilization` helpers. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-30-regime-churn-diagnostics-v1-4-design.md`

## Global Constraints

- Approved base SHA: `0368fd960c23c6924a6b72b9a477f8fa39f9c0cd`.
- Working branch: `codex/regime-churn-diagnostics-v1-4`; the approved spec commits are already on this branch.
- D1 only. Do not implement candidate, suppression, ranking, winner, validation, locked-evaluation, or promotion contracts.
- D1 fixed protocol: initial capital USD `100000`, transaction cost `5.0` bps, Discovery `2007-10-01` through `2014-12-31`, whipsaw window `5` signal sessions, retry/cluster diagnostic windows `10` signal sessions.
- Later real Manual D1 authorization will permit SPY `2006-09-01` through `2014-12-31` and BIL `2007-10-01` through `2014-12-31`; this implementation cycle must not access Tiingo, `.env`, or any provider.
- No QQQ input. `_build_v1_signals(..., qqq_bars=None)` remains the only classifier path used by the diagnosis engine.
- Freeze `MarketRegimeEngine`, V1 score construction, thresholds `45 / 15 / -20`, regimes, confidence/QQQ behavior, and maximum-long-exposure mapping `(0.0, 0.3, 0.7, 1.0)`.
- Preserve V1+BIL residual-cash accounting: cost is charged on `signal_date` before the `signal_date -> return_end_date` return; BIL is a cash-return proxy and creates no transaction leg.
- Reuse unchanged helpers from `regime_evaluation.py` / `regime_stabilization.py` where safe. Do not refactor V1.2/V1.3 merely for reuse.
- Future-dated rows supplied to the pure API may be ignored by date without reading price content. This is an API safety property, not authorization to request post-2014 provider data.
- Structural classification must never consume return-attribution fields.
- Every implementation task uses RED -> GREEN -> review -> commit. Do not skip the initial failing test.
- Preserve `src/private_quant/backtest/__init__.py`; V1.3 established the pattern of narrow explicit module exports rather than widening package exports.
- No broker, IBKR, TWS, order, Streamlit/UI, provider registry, configuration, `.env`, `.env.example`, dependency, or market-data adapter changes.
- No raw market-data files, provider payloads, console dumps, or secrets may be committed.

## File Responsibilities

- Create `src/private_quant/backtest/regime_churn_diagnostics_v1_4.py`: fixed D1 constants, immutable public report contracts, private event/pair/retry/cluster extraction, descriptive attribution, and the single public `analyze_regime_churn_v1_4` orchestration function.
- Create `tests/test_regime_churn_diagnostics_v1_4.py`: synthetic protocol fixtures plus behavior, parity, point-in-time, public-export, source-safety, and release-state guards.
- Modify `docs/MARKET_REGIME_V1.md`: document approved V1.4 D1 methodology and explicitly state Manual D1 is unrun.
- Modify `docs/ROADMAP.md`: add V1.4 stage checklist with infrastructure checked and every empirical/candidate stage unchecked.
- Preserve all other source files. In particular do not modify `regime_evaluation.py`, `regime_stabilization.py`, `regime_reentry_v1_3.py`, `market_regime.py`, or `backtest/__init__.py`.

---

### Task 1: D1 contracts, fixed constants, and exposure-change extraction

**Files:**
- Create: `src/private_quant/backtest/regime_churn_diagnostics_v1_4.py`
- Create: `tests/test_regime_churn_diagnostics_v1_4.py`

**Interfaces:**
- Consumes: `ALLOWED_EXPOSURES`, `DEVELOPMENT_START`, `DEVELOPMENT_END`, `_V1Signal`, `_build_v1_signals` from unchanged `regime_stabilization`; `MarketRegime` from unchanged risk module.
- Produces private constants `_D1_INITIAL_CAPITAL = 100_000.0`, `_D1_COST_BPS = 5.0`, `_D1_START = date(2007, 10, 1)`, `_D1_END = date(2014, 12, 31)`, `_WHIPSAW_WINDOW = 5`, `_RETRY_WINDOW = 10`, `_CLUSTER_WINDOW = 10`.
- Produces public enums `V14Boundary` (`ZERO_TO_THIRTY`, `THIRTY_TO_SEVENTY`, `SEVENTY_TO_FULL`) and `V14Direction` (`UP`, `DOWN`).
- Produces immutable `V14ExposureChangeEvent(signal_index, signal_date, from_exposure, to_exposure, direction, primary_boundary, crossed_boundaries, v1_regime, v1_score, v1_cap)`.
- Produces private `_extract_change_events(signals)` where `signals` is the measured D1 tuple of `_V1Signal` records; the first measured target is context only and never a change event.

- [ ] **Step 1: Write failing contract and event tests.** Add `V14ContractTests` and `ExposureChangeEventTests`. Lock enum values, fixed constants, frozen/slotted records, exact allowed exposures, first-target-not-change semantics, single-level boundaries, and multi-level movement order. Include these hand-derived cases:

```python
signals = (
    _V1Signal(date(2010, 1, 1), 60, MarketRegime.BULL, 1.0),
    _V1Signal(date(2010, 1, 2), 10, MarketRegime.RISK_OFF, 0.3),
    _V1Signal(date(2010, 1, 3), -30, MarketRegime.BEAR, 0.0),
    _V1Signal(date(2010, 1, 4), 60, MarketRegime.BULL, 1.0),
)
events = module._extract_change_events(signals)
self.assertEqual(len(events), 3)
self.assertEqual(events[0].primary_boundary, module.V14Boundary.SEVENTY_TO_FULL)
self.assertEqual(
    events[0].crossed_boundaries,
    (module.V14Boundary.SEVENTY_TO_FULL, module.V14Boundary.THIRTY_TO_SEVENTY),
)
self.assertEqual(events[1].primary_boundary, module.V14Boundary.ZERO_TO_THIRTY)
self.assertEqual(
    events[2].crossed_boundaries,
    (
        module.V14Boundary.ZERO_TO_THIRTY,
        module.V14Boundary.THIRTY_TO_SEVENTY,
        module.V14Boundary.SEVENTY_TO_FULL,
    ),
)
```

Also reject non-plain dates, non-increasing signal dates, bool/non-finite scores, wrong regime types, bool/non-finite/unrecognized caps, and mutated/spoofed signal records.

- [ ] **Step 2: Run focused tests and record RED.** Run:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m unittest tests.test_regime_churn_diagnostics_v1_4.V14ContractTests tests.test_regime_churn_diagnostics_v1_4.ExposureChangeEventTests -v
```

Expected: import/module/contract failures because the V1.4 module does not exist yet.

- [ ] **Step 3: Implement minimal fixed contracts and event extraction.** Use exact enum identity and `dataclass(frozen=True, slots=True)`. Boundary movement is determined from `ALLOWED_EXPOSURES` indices, never floating arithmetic. For example:

```python
def _crossed_boundaries(start: float, end: float) -> tuple[V14Boundary, ...]:
    levels = ALLOWED_EXPOSURES
    boundary_by_upper_index = {
        1: V14Boundary.ZERO_TO_THIRTY,
        2: V14Boundary.THIRTY_TO_SEVENTY,
        3: V14Boundary.SEVENTY_TO_FULL,
    }
    start_index, end_index = levels.index(start), levels.index(end)
    if end_index > start_index:
        return tuple(boundary_by_upper_index[i] for i in range(start_index + 1, end_index + 1))
    return tuple(boundary_by_upper_index[i] for i in range(start_index, end_index, -1))
```

`_extract_change_events` validates all measured signals before returning events. It compares index `1..N-1`; no event is manufactured for the first target.

- [ ] **Step 4: Run Task 1 tests GREEN.** Re-run the exact command above. Expected: all Task 1 tests pass.

- [ ] **Step 5: Review and commit.** Confirm no provider/config/broker imports and commit:

```powershell
git add src/private_quant/backtest/regime_churn_diagnostics_v1_4.py tests/test_regime_churn_diagnostics_v1_4.py
git commit -m "feat: add V1.4 churn event contracts"
```

---

### Task 2: Rich whipsaw-pair extraction with exact V1.2/V1.3 parity

**Files:**
- Modify: `src/private_quant/backtest/regime_churn_diagnostics_v1_4.py`
- Modify: `tests/test_regime_churn_diagnostics_v1_4.py`

**Interfaces:**
- Consumes: Task 1 events plus the measured D1 `_V1Signal` schedule.
- Produces immutable private/public-detail contracts `V14PairReturnAttribution` and `V14WhipsawPair`; pair return attribution fields may initially be `None` until Task 4 fills them.
- Produces `_extract_v14_whipsaw_pairs(signals, events)` -> non-overlapping tuple of `V14WhipsawPair` using the exact inherited five-signal-session rule.
- Pair fields include `opener`, `closer`, `latency_sessions`, `primary_boundary`, `crossed_boundaries`, `failed_reentry`, `failed_derisk`, and placeholder cost/return fields filled later without changing pair identity.

- [ ] **Step 1: Write failing whipsaw tests.** Add `WhipsawPairTests`. Cover: exact latency 1/2/3/4/5 accepted; latency 6 rejected; opposite direction that does not return/cross pre-opener exposure does not close; pairs non-overlap; a closer cannot close two pairs; UP opener marks failed re-entry; DOWN opener marks failed de-risk. Add literal parity schedule:

```python
caps = (1.0, 0.3, 0.7, 1.0, 0.3, 1.0)
# Existing V1.2 rule: 5 schedule changes, 2 non-overlapping whipsaw pairs.
```

Construct minimal state-point adapters exposing `signal_date`, `overlay_exposure`, and `v1_maximum_long_exposure`, call unchanged `_stabilization_diagnostics(..., include_reentry_detail=False)`, and assert pair-count parity.

- [ ] **Step 2: Add table-driven parity cases before implementation.** Include at least these target schedules, all with monotonically increasing dates:

```python
(
    (1.0, 0.3, 1.0),
    (1.0, 0.7, 0.3, 1.0),
    (0.0, 0.3, 0.0, 0.3, 0.0),
    (1.0, 0.3, 0.7, 1.0, 0.3, 1.0),
    (0.0, 0.7, 1.0, 0.3, 0.0),
)
```

For every schedule, assert `len(_extract_v14_whipsaw_pairs(...)) == _stabilization_diagnostics(...).whipsaw_pairs`.

- [ ] **Step 3: Run whipsaw tests RED.** Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_churn_diagnostics_v1_4.WhipsawPairTests -v
```

Expected: missing pair contracts/extractor.

- [ ] **Step 4: Implement the inherited scanner exactly.** Operate on change events ordered by `signal_index`, but enforce the five-session bound with original signal indices, not number of changes. Pseudocode must remain equivalent to V1.2:

```python
position = 0
while position < len(events):
    opener = events[position]
    closer_position = None
    for candidate_position in range(position + 1, len(events)):
        closer = events[candidate_position]
        if closer.signal_index > opener.signal_index + _WHIPSAW_WINDOW:
            break
        if opener.direction is DOWN:
            closes = closer.direction is UP and closer.to_exposure >= opener.from_exposure
        else:
            closes = closer.direction is DOWN and closer.to_exposure <= opener.from_exposure
        if closes:
            closer_position = candidate_position
            break
    if closer_position is None:
        position += 1
    else:
        # create one pair, then skip through the closer
        position = closer_position + 1
```

For pair `crossed_boundaries`, preserve the opener's movement-order tuple. `primary_boundary` is `opener.primary_boundary`. `failed_reentry = opener.direction is UP`; `failed_derisk = opener.direction is DOWN` because pair construction already proves return/cross semantics.

- [ ] **Step 5: Run Task 2 GREEN and full focused file.** Run WhipsawPairTests, then the whole V1.4 test file. Expected: all implemented groups pass.

- [ ] **Step 6: Commit.**

```powershell
git add src/private_quant/backtest/regime_churn_diagnostics_v1_4.py tests/test_regime_churn_diagnostics_v1_4.py
git commit -m "feat: extract V1.4 whipsaw anatomy pairs"
```

---

### Task 3: Same-boundary retries and churn clusters

**Files:**
- Modify: `src/private_quant/backtest/regime_churn_diagnostics_v1_4.py`
- Modify: `tests/test_regime_churn_diagnostics_v1_4.py`

**Interfaces:**
- Produces immutable `V14RetryEvent(failed_pair_index, retry_event, primary_boundary, retry_latency_sessions, failed_again)`.
- Produces `_extract_v14_retries(events, pairs)` -> tuple of first retries only, defined only from failed-reentry pairs.
- Produces immutable `V14ChurnCluster(start_date, end_date, start_opener_index, end_closer_index, pair_indices, pair_count, schedule_change_count, boundaries, dominant_boundaries, failed_reentry_count, failed_derisk_count, absolute_exposure_turnover, transaction_cost)`.
- Produces `_build_v14_clusters(events, pairs)` -> tuple of adjacent-pair chained clusters.

- [ ] **Step 1: Write retry tests RED.** Add `RetryTests`. Lock exact 10-signal-session boundary, reject day 11, require an UP retry that crosses the same `primary_boundary`, ignore a different-boundary UP event, and create at most one retry for one failed pair. Retry failure must be determined by identity/index membership: the retry event itself is the opener of a later extracted failed-reentry pair. Do not rescan returns or invent another window.

Example:

```python
# 30 -> 70 fails back to 30; next 30 -> 70 within 10 sessions is retry.
self.assertEqual(retries[0].primary_boundary, V14Boundary.THIRTY_TO_SEVENTY)
self.assertTrue(retries[0].failed_again)
```

- [ ] **Step 2: Write cluster tests RED.** Add `ClusterTests`. Cover exact 10-session opener distance, 11-session split, shared-crossed-boundary requirement, adjacent-pair chaining `(1, 9, 17)`, deterministic tied dominant boundaries, and actual schedule-change count across inclusive first-opener-to-final-closer indices. Explicitly assert multi-level boundary crossings do not inflate `schedule_change_count`.

- [ ] **Step 3: Run RetryTests and ClusterTests RED.** Expected: missing retry/cluster contracts/functions.

- [ ] **Step 4: Implement retry extraction.** For every pair with `failed_reentry=True`, inspect actual schedule-change events after its closer. Stop when `event.signal_index > pair.closer.signal_index + _RETRY_WINDOW`. Select the first `UP` event whose `primary_boundary` equals the failed pair's primary boundary. `failed_again` is true only if that exact event object/index equals the opener of a later failed-reentry pair.

- [ ] **Step 5: Implement adjacent-pair cluster formation.** Join current pair when both conditions hold relative to the immediately previous pair:

```python
within_window = current.opener.signal_index - previous.opener.signal_index <= _CLUSTER_WINDOW
shares_boundary = bool(set(current.crossed_boundaries) & set(previous.crossed_boundaries))
```

For each finalized cluster:
- `pair_indices` are indices into the immutable pair tuple.
- `boundaries` are enum-order sorted union of all crossed boundaries.
- dominant boundaries are all boundaries tied for maximum pair incidence, in enum definition order.
- `schedule_change_count` counts actual events with `first_opener.signal_index <= event.signal_index <= final_closer.signal_index`.
- `absolute_exposure_turnover` sums `abs(to_exposure - from_exposure)` across those actual events.
- keep `transaction_cost=0.0` until Task 4 attaches accounting; do not classify clusters using cost.

- [ ] **Step 6: Run Task 3 groups GREEN, then whole V1.4 file.** Expected: retry and cluster semantics pass including exact boundaries and ties.

- [ ] **Step 7: Commit.**

```powershell
git add src/private_quant/backtest/regime_churn_diagnostics_v1_4.py tests/test_regime_churn_diagnostics_v1_4.py
git commit -m "feat: classify V1.4 retries and churn clusters"
```

---

### Task 4: Fixed D1 alignment, continuous accounting, descriptive attribution, and report assembly

**Files:**
- Modify: `src/private_quant/backtest/regime_churn_diagnostics_v1_4.py`
- Modify: `tests/test_regime_churn_diagnostics_v1_4.py`

**Interfaces:**
- Consumes unchanged `_align_evaluation_history`, `_simulate_intervals`, `_performance_metrics`, `EvaluationStrategy.REGIME_BIL_CASH_PROXY`, `InvalidEvaluationDataError` from `regime_evaluation`, plus `_build_v1_signals` and `ALLOWED_EXPOSURES`.
- Produces immutable `V14Coverage(symbol, first_date, last_date, rows)` for sanitized in-memory input coverage through D1 cutoff.
- Produces immutable summary records for boundary counts, latency counts, direction counts, retry-by-boundary, and cluster summary. Keep them small/frozen rather than mutable dicts.
- Produces `V14WhipsawAnatomyReport` containing the exact spec-required coverage/accounting, pair/retry/cluster records, rate/breakdown summaries, cost attribution, and descriptive return attribution.
- Produces the only public orchestration function:

```python
analyze_regime_churn_v1_4(spy_bars, bil_bars, *, engine=None) -> V14WhipsawAnatomyReport
```

No capital/cost/date parameters are accepted.

- [ ] **Step 1: Write orchestration/input-safety tests RED.** Add `D1OrchestrationTests`. Build deterministic synthetic SPY warm-up plus exact D1 boundaries and matching BIL dates. Inject a `ProtocolEngine` whose `evaluate` asserts `qqq_bars is None` and records dates. Tests must assert:
  - analysis start/end fixed to `2007-10-01` / `2014-12-31`;
  - first and last common complete interval are not silently shifted;
  - all engine `as_of` dates are `<= 2014-12-31`;
  - public signature exposes only `spy_bars`, `bil_bars`, keyword-only `engine`;
  - appending a valid-dated 2015 object whose `adjusted_close` property raises leaves the report unchanged and never reads the property;
  - malformed/unparseable dates fail before any classifier call;
  - duplicate active dates, wrong symbols, missing BIL active dates, non-positive/non-finite active closes, insufficient SPY warm-up, missing D1 start/end, and no common intervals fail closed.

Use a future fixture like:

```python
class FutureBar:
    symbol = "SPY"
    trading_date = date(2015, 1, 2)
    @property
    def adjusted_close(self):
        raise AssertionError("future price content read")
```

- [ ] **Step 2: Write accounting/attribution tests RED.** Use 3-6 synthetic intervals with hand-calculated returns and exposure changes. Assert opening allocation cost remains in baseline total cost but is not a D1 schedule-change event. Assert a pair's opening/closing costs equal the corresponding `EvaluationPoint.transaction_cost` values, pair cost is their sum, and cluster cost sums all actual schedule-change point costs inside its inclusive event span without changing cluster membership.

- [ ] **Step 3: Write return-attribution isolation test RED.** Build identical signal/exposure schedules with different SPY/BIL returns. Assert event, pair structural fields, retries, and cluster memberships are exactly equal while `V14PairReturnAttribution` values differ. This proves returns cannot influence structural classification.

- [ ] **Step 4: Implement fixed alignment/orchestration.** Call `_align_evaluation_history(spy_bars, bil_bars, evaluation_start=_D1_START, evaluation_end=_D1_END)`. Explicitly require:
  - `aligned.intervals[0].signal_date == _D1_START`;
  - `aligned.intervals[-1].return_end_date == _D1_END`;
  - at least one complete interval.

Build V1 signals only through `_D1_END`, map them by date, and require every interval `signal_date` has a V1 signal. Measured signals are exactly aligned interval signal dates. Exposure schedule is `signal.maximum_long_exposure`.

Simulate once:

```python
points = _simulate_intervals(
    aligned.intervals,
    exposures,
    strategy=EvaluationStrategy.REGIME_BIL_CASH_PROXY,
    initial_capital=_D1_INITIAL_CAPITAL,
    transaction_cost_bps=_D1_COST_BPS,
)
metrics = _performance_metrics(_D1_INITIAL_CAPITAL, points, applicable_exposures=ALLOWED_EXPOSURES)
```

Do not invoke any candidate or V1.3 overlay function.

- [ ] **Step 5: Attach cost attribution after structural extraction.** Create a `point_by_signal_date` map and replace/finalize pair/cluster immutable records with costs derived from the baseline points. Never feed costs back into pair/retry/cluster extraction.

- [ ] **Step 6: Implement descriptive pair returns.** For each pair, use the baseline `EvaluationPoint` sequence from opener signal through the interval whose signal date is the closer signal date, inclusive. Compute:
  - SPY cumulative return as product of `(1 + point.spy_return)` minus 1;
  - baseline portfolio return from the opener point's pre-cost `starting_value` to closer point `ending_value` minus 1;
  - full-SPY comparator over the same interval sequence from SPY returns only;
  - transaction-cost drag as sum of stored point costs over the pair window divided by opener starting value.

These fields are descriptive only.

- [ ] **Step 7: Assemble exact report summaries.** Required semantics:
  - `schedule_change_count = len(events)`;
  - `whipsaw_pair_count = len(pairs)`;
  - `whipsaw_rate = pair_count / schedule_change_count` else `None`;
  - primary-boundary counts add to total pairs;
  - all-crossed-boundary incidence is explicitly non-additive and may exceed pair count when summed;
  - latency buckets 1..5 are always present;
  - within-2/within-3 shares are `None` when no pairs;
  - retry failure rate is `None` when no retries;
  - zero-whipsaw report returns empty tuples and no fabricated rates;
  - baseline annualized turnover and total cost come from the existing continuous metrics.

- [ ] **Step 8: Run orchestration/accounting tests GREEN, then whole focused file.** Expected: all D1 behavior groups pass with no network/provider access.

- [ ] **Step 9: Commit.**

```powershell
git add src/private_quant/backtest/regime_churn_diagnostics_v1_4.py tests/test_regime_churn_diagnostics_v1_4.py
git commit -m "feat: assemble V1.4 whipsaw anatomy report"
```

---

### Task 5: Narrow exports, source-safety guards, and release-state documentation

**Files:**
- Modify: `src/private_quant/backtest/regime_churn_diagnostics_v1_4.py`
- Modify: `tests/test_regime_churn_diagnostics_v1_4.py`
- Modify: `docs/MARKET_REGIME_V1.md`
- Modify: `docs/ROADMAP.md`

**Interfaces:**
- New module explicit `__all__` includes only the public diagnosis contracts/enums needed to consume the report and `analyze_regime_churn_v1_4`.
- Do not export private constants, extraction helpers, candidate-like contracts, or anything from package `backtest/__init__.py`.

- [ ] **Step 1: Write public-export/source-safety/release-state tests RED.** Add `V14PublicExportTests`, `V14SourceSafetyTests`, and `V14ReleaseStateTests`.

Public export expected set should be exact and small, for example:

```python
expected = {
    "V14Boundary",
    "V14Direction",
    "V14ExposureChangeEvent",
    "V14WhipsawPair",
    "V14RetryEvent",
    "V14ChurnCluster",
    "V14WhipsawAnatomyReport",
    "analyze_regime_churn_v1_4",
}
self.assertEqual(set(module.__all__), expected)
```

If summary/coverage helper records must be public because they appear as report field types, add only those exact immutable record names and update this expected set explicitly. Never export extraction functions or protocol constants.

AST/source tests must reject imports/calls/attributes containing provider/config/environment/broker/order/streamlit/network terms and reject QQQ parameters. Also inspect reused `_build_v1_signals` to confirm the only QQQ use remains literal `qqq_bars=None`.

Release-state test must require Roadmap text equivalent to:

```text
[x] V1.4 design / D1 diagnostic infrastructure
[ ] Manual D1 Whipsaw Anatomy
[ ] Mechanism Conclusion frozen
[ ] Candidate design
[ ] 2015–2020 Candidate Validation
[ ] 2021+ Locked Evaluation
```

and methodology text that Manual D1 has not been run and no empirical V1.4 mechanism conclusion/candidate/winner exists.

- [ ] **Step 2: Run these tests RED.** Expected: missing `__all__`/docs state.

- [ ] **Step 3: Add explicit module `__all__`.** Do not change `src/private_quant/backtest/__init__.py`.

- [ ] **Step 4: Update `docs/MARKET_REGIME_V1.md`.** Add a concise V1.4 section documenting:
  - diagnosis-only purpose and frozen V1 boundary;
  - fixed D1 period/cost/windows;
  - event, whipsaw, retry, cluster definitions;
  - structural-vs-return attribution separation;
  - future-row API safety versus provider authorization distinction;
  - future V1/L1 gates as predeclared protocol only;
  - explicit `Manual D1 NOT RUN`, no mechanism conclusion, no candidate, no 2015+ empirical V1.4 result, no 2021+ V1.4 data, and no execution implication.

Do not rewrite V1.2/V1.3 closure history.

- [ ] **Step 5: Update `docs/ROADMAP.md`.** Insert V1.4 before Phase 3 with exactly the six-stage checklist from the spec. Mark only design/infrastructure complete. Leave Manual D1, Mechanism Conclusion, Candidate design, Validation, and Locked Evaluation unchecked. State candidate structures are intentionally undefined until D1 is reviewed.

- [ ] **Step 6: Run Task 5 tests GREEN plus existing release guards.** Run the V1.4 focused file and existing V1.2/V1.3 test files to ensure historical documentation guards remain valid.

- [ ] **Step 7: Commit.**

```powershell
git add src/private_quant/backtest/regime_churn_diagnostics_v1_4.py tests/test_regime_churn_diagnostics_v1_4.py docs/MARKET_REGIME_V1.md docs/ROADMAP.md
git commit -m "docs: expose V1.4 D1 diagnostic protocol"
```

---

### Task 6: Whole-branch verification, scope audit, and PR handoff

**Files:** No planned new implementation files. Only regression repairs are allowed if fresh verification exposes a defect; write a failing regression first for any repair.

**Interfaces:** The branch is reviewable only if the complete diff is limited to the approved spec, plan, new V1.4 module/test file, and two methodology/roadmap files.

- [ ] **Step 1: Run focused V1.4 suite.**

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m unittest tests.test_regime_churn_diagnostics_v1_4 -v
```

Expected: zero failures/errors.

- [ ] **Step 2: Run full repository suite.**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Expected: zero failures/errors.

- [ ] **Step 3: Run compile/dependency/diff checks.**

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pip check
git diff --check
git diff --check 0368fd960c23c6924a6b72b9a477f8fa39f9c0cd...HEAD
```

Expected: all commands exit 0; `pip check` reports no broken requirements.

- [ ] **Step 4: Audit complete diff allowlist.**

```powershell
git diff --name-only 0368fd960c23c6924a6b72b9a477f8fa39f9c0cd...HEAD
```

Expected paths only:

```text
docs/MARKET_REGIME_V1.md
docs/ROADMAP.md
docs/superpowers/plans/2026-08-30-regime-churn-diagnostics-v1-4-implementation.md
docs/superpowers/specs/2026-08-30-regime-churn-diagnostics-v1-4-design.md
src/private_quant/backtest/regime_churn_diagnostics_v1_4.py
tests/test_regime_churn_diagnostics_v1_4.py
```

Then require empty diffs for protected implementation areas:

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

- [ ] **Step 5: Verify source-safety facts manually.** Confirm no string/import/call path for `Tiingo`, `MarketDataProvider`, provider registry, `.env`, `dotenv`, `os.environ`, broker, IBKR/TWS, order, Streamlit, HTTP/network, QQQ input, candidate, winner, ranking, validation runner, or locked runner exists in the V1.4 module. Synthetic 2015+ fixtures in tests are allowed; real 2015+/2021+ data access is not.

- [ ] **Step 6: Run independent whole-branch code review.** Use a fresh reviewer against the spec. Resolve every Critical/Important finding with RED -> GREEN regression coverage. Do not accept speculative refactors unrelated to D1.

- [ ] **Step 7: Re-run the entire verification stack after the final repair commit.** Do not rely on earlier green output after any code/doc change.

- [ ] **Step 8: Confirm branch status and push.**

```powershell
git status --short
git status --branch --short
git rev-parse HEAD
git merge-base HEAD 0368fd960c23c6924a6b72b9a477f8fa39f9c0cd
git push -u origin codex/regime-churn-diagnostics-v1-4
```

Working tree must be clean. The merge base must be the approved base.

- [ ] **Step 9: Open/update one PR against `main`.** PR body must say plainly: `V1.4 D1 diagnostic infrastructure only. Manual D1 has NOT been run.` Include local verification counts and state that GitHub CI status is separate if no checks exist. Do not merge.

- [ ] **Step 10: Return implementation report and STOP.** Return branch, base, final HEAD, exact changed files, focused/full test counts, compileall/pip/diff results, public API, review findings/repairs, and explicit confirmations: no Tiingo, no `.env`, no QQQ, no real 2015+, no 2021+, Manual D1 not run, no candidate/winner/promotion code, no protected-path changes, PR open/unmerged.

## Self-Review

- Spec coverage: Tasks 1-5 cover all 33 required D1 test domains, fixed protocol, point-in-time safety, event/boundary semantics, exact inherited whipsaw parity, retries, clusters, accounting, return isolation, zero/undefined behavior, narrow exports, and release-state documentation. Task 6 covers the mandated full verification and scope audit.
- Placeholder scan: no `TBD`, `TODO`, "implement later", generic error-handling placeholders, or undefined neighboring interfaces remain.
- Type consistency: Task 1 defines events/enums used by Tasks 2-5; Task 2 defines pair records used by Tasks 3-5; Task 3 defines retries/clusters; Task 4 defines report/summary/coverage contracts and the only public orchestration function; Task 5 freezes exports/docs. No task requires a candidate or locked-evaluation type.
- Scope: one subsystem only — provider-independent D1 diagnosis infrastructure. Manual D1, Mechanism Conclusion, candidate design, 2015-2020 validation, and 2021+ locked evaluation are explicitly outside this plan.
