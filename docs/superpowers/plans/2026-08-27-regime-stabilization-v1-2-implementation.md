# Market Regime Stabilization & Re-entry V1.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic Market Regime V1.2 research overlay that preserves immediate de-risking, tests exactly 12 confirmed-reentry candidates through 2020, freezes at most one winner, and evaluates only that winner on a separate 2021+ locked period.

**Architecture:** Add a provider-independent `regime_stabilization.py` module downstream of the unchanged `MarketRegimeEngine`. Reuse V1.1 SPY/BIL alignment, interval simulation, transaction-cost accounting, and performance metrics. Keep candidate selection, locked evaluation, and post-selection diagnostics as separate entry points so locked-period information cannot feed selection.

**Tech Stack:** Python 3.11+, standard library, existing `PriceBar`, `MarketRegimeEngine`, V1.1 backtest helpers, `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-27-regime-stabilization-v1-2-design.md`

## Global Constraints

- Freeze Market Regime V1 scoring, weights, `45 / 15 / -20` thresholds, regime definitions, confidence, QQQ behavior, and `1.0 / 0.7 / 0.3 / 0.0` cap mapping.
- V1.2 reads only V1 `score`, `regime`, and `maximum_long_exposure`.
- No QQQ input or confidence dependency in the stabilization module.
- Allowed overlay exposures: `0.0, 0.3, 0.7, 1.0` only; overlay may never exceed V1 cap.
- De-risk immediately; re-enter at most one exposure level per signal session.
- Fixed candidates: `(margin, confirmation_sessions)` from `{0,5,10} x {1,2,3,5}` only.
- Development: `2007-10-01..2014-12-31`; Validation: `2015-01-01..2020-12-31`; Combined selection: `2007-10-01..2020-12-31`; Locked: `2021-01-01..latest complete common interval`.
- Primary baseline: unchanged Regime V1 + BIL residual-cash proxy at `5 bps`.
- Selection gates: Dev DD >= `-0.20`; Val DD >= `-0.20`; Combined CAGR strictly above baseline; Dev and Val CAGR each no more than `0.005` below baseline; Combined turnover <= baseline * `0.85`; Combined whipsaw count <= baseline * `0.80`.
- Winner return tie band: `0.0005`; then lower whipsaw count, better drawdown, smaller confirmation, smaller margin.
- Locked promotion gates: DD >= `-0.20`; CAGR >= baseline + `0.0025`; turnover <= baseline * `0.85`; whipsaw count <= baseline * `0.80`.
- Preserve V1.1 `signal_date -> return_end_date`, opening-cost-from-zero, BIL proxy, and metric formulas.
- No Streamlit, provider construction, `.env` access in tests, TWS/IBKR, broker/order/paper-trading changes.
- Stop before manual Tiingo Stage 1 until explicitly authorized.

## File Map

- Create `src/private_quant/backtest/regime_stabilization.py`.
- Create `tests/test_regime_stabilization.py`.
- Modify `src/private_quant/backtest/__init__.py`.
- Modify `docs/MARKET_REGIME_V1.md` and `docs/ROADMAP.md`.
- Do not modify `src/private_quant/risk/market_regime.py`, broker/IBKR/order/paper-trading/configuration/Streamlit files, `.env`, or `.env.example`.

---

### Task 1: Fixed Contracts and Protocol Constants

**Files:**
- Create: `src/private_quant/backtest/regime_stabilization.py`
- Create: `tests/test_regime_stabilization.py`

**Produces:** `StabilizationCandidate`, `BoundaryConfirmationState`, `StabilizationTransition`, `StabilizationSignalPoint`, `StabilizationDiagnostics`, `ResearchPeriod`, `GateStatus`, `GateResult`, `SelectionStatus`, `PromotionStatus`, fixed dates and thresholds.

- [ ] **Step 1: Write failing contract tests**

```python
class StabilizationContractTests(unittest.TestCase):
    def test_fixed_grid(self):
        self.assertEqual(
            FIXED_STABILIZATION_CANDIDATES,
            tuple(StabilizationCandidate(m, c) for m in (0, 5, 10) for c in (1, 2, 3, 5)),
        )
        self.assertEqual(len(FIXED_STABILIZATION_CANDIDATES), 12)

    def test_candidate_validation(self):
        for args in ((-1, 1), (7, 1), (5, 4), (5, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                StabilizationCandidate(*args)

    def test_period_constants(self):
        self.assertEqual(DEVELOPMENT_START, date(2007, 10, 1))
        self.assertEqual(DEVELOPMENT_END, date(2014, 12, 31))
        self.assertEqual(VALIDATION_START, date(2015, 1, 1))
        self.assertEqual(SELECTION_END, date(2020, 12, 31))
        self.assertEqual(LOCKED_START, date(2021, 1, 1))
```

- [ ] **Step 2: Verify RED**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_regime_stabilization.py" -v
```

Expected: import failure for the new module.

- [ ] **Step 3: Implement constants and frozen contracts**

```python
ALLOWED_EXPOSURES = (0.0, 0.3, 0.7, 1.0)
MARGINS = (0, 5, 10)
CONFIRMATION_SESSIONS = (1, 2, 3, 5)
DEVELOPMENT_START = date(2007, 10, 1)
DEVELOPMENT_END = date(2014, 12, 31)
VALIDATION_START = date(2015, 1, 1)
SELECTION_END = date(2020, 12, 31)
LOCKED_START = date(2021, 1, 1)
PRIMARY_COST_BPS = 5.0
SPLIT_CAGR_ALLOWANCE = 0.005
WINNER_CAGR_TIE_BAND = 0.0005
LOCKED_CAGR_IMPROVEMENT = 0.0025
TURNOVER_REDUCTION = 0.15
WHIPSAW_REDUCTION = 0.20
POST_SELECTION_COST_BPS = (0.0, 2.0, 5.0, 10.0)

@dataclass(frozen=True, slots=True)
class StabilizationCandidate:
    margin: int
    confirmation_sessions: int
    def __post_init__(self):
        if self.margin not in MARGINS or self.confirmation_sessions not in CONFIRMATION_SESSIONS:
            raise ValueError("candidate is outside the fixed V1.2 grid")

FIXED_STABILIZATION_CANDIDATES = tuple(
    StabilizationCandidate(m, c) for m in MARGINS for c in CONFIRMATION_SESSIONS
)
```

Add the remaining frozen dataclasses/enums exactly as specified by the design; no provider, credential, broker, or account fields.

- [ ] **Step 4: Verify GREEN** using the focused command.

- [ ] **Step 5: Commit**

```powershell
git add src/private_quant/backtest/regime_stabilization.py tests/test_regime_stabilization.py
git commit -m "feat: add regime stabilization v1.2 contracts"
```

---

### Task 2: Deterministic State Machine

**Files:** same module/test.

**Produces:** `_V1Signal`, `_update_confirmations`, `_next_overlay_exposure`, `_run_stabilization_state_machine`.

- [ ] **Step 1: Write failing state tests** covering these exact schedules:

```python
# candidate (0,1), constant strong BULL cap 1.0 from zero -> (0.3, 0.7, 1.0)
# candidate (0,3), five strong BULL sessions -> (0.0, 0.0, 0.3, 0.7, 1.0)
# prior 0.7 then V1 cap 0.0 -> immediate 0.0 and DE_RISK, no same-session upgrade
# candidate (5,2), scores -15,-16,-15,-15 -> to_30 counter 1,0,1,2
# every output exposure belongs to ALLOWED_EXPOSURES and is <= current V1 cap
```

Construct `_V1Signal` values directly with literal dates and `MarketRegime` values; do not mock portfolio returns in this task.

- [ ] **Step 2: Verify RED** with the focused suite.

- [ ] **Step 3: Implement exact update order**

```python
def _update_confirmations(score, candidate, prior):
    def update(threshold, value):
        if score >= threshold + candidate.margin:
            return min(candidate.confirmation_sessions, value + 1)
        return 0
    return BoundaryConfirmationState(
        to_30=update(-20, prior.to_30),
        to_70=update(15, prior.to_70),
        to_100=update(45, prior.to_100),
    )
```

Then: update counters first; if `v1_cap < prior_overlay`, set directly to cap and stop; otherwise permit only `0->0.3`, `0.3->0.7`, or `0.7->1.0` when the corresponding updated counter has reached `confirmation_sessions` and V1 cap permits that level.

- [ ] **Step 4: Verify GREEN**.

- [ ] **Step 5: Commit** `feat: add stabilization state machine`.

---

### Task 3: Point-in-Time V1 Signal Stream and State Warm-up

**Files:** same module/test.

**Produces:** `_build_v1_signals(spy_history, *, final_signal_date, engine=None)` and `_measured_state_points(state_points, signal_dates)`.

- [ ] **Step 1: Write failing tests** proving:
  - first V1 signal uses the 252nd SPY observation;
  - `MarketRegimeEngine.evaluate` receives only SPY through each `as_of`;
  - `qqq_bars` is always `None`;
  - a valid-dated malformed SPY price after `final_signal_date` does not affect the earlier stream;
  - missing measured signal date is a hard deterministic error.

Use a local `RecordingEngine.evaluate()` that returns `SimpleNamespace(score=60, regime=MarketRegime.BULL, maximum_long_exposure=1.0)` and records inputs.

- [ ] **Step 2: Verify RED**.

- [ ] **Step 3: Implement cutoff-first signal generation**

```python
def _build_v1_signals(spy_history, *, final_signal_date, engine=None):
    classifier = engine or MarketRegimeEngine()
    dated = tuple((_canonical_trading_date(bar), bar) for bar in spy_history)
    visible = tuple(bar for day, bar in dated if day <= final_signal_date)
    if len(visible) < 252:
        raise InvalidEvaluationDataError("SPY history has insufficient V1 warm-up")
    output = []
    for index in range(251, len(visible)):
        as_of = _canonical_trading_date(visible[index])
        result = classifier.evaluate(visible[: index + 1], as_of=as_of, qqq_bars=None)
        if result.maximum_long_exposure not in ALLOWED_EXPOSURES:
            raise InvalidEvaluationDataError("V1 exposure mapping is invalid")
        output.append(_V1Signal(as_of, result.score, result.regime, result.maximum_long_exposure))
    return tuple(output)
```

Selection and locked orchestration must call V1.1 `_align_evaluation_history` first so requested end boundaries are applied before this helper sees active SPY history.

- [ ] **Step 4: Verify GREEN**.

- [ ] **Step 5: Commit** `feat: add point in time stabilization signals`.

---

### Task 4: Reuse V1.1 Accounting and Continuous Period Slices

**Files:** same module/test.

**Produces:** `_simulate_bil_cash_schedule`, `_slice_period_points`, `_rebased_period_metrics`.

- [ ] **Step 1: Write failing numeric tests** using V1.1 `_PriceInterval`:
  - with initial capital 100, first target 0.7 and 5 bps, opening cost is exactly `0.035`;
  - unchanged second 0.7 target has zero new exposure cost;
  - a period beginning on a real `0.3->0.7` transition retains `exposure_change == 0.4` rather than inventing a new opening trade;
  - a two-interval 100% schedule with returns `+10%,-5%` and no cost rebases from 200 to initial 100 and final `104.5`.

- [ ] **Step 2: Verify RED**.

- [ ] **Step 3: Implement a thin bridge**

```python
def _simulate_bil_cash_schedule(aligned, exposures, *, cost_bps=5.0, initial_capital=100_000.0):
    return _simulate_intervals(
        aligned.intervals,
        exposures,
        strategy=EvaluationStrategy.REGIME_BIL_CASH_PROXY,
        initial_capital=initial_capital,
        transaction_cost_bps=cost_bps,
    )
```

Slice only intervals whose `signal_date >= start` and `return_end_date <= end`. For rebasing, multiply `starting_value`, `ending_value`, and `transaction_cost` by `100 / first.starting_value`, preserve returns/exposures/exposure changes, then call V1.1 `_performance_metrics(100.0, rebased_points, applicable_exposures=ALLOWED_EXPOSURES)`.

- [ ] **Step 4: Run focused suite and `tests.test_regime_evaluation`**; both pass.

- [ ] **Step 5: Commit** `feat: bridge stabilization to v1.1 accounting`.

---

### Task 5: Schedule Diagnostics

**Files:** same module/test.

**Produces:** `_stabilization_diagnostics(state_points, *, start, end, include_reentry_detail)`.

- [ ] **Step 1: Write failing literal-schedule tests** for:

```text
70 -> 30 -> 70 within five sessions = 1 whipsaw
30 -> 70 -> 30 within five sessions = 1 whipsaw
0 -> 30 -> 70 -> 100 = 0 whipsaws
100 -> 70, then return to 100 only after more than five signal sessions = 0 whipsaws
constant schedule = 0 schedule changes and whipsaw_rate is None
first available target alone is never counted as a schedule change
```

Also add one seven-session explicit `StabilizationSignalPoint` fixture containing one completed defensive-to-100 recovery and one later incomplete recovery; assert the exact completed duration and incomplete count. Add an explicit boundary-confirmation fixture and assert the exact re-entry lag from first qualifying session after reset to actual boundary crossing.

- [ ] **Step 2: Verify RED**.

- [ ] **Step 3: Implement diagnostics**:
  - compare each signal target to its preceding signal target;
  - whipsaw opener searches only the next five signal indices;
  - downward opener closes on an upward change returning to or above pre-opener exposure;
  - upward opener closes on a downward change returning to or below pre-opener exposure;
  - pairs are non-overlapping and scanning resumes after the closer;
  - count in-period sessions where overlay `<` V1 cap;
  - completed lags/durations use signal-session counts; incomplete recoveries get no fabricated duration;
  - use `fmean`/`median` only for non-empty tuples; otherwise `None`.

- [ ] **Step 4: Verify GREEN**.

- [ ] **Step 5: Commit** `feat: add stabilization diagnostics`.

---

### Task 6: Fixed Candidate Selection Through 2020

**Files:** same module/test.

**Produces:** `CandidatePeriodResult`, `CandidateQualification`, `CandidateSelectionResult`, public `select_regime_stabilization_candidate(spy_bars, bil_bars, *, engine=None, initial_capital=100_000.0)`.

- [ ] **Step 1: Write failing pure gate/ranking tests**.

Create literal `PerformanceMetrics` and `StabilizationDiagnostics` fixtures, then assert:
  - Validation DD `-0.201` fails;
  - Combined CAGR equal to baseline fails because it must be strictly greater;
  - Dev/Val exactly baseline minus `0.005` pass their split-return gates;
  - turnover exactly baseline * `0.85` passes;
  - whipsaw count exactly baseline * `0.80` passes when integer arithmetic makes the value exact;
  - baseline turnover `0` or baseline whipsaw `0` produces `NOT_EVALUABLE` and candidate cannot qualify;
  - candidates within `0.0005` of top CAGR enter the tie set;
  - tie order is whipsaw, absolute drawdown, confirmation length, margin.

- [ ] **Step 2: Verify RED**.

- [ ] **Step 3: Implement qualification and ranking** with decimal-return units and the exact formulas in Global Constraints. Store one `GateResult` per gate and set `qualified=True` only when every required gate is `PASS`.

- [ ] **Step 4: Write failing orchestration/isolation tests**:
  - public signature is exactly `(spy_bars, bil_bars, engine, initial_capital)`;
  - result contains all 12 candidates in fixed-grid order;
  - valid-dated malformed SPY/BIL price content in 2021 cannot change selection ending 2020-12-31;
  - an unparseable date still fails safely because temporal placement is unknown;
  - measured baseline/candidate dates exactly equal V1.1 common intervals.

- [ ] **Step 5: Implement selection orchestration**

```python
aligned = _align_evaluation_history(
    spy_bars,
    bil_bars,
    evaluation_start=DEVELOPMENT_START,
    evaluation_end=SELECTION_END,
)
measured_dates = tuple(interval.signal_date for interval in aligned.intervals)
v1_signals = _build_v1_signals(
    aligned.spy_history,
    final_signal_date=measured_dates[-1],
    engine=engine,
)
```

Build baseline caps and every candidate state path from the same V1 signal stream. Candidate state processing includes all pre-measurement V1-eligible signals, but simulation uses only exact measured dates. Simulate baseline and candidates at 5 bps, slice Dev/Val/Combined from continuous paths, calculate diagnostics on identical boundaries, qualify all 12, then freeze at most one winner. If none qualify, return `NO_QUALIFIED_CANDIDATE` and `winner=None`.

- [ ] **Step 6: Verify GREEN plus V1.1 regression suite**.

- [ ] **Step 7: Commit** `feat: add fixed stabilization candidate selection`.

---

### Task 7: Locked 2021+ Evaluation

**Files:** same module/test.

**Produces:** `LockedEvaluationResult`, public `evaluate_locked_regime_stabilization(spy_bars, bil_bars, *, frozen_candidate, engine=None, initial_capital=100_000.0)`.

- [ ] **Step 1: Write failing locked tests**:
  - signature contains exactly one `frozen_candidate`, no grid or ranking parameters;
  - a candidate outside `FIXED_STABILIZATION_CANDIDATES` is rejected;
  - CAGR improvement `0.0024` fails, `0.0025` passes that gate;
  - denominator-zero turnover/whipsaw yields `NOT_EVALUABLE` and final `NO_V1_2_PROMOTION`;
  - pre-2021 V1 signals reconstruct overlay/counters, while returned portfolio points all begin on or after `2021-01-01`.

- [ ] **Step 2: Verify RED**.

- [ ] **Step 3: Implement locked orchestration**

```python
if frozen_candidate not in FIXED_STABILIZATION_CANDIDATES:
    raise ValueError("locked evaluation requires a frozen fixed-grid candidate")
aligned = _align_evaluation_history(
    spy_bars,
    bil_bars,
    evaluation_start=LOCKED_START,
    evaluation_end=None,
)
```

Run state-machine warm-up across all eligible pre-2021 signals from `aligned.spy_history`, extract only locked measured dates for simulation, and start both locked baseline and candidate virtual capital from the supplied `initial_capital`, paying V1.1 opening exposure cost from zero. Do not carry pre-2021 portfolio value into locked returns.

Apply every locked promotion gate. Any `FAIL` or `NOT_EVALUABLE` produces `NO_V1_2_PROMOTION`; only all-pass produces `PROMOTE_V1_2_RESEARCH`.

- [ ] **Step 4: Verify GREEN**.

- [ ] **Step 5: Commit** `feat: add locked stabilization evaluation`.

---

### Task 8: Post-selection Diagnostics, Public Exports, Source Safety

**Files:**
- Modify `src/private_quant/backtest/regime_stabilization.py`
- Modify `src/private_quant/backtest/__init__.py`
- Modify `tests/test_regime_stabilization.py`

**Produces:** public `build_stabilization_post_selection_diagnostics(spy_bars, bil_bars, *, frozen_candidate, engine=None, initial_capital=100_000.0)`.

- [ ] **Step 1: Write failing tests** asserting:
  - one frozen candidate only; no grid, custom costs, or custom windows;
  - cost scenarios exactly `{0.0,2.0,5.0,10.0}`;
  - fixed windows exactly GFC `2007-10-01..2009-06-30`, calendar 2020, calendar 2022, `2023-01-01..2025-12-31`;
  - function returns descriptive metrics/diagnostics only and never candidate ranking.

- [ ] **Step 2: Add AST source-safety tests** for `regime_stabilization.py`:

```python
for forbidden in (
    "streamlit",
    "dotenv",
    "ibapi",
    "private_quant.broker",
    "private_quant.app.paper_trading",
):
    self.assertFalse(any(name == forbidden or name.startswith(forbidden + ".") for name in imports))
self.assertNotIn("qqq_bars", source)
self.assertNotIn("RegimeConfidence", source)
self.assertNotIn("placeOrder", source)
self.assertNotIn("build_market_data_provider", source)
self.assertNotIn(".env", source)
```

- [ ] **Step 3: Verify RED**.

- [ ] **Step 4: Implement fixed post-selection diagnostics** by reusing one frozen state path and V1.1 accounting for 0/2/5/10 bps, full-period metrics, four fixed windows, exposure distribution, turnover/cost, whipsaw, re-entry lag, and recovery duration. No result is allowed to change the frozen candidate.

- [ ] **Step 5: Export only public contracts/results and these functions from `backtest/__init__.py`**:

```python
select_regime_stabilization_candidate
evaluate_locked_regime_stabilization
build_stabilization_post_selection_diagnostics
```

Do not export state-machine, gate, or ranking helpers.

- [ ] **Step 6: Verify GREEN plus V1.1 regression tests**.

- [ ] **Step 7: Commit** `feat: expose stabilization research protocol`.

---

### Task 9: Docs, Full Verification, and Manual Stage 1 Gate

**Files:**
- Modify `docs/MARKET_REGIME_V1.md`
- Modify `docs/ROADMAP.md`
- Modify `tests/test_regime_stabilization.py`

- [ ] **Step 1: Add failing documentation tests** requiring the docs to contain `Market Regime Stabilization & Re-entry V1.2`, `NO_QUALIFIED_CANDIDATE`, `2021-01-01`, and a statement that freshness must be rechecked; forbid claims `V1.2 winner:` and `PROMOTE_V1_2_RESEARCH confirmed` before manual runs.

- [ ] **Step 2: Update docs** with frozen V1 boundary, 12-candidate grid, fixed periods, 5 bps BIL baseline, gates/tie rules, non-pristine locked-period wording, valid failure outcomes, two separate manual authorization stages, and no execution path. In `ROADMAP.md`, deterministic implementation/test items can be checked after verification; Manual Stage 1 and Stage 2 remain unchecked.

- [ ] **Step 3: Run focused V1.2 suite**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_regime_stabilization.py" -v
```

Record exact count.

- [ ] **Step 4: Run full repository verification**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pip check
git diff --check
git status --short --branch
```

Expected: all tests pass, full count exceeds 269, compileall PASS, pip check clean, diff check PASS, working tree clean after final commit.

- [ ] **Step 5: Verify frozen and execution-path diffs are empty**

```powershell
git diff main...HEAD -- src/private_quant/risk/market_regime.py
git diff main...HEAD -- src/private_quant/broker
git diff main...HEAD -- src/private_quant/app/paper_trading.py
git diff main...HEAD -- .env .env.example
git diff --name-only main...HEAD
```

The first four outputs must be empty. The changed-file list is limited to V1.2 module/test/exports/docs/spec/plan files; no config or Streamlit application files.

- [ ] **Step 6: Commit docs**

```powershell
git add docs/MARKET_REGIME_V1.md docs/ROADMAP.md tests/test_regime_stabilization.py
git commit -m "docs: document regime stabilization v1.2 research"
```

If checkbox status needs a narrow post-verification update, make one additional docs-only commit.

- [ ] **Step 7: STOP before `.env` or Tiingo** and return actual values for branch, HEAD, changed files, focused/full test counts, compileall, pip check, diff check, clean tree, empty frozen/execution diffs, and secret/data-artifact review, ending with:

```text
I am waiting for authorization to run Manual Tiingo Stage 1 candidate selection through 2020-12-31 only.
```

Do not read `.env`, call Tiingo, connect to TWS/IBKR, or touch orders before that authorization.

---

## Manual Stage 1 Protocol — Separate Authorization Required

1. Use the existing configuration loader; never print `.env` or credentials.
2. Fetch SPY/BIL only as needed for warm-up and evaluation through `2020-12-31`; do not fetch 2021+ for selection.
3. Do not request QQQ for V1.2.
4. Run `select_regime_stabilization_candidate` only.
5. Report sanitized coverage, baseline Dev/Val/Combined metrics, all 12 candidates, all gates, and exact winner or `NO_QUALIFIED_CANDIDATE`.
6. Do not change grid, rules, dates, thresholds, gates, or tie logic after results.
7. If no candidate qualifies, stop and do not open locked data.
8. If a candidate wins, stop for review and explicit freeze/Stage 2 authorization.
9. No raw provider payloads, downloaded price history, API keys, config objects, headers, TWS/IBKR, or orders.

## Manual Stage 2 Protocol — Second Separate Authorization Required

1. Use exactly the reviewed Stage 1 frozen candidate.
2. Fetch/read SPY/BIL through latest complete common interval.
3. Run `evaluate_locked_regime_stabilization` and report all locked gates plus final `PROMOTE_V1_2_RESEARCH` or `NO_V1_2_PROMOTION`.
4. Only after the candidate remains frozen, run fixed 0/2/5/10 bps and fixed-window diagnostics.
5. Do not retune or replace the candidate after locked results.
6. No TWS/IBKR or orders.
