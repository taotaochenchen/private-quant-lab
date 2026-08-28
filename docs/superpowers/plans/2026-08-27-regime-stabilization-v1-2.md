# Market Regime Stabilization & Re-entry V1.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, provider-independent Market Regime V1.2 research overlay that preserves immediate de-risking, tests a fixed 12-candidate confirmed re-entry grid through 2020, freezes at most one winner, and evaluates that exact winner on a structurally separate 2021+ locked period.

**Architecture:** Add a new `regime_stabilization.py` research module downstream of the unchanged `MarketRegimeEngine`. Reuse the validated V1.1 SPY/BIL alignment, portfolio simulation, and metric conventions without changing their behavior; V1.2 owns only the stateful exposure-transition schedule, diagnostics, candidate-selection protocol, and locked-promotion protocol. Selection and locked evaluation are separate public entry points so 2021+ results cannot participate in winner selection.

**Tech Stack:** Python 3.11+, standard-library `dataclasses`, `enum`, `math`, `statistics`, existing `PriceBar`, `MarketRegimeEngine`, V1.1 evaluation helpers, and `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-27-regime-stabilization-v1-2-design.md`

## Global Constraints

- Do not change Market Regime V1 trend, momentum, drawdown, volatility components, weights, or `45 / 15 / -20` thresholds.
- Do not change `BULL / CAUTIOUS_BULL / RISK_OFF / BEAR` definitions or the `100% / 70% / 30% / 0%` V1 maximum-long-exposure mapping.
- Do not use QQQ confidence to control V1.2 exposure; the stabilization module has no QQQ input or dependency.
- Allowed overlay exposures are exactly `0.0, 0.3, 0.7, 1.0`, and overlay exposure must never exceed the current V1 cap.
- Downgrades are immediate; upgrades are at most one exposure level per signal session.
- Fixed candidates are exactly `margin in (0, 5, 10)` crossed with `confirmation_sessions in (1, 2, 3, 5)`; no caller-supplied candidate grid.
- Candidate selection uses Development `2007-10-01..2014-12-31`, Validation `2015-01-01..2020-12-31`, and combined `2007-10-01..2020-12-31` only.
- Locked evaluation begins `2021-01-01` and cannot select, mutate, or replace the frozen winner.
- Primary comparison is unchanged Regime V1 + BIL residual-cash proxy at `5 bps`.
- Selection gates: Development and Validation max drawdown no worse than `-20%`; combined CAGR strictly above baseline; each split CAGR no more than `0.50 percentage point` below baseline; combined annualized turnover at least `15%` lower; combined whipsaw-pair count at least `20%` lower.
- Winner tie band is `0.05 percentage point` CAGR, then lower whipsaw count, better max drawdown, smaller confirmation length, smaller margin.
- Locked promotion gates: max drawdown no worse than `-20%`; CAGR at least `0.25 percentage point` above baseline; turnover at least `15%` lower; whipsaw-pair count at least `20%` lower.
- V1.1 signal-date-to-next-session timing, opening-cost convention, BIL cash proxy, and metric formulas remain unchanged.
- Automated tests must not read `.env`, call Tiingo, import provider builders, connect to TWS/IBKR, or touch order code.
- Do not add Streamlit UI in V1.2.
- Manual Tiingo validation is two-stage and requires explicit authorization before each stage. Implementation must stop before Stage 1 authorization.

---

## File Structure

- Create `src/private_quant/backtest/regime_stabilization.py` — all V1.2 immutable contracts, fixed protocol constants, state machine, diagnostics, candidate selection, and locked evaluation.
- Create `tests/test_regime_stabilization.py` — deterministic V1.2 state-machine, isolation, gate, ranking, diagnostics, and source-safety tests.
- Modify `src/private_quant/backtest/__init__.py` — export only the intended public V1.2 contracts and orchestration functions.
- Modify `docs/MARKET_REGIME_V1.md` — document V1.2 as a research study with no winner claimed before manual Stage 1.
- Modify `docs/ROADMAP.md` — add V1.2 deterministic implementation and two-stage validation checklist without claiming empirical promotion.
- Do not modify `src/private_quant/risk/market_regime.py`, broker/IBKR/order/paper-trading/configuration/Streamlit code, `.env`, or `.env.example`.

---

### Task 1: Lock V1.2 Contracts and Fixed Research Protocol

**Files:**
- Create: `src/private_quant/backtest/regime_stabilization.py`
- Create: `tests/test_regime_stabilization.py`

**Interfaces:**
- Consumes: `MarketRegime`, `PerformanceMetrics`, `EvaluationPoint` from existing code.
- Produces:
  - `StabilizationCandidate(margin: int, confirmation_sessions: int)`
  - `BoundaryConfirmationState(to_30: int, to_70: int, to_100: int)`
  - `StabilizationTransition`
  - `StabilizationSignalPoint`
  - `ResearchPeriod`
  - `GateStatus`, `GateResult`
  - `SelectionStatus`, `PromotionStatus`
  - `FIXED_STABILIZATION_CANDIDATES`
  - fixed date and threshold constants used by later tasks.

- [ ] **Step 1: Write failing contract tests**

Add `tests/test_regime_stabilization.py` with fixed-grid and immutability assertions:

```python
from dataclasses import FrozenInstanceError
from datetime import date
import unittest

from private_quant.backtest.regime_stabilization import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    FIXED_STABILIZATION_CANDIDATES,
    LOCKED_START,
    SELECTION_END,
    StabilizationCandidate,
)


class StabilizationContractTests(unittest.TestCase):
    def test_fixed_candidate_grid_is_exact_and_ordered(self) -> None:
        self.assertEqual(
            FIXED_STABILIZATION_CANDIDATES,
            tuple(
                StabilizationCandidate(margin, confirmation)
                for margin in (0, 5, 10)
                for confirmation in (1, 2, 3, 5)
            ),
        )
        self.assertEqual(len(FIXED_STABILIZATION_CANDIDATES), 12)

    def test_candidate_is_immutable_and_rejects_out_of_protocol_values(self) -> None:
        candidate = StabilizationCandidate(5, 3)
        with self.assertRaises(FrozenInstanceError):
            candidate.margin = 10
        for args in ((-1, 3), (6, 3), (5, 4), (5, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                StabilizationCandidate(*args)

    def test_fixed_period_boundaries_are_not_parameters(self) -> None:
        self.assertEqual(DEVELOPMENT_START, date(2007, 10, 1))
        self.assertEqual(DEVELOPMENT_END, date(2014, 12, 31))
        self.assertEqual(SELECTION_END, date(2020, 12, 31))
        self.assertEqual(LOCKED_START, date(2021, 1, 1))
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_regime_stabilization.py" -v
```

Expected: import failure because `regime_stabilization.py` does not exist.

- [ ] **Step 3: Implement immutable contracts and constants**

Create `src/private_quant/backtest/regime_stabilization.py` with this public foundation:

```python
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum
from statistics import fmean, median

from private_quant.backtest.regime_evaluation import EvaluationPoint, PerformanceMetrics
from private_quant.risk import MarketRegime, MarketRegimeEngine

ALLOWED_EXPOSURES = (0.0, 0.3, 0.7, 1.0)
MARGINS = (0, 5, 10)
CONFIRMATION_SESSIONS = (1, 2, 3, 5)
DEVELOPMENT_START = date(2007, 10, 1)
DEVELOPMENT_END = date(2014, 12, 31)
VALIDATION_START = date(2015, 1, 1)
SELECTION_END = date(2020, 12, 31)
LOCKED_START = date(2021, 1, 1)
PRIMARY_COST_BPS = 5.0
RISK_FLOOR = -0.20
SPLIT_CAGR_ALLOWANCE = 0.005
WINNER_CAGR_TIE_BAND = 0.0005
LOCKED_CAGR_IMPROVEMENT = 0.0025
TURNOVER_REDUCTION = 0.15
WHIPSAW_REDUCTION = 0.20


@dataclass(frozen=True, slots=True)
class StabilizationCandidate:
    margin: int
    confirmation_sessions: int

    def __post_init__(self) -> None:
        if self.margin not in MARGINS or self.confirmation_sessions not in CONFIRMATION_SESSIONS:
            raise ValueError("candidate is outside the fixed V1.2 grid")


FIXED_STABILIZATION_CANDIDATES = tuple(
    StabilizationCandidate(margin, confirmation)
    for margin in MARGINS
    for confirmation in CONFIRMATION_SESSIONS
)


@dataclass(frozen=True, slots=True)
class BoundaryConfirmationState:
    to_30: int = 0
    to_70: int = 0
    to_100: int = 0


class StabilizationTransition(str, Enum):
    HOLD = "hold"
    DE_RISK = "de_risk"
    REENTER_30 = "reenter_30"
    REENTER_70 = "reenter_70"
    REENTER_100 = "reenter_100"


@dataclass(frozen=True, slots=True)
class StabilizationSignalPoint:
    signal_date: date
    v1_score: int
    v1_regime: MarketRegime
    v1_cap: float
    prior_overlay_exposure: float
    overlay_exposure: float
    confirmations: BoundaryConfirmationState
    transition: StabilizationTransition


class ResearchPeriod(str, Enum):
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    COMBINED = "combined"
    LOCKED = "locked"


class GateStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_EVALUABLE = "not_evaluable"


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    status: GateStatus
    actual: float | int | None
    required: float | int | str


class SelectionStatus(str, Enum):
    WINNER_FROZEN = "winner_frozen"
    NO_QUALIFIED_CANDIDATE = "no_qualified_candidate"


class PromotionStatus(str, Enum):
    PROMOTE_V1_2_RESEARCH = "promote_v1_2_research"
    NO_V1_2_PROMOTION = "no_v1_2_promotion"
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same unittest discovery command. Expected: Task 1 tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/private_quant/backtest/regime_stabilization.py tests/test_regime_stabilization.py
git commit -m "feat: add regime stabilization v1.2 contracts"
```

---

### Task 2: Implement the Deterministic Fast-De-risk / Confirmed-Re-entry State Machine

**Files:**
- Modify: `src/private_quant/backtest/regime_stabilization.py`
- Modify: `tests/test_regime_stabilization.py`

**Interfaces:**
- Consumes: `StabilizationCandidate`, `BoundaryConfirmationState`, unchanged V1 daily `score`, `regime`, and `maximum_long_exposure`.
- Produces:
  - `_update_confirmations(score: int, candidate: StabilizationCandidate, prior: BoundaryConfirmationState) -> BoundaryConfirmationState`
  - `_next_overlay_exposure(...) -> tuple[float, StabilizationTransition]`
  - `_run_stabilization_state_machine(v1_points, candidate) -> tuple[StabilizationSignalPoint, ...]`.

- [ ] **Step 1: Add failing state-machine tests**

Add tests covering the exact update order and invariants:

```python
class StabilizationStateMachineTests(unittest.TestCase):
    def test_immediate_multi_level_derisk_and_no_same_session_reupgrade(self) -> None:
        points = run_fake_v1_sequence(
            caps=(1.0, 1.0, 0.0),
            scores=(60, 60, 60),
            candidate=StabilizationCandidate(0, 1),
        )
        self.assertEqual(tuple(p.overlay_exposure for p in points), (1.0, 1.0, 0.0))
        self.assertIs(points[-1].transition, StabilizationTransition.DE_RISK)

    def test_reentry_is_at_most_one_level_per_signal_session(self) -> None:
        points = run_fake_v1_sequence(
            caps=(0.0, 1.0, 1.0, 1.0),
            scores=(-30, 60, 60, 60),
            candidate=StabilizationCandidate(0, 1),
        )
        self.assertEqual(tuple(p.overlay_exposure for p in points), (0.0, 0.3, 0.7, 1.0))

    def test_confirmation_uses_inclusive_margin_and_resets_on_failure(self) -> None:
        candidate = StabilizationCandidate(5, 2)
        scores = (-15, -16, -15, -15)
        states = accumulate_confirmations(scores, candidate)
        self.assertEqual(tuple(s.to_30 for s in states), (1, 0, 1, 2))

    def test_parallel_high_boundary_counters_accumulate_while_exposure_is_lower(self) -> None:
        points = run_fake_v1_sequence(
            caps=(0.0, 1.0, 1.0, 1.0, 1.0),
            scores=(-30, 60, 60, 60, 60),
            candidate=StabilizationCandidate(0, 3),
        )
        self.assertEqual(points[3].confirmations.to_100, 3)
        self.assertEqual(tuple(p.overlay_exposure for p in points[-3:]), (0.3, 0.7, 1.0))

    def test_overlay_never_exceeds_v1_cap(self) -> None:
        points = run_fake_v1_sequence(
            caps=(0.7, 0.7, 0.3, 0.7),
            scores=(60, 60, 60, 60),
            candidate=StabilizationCandidate(0, 1),
        )
        self.assertTrue(all(p.overlay_exposure <= p.v1_cap for p in points))
```

Implement local test helpers with a small frozen fake V1 input contract rather than mocking `MarketRegimeEngine` in these pure state tests.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_regime_stabilization.py" -v
```

Expected: missing state-machine helpers.

- [ ] **Step 3: Implement counter and transition logic exactly**

Add a private `_V1Signal` dataclass and these implementations:

```python
@dataclass(frozen=True, slots=True)
class _V1Signal:
    signal_date: date
    score: int
    regime: MarketRegime
    cap: float


def _updated_counter(score: int, threshold: int, margin: int, prior: int, required: int) -> int:
    if score >= threshold + margin:
        return min(required, prior + 1)
    return 0


def _update_confirmations(
    score: int,
    candidate: StabilizationCandidate,
    prior: BoundaryConfirmationState,
) -> BoundaryConfirmationState:
    required = candidate.confirmation_sessions
    return BoundaryConfirmationState(
        to_30=_updated_counter(score, -20, candidate.margin, prior.to_30, required),
        to_70=_updated_counter(score, 15, candidate.margin, prior.to_70, required),
        to_100=_updated_counter(score, 45, candidate.margin, prior.to_100, required),
    )


def _next_overlay_exposure(
    prior_exposure: float,
    v1_cap: float,
    confirmations: BoundaryConfirmationState,
    candidate: StabilizationCandidate,
) -> tuple[float, StabilizationTransition]:
    if prior_exposure not in ALLOWED_EXPOSURES or v1_cap not in ALLOWED_EXPOSURES:
        raise ValueError("stabilization exposure is invalid")
    if v1_cap < prior_exposure:
        return v1_cap, StabilizationTransition.DE_RISK

    required = candidate.confirmation_sessions
    if prior_exposure == 0.0 and v1_cap >= 0.3 and confirmations.to_30 >= required:
        return 0.3, StabilizationTransition.REENTER_30
    if prior_exposure == 0.3 and v1_cap >= 0.7 and confirmations.to_70 >= required:
        return 0.7, StabilizationTransition.REENTER_70
    if prior_exposure == 0.7 and v1_cap >= 1.0 and confirmations.to_100 >= required:
        return 1.0, StabilizationTransition.REENTER_100
    return prior_exposure, StabilizationTransition.HOLD


def _run_stabilization_state_machine(
    v1_signals: Sequence[_V1Signal],
    candidate: StabilizationCandidate,
) -> tuple[StabilizationSignalPoint, ...]:
    prior_exposure = 0.0
    confirmations = BoundaryConfirmationState()
    output: list[StabilizationSignalPoint] = []
    for signal in v1_signals:
        confirmations = _update_confirmations(signal.score, candidate, confirmations)
        overlay, transition = _next_overlay_exposure(
            prior_exposure, signal.cap, confirmations, candidate
        )
        if overlay > signal.cap or overlay not in ALLOWED_EXPOSURES:
            raise ValueError("stabilization exposure exceeds V1 cap")
        output.append(
            StabilizationSignalPoint(
                signal_date=signal.signal_date,
                v1_score=signal.score,
                v1_regime=signal.regime,
                v1_cap=signal.cap,
                prior_overlay_exposure=prior_exposure,
                overlay_exposure=overlay,
                confirmations=confirmations,
                transition=transition,
            )
        )
        prior_exposure = overlay
    return tuple(output)
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the focused suite. Expected: all Task 1-2 tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/private_quant/backtest/regime_stabilization.py tests/test_regime_stabilization.py
git commit -m "feat: add regime stabilization state machine"
```

---

### Task 3: Build Point-in-Time V1 Signal Streams and Warm-up State Without QQQ

**Files:**
- Modify: `src/private_quant/backtest/regime_stabilization.py`
- Modify: `tests/test_regime_stabilization.py`

**Interfaces:**
- Consumes: existing V1.1 `_align_evaluation_history`, `_canonical_trading_date`, and unchanged `MarketRegimeEngine`.
- Produces:
  - `_build_v1_signals(spy_history, *, final_signal_date, engine=None) -> tuple[_V1Signal, ...]`
  - `_measured_state_points(all_state_points, measured_signal_dates) -> tuple[StabilizationSignalPoint, ...]`.

- [ ] **Step 1: Write failing point-in-time and warm-up tests**

Use real `PriceBar` fixtures and a recording engine. Required assertions:

```python
class StabilizationSignalStreamTests(unittest.TestCase):
    def test_v1_signal_stream_starts_at_252nd_observation_and_has_no_qqq_argument(self) -> None:
        spy = make_spy_bars(260)
        signals = _build_v1_signals(
            tuple(spy),
            final_signal_date=spy[258].trading_date,
            engine=RecordingRegimeEngine(),
        )
        self.assertEqual(signals[0].signal_date, spy[251].trading_date)
        self.assertEqual(signals[-1].signal_date, spy[258].trading_date)

    def test_state_warmup_changes_first_measured_overlay_but_not_opening_portfolio_cost(self) -> None:
        # The pre-period signals qualify counters before the first measured signal.
        # Assert the first measured overlay reflects warm-up state; portfolio opening cost is tested in Task 4.
        ...

    def test_future_valid_dated_malformed_price_cannot_change_selection_signal_stream(self) -> None:
        baseline = build_selection_signals(valid_spy)
        changed = build_selection_signals(spy_with_nan_on_2021_01_04)
        self.assertEqual(changed, baseline)

    def test_unparseable_future_date_fails_safely(self) -> None:
        with self.assertRaises(InvalidEvaluationDataError):
            build_selection_history(spy_with_unparseable_date)
```

Replace the ellipsis in the actual test with explicit fixture values: use three warm-up scores at or above all boundaries with `confirmation_sessions=3`, then assert the first measured target is `0.3` rather than `0.0` while the pre-measurement points are absent from the measured schedule.

- [ ] **Step 2: Run focused tests and verify RED**

Run the focused unittest suite. Expected: missing signal-stream helpers.

- [ ] **Step 3: Implement signal stream with explicit cutoff**

Import existing helpers:

```python
from private_quant.backtest.regime_evaluation import (
    EvaluationStrategy,
    InvalidEvaluationDataError,
    _AlignedEvaluationHistory,
    _align_evaluation_history,
    _canonical_trading_date,
)
```

Implement:

```python
def _build_v1_signals(
    spy_history: Sequence[PriceBar],
    *,
    final_signal_date: date,
    engine: MarketRegimeEngine | None = None,
) -> tuple[_V1Signal, ...]:
    classifier = engine or MarketRegimeEngine()
    ordered = tuple(
        bar for bar in spy_history if _canonical_trading_date(bar) <= final_signal_date
    )
    if len(ordered) < 252:
        raise InvalidEvaluationDataError("SPY history has insufficient V1 warm-up")
    output: list[_V1Signal] = []
    for index in range(251, len(ordered)):
        as_of = _canonical_trading_date(ordered[index])
        result = classifier.evaluate(ordered[: index + 1], as_of=as_of, qqq_bars=None)
        if result.maximum_long_exposure not in ALLOWED_EXPOSURES:
            raise InvalidEvaluationDataError("V1 exposure mapping is invalid")
        output.append(_V1Signal(as_of, result.score, result.regime, result.maximum_long_exposure))
    return tuple(output)
```

Selection orchestration added in later tasks must first call `_align_evaluation_history(... evaluation_start=DEVELOPMENT_START, evaluation_end=SELECTION_END)`, so valid-dated 2021+ price content is outside the active boundary before `_build_v1_signals` receives `aligned.spy_history`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the focused suite and confirm the recording engine never receives QQQ.

- [ ] **Step 5: Commit**

```powershell
git add src/private_quant/backtest/regime_stabilization.py tests/test_regime_stabilization.py
git commit -m "feat: add point in time stabilization signal stream"
```

---

### Task 4: Reuse V1.1 Portfolio Accounting and Add Continuous Period Slices

**Files:**
- Modify: `src/private_quant/backtest/regime_stabilization.py`
- Modify: `tests/test_regime_stabilization.py`

**Interfaces:**
- Consumes: V1.1 `_simulate_intervals`, `_performance_metrics`, `_PriceInterval`, `EvaluationStrategy.REGIME_BIL_CASH_PROXY`.
- Produces:
  - `_simulate_bil_cash_schedule(aligned, exposures, cost_bps) -> tuple[EvaluationPoint, ...]`
  - `_slice_period_points(points, start, end) -> tuple[EvaluationPoint, ...]`
  - `_rebased_period_metrics(points) -> PerformanceMetrics`.

- [ ] **Step 1: Write failing accounting tests**

Add deterministic fixtures proving opening cost and boundary continuity:

```python
class StabilizationPortfolioTests(unittest.TestCase):
    def test_first_measured_target_still_pays_opening_cost_from_zero(self) -> None:
        points = simulate_fixture(exposures=(0.7, 0.7), cost_bps=5.0)
        self.assertAlmostEqual(points[0].exposure_change, 0.7)
        self.assertAlmostEqual(points[0].transaction_cost, 100.0 * 0.7 * 5.0 / 10_000.0)
        self.assertEqual(points[1].exposure_change, 0.0)

    def test_period_slice_preserves_real_boundary_exposure_change(self) -> None:
        full = simulate_three_interval_fixture(exposures=(0.3, 0.7, 0.7))
        validation = _slice_period_points(full, date(2020, 1, 3), date(2020, 12, 31))
        self.assertEqual(validation[0].exposure_change, 0.4)

    def test_rebased_period_metrics_do_not_restart_strategy(self) -> None:
        metrics = _rebased_period_metrics(period_fixture_points())
        self.assertEqual(metrics.initial_capital, 100.0)
        self.assertAlmostEqual(metrics.final_value, expected_rebased_final)
```

Use explicit numeric values in the final tests; do not compute expected values by calling the implementation under test.

- [ ] **Step 2: Run focused tests and verify RED**

Run the focused suite. Expected: missing portfolio bridge helpers.

- [ ] **Step 3: Implement thin V1.1 bridge and rebasing**

Import:

```python
from private_quant.backtest.regime_evaluation import (
    EvaluationPoint,
    EvaluationStrategy,
    PerformanceMetrics,
    _performance_metrics,
    _simulate_intervals,
)
```

Implement the bridge:

```python
def _simulate_bil_cash_schedule(
    aligned: _AlignedEvaluationHistory,
    exposures: Sequence[float],
    *,
    cost_bps: float = PRIMARY_COST_BPS,
    initial_capital: float = 100_000.0,
) -> tuple[EvaluationPoint, ...]:
    return _simulate_intervals(
        aligned.intervals,
        exposures,
        strategy=EvaluationStrategy.REGIME_BIL_CASH_PROXY,
        initial_capital=initial_capital,
        transaction_cost_bps=cost_bps,
    )


def _slice_period_points(
    points: Sequence[EvaluationPoint], start: date, end: date
) -> tuple[EvaluationPoint, ...]:
    return tuple(
        point for point in points
        if start <= point.signal_date and point.return_end_date <= end
    )


def _rebased_period_metrics(points: Sequence[EvaluationPoint]) -> PerformanceMetrics:
    if not points:
        raise ValueError("research period has no complete intervals")
    scale = 100.0 / points[0].starting_value
    rebased = tuple(
        EvaluationPoint(
            signal_date=p.signal_date,
            return_end_date=p.return_end_date,
            starting_value=p.starting_value * scale,
            ending_value=p.ending_value * scale,
            target_spy_exposure=p.target_spy_exposure,
            spy_return=p.spy_return,
            residual_cash_return=p.residual_cash_return,
            net_return=p.net_return,
            exposure_change=p.exposure_change,
            transaction_cost=p.transaction_cost * scale,
        )
        for p in points
    )
    return _performance_metrics(
        100.0,
        rebased,
        applicable_exposures=ALLOWED_EXPOSURES,
    )
```

- [ ] **Step 4: Run focused tests and V1.1 regression suite**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_regime_stabilization.py" -v
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation -v
```

Expected: both pass; no V1.1 behavior changed.

- [ ] **Step 5: Commit**

```powershell
git add src/private_quant/backtest/regime_stabilization.py tests/test_regime_stabilization.py
git commit -m "feat: reuse v1.1 accounting for stabilization study"
```

---

### Task 5: Implement Schedule Diagnostics, Whipsaw, Re-entry Lag, and Recovery Episodes

**Files:**
- Modify: `src/private_quant/backtest/regime_stabilization.py`
- Modify: `tests/test_regime_stabilization.py`

**Interfaces:**
- Produces:
  - `StabilizationDiagnostics`
  - `_schedule_change_count(points, *, start=None, end=None)`
  - `_whipsaw_pairs(points, *, start=None, end=None, horizon=5)`
  - `_stabilization_diagnostics(state_points, *, start, end, include_reentry_detail)`.

- [ ] **Step 1: Write failing diagnostic tests with literal schedules**

```python
class StabilizationDiagnosticTests(unittest.TestCase):
    def test_whipsaw_examples_and_non_examples(self) -> None:
        self.assertEqual(whipsaws_for((0.7, 0.3, 0.7)), 1)
        self.assertEqual(whipsaws_for((0.3, 0.7, 0.3)), 1)
        self.assertEqual(whipsaws_for((0.0, 0.3, 0.7, 1.0)), 0)
        self.assertEqual(whipsaws_for((1.0, 0.7, 0.7, 0.7, 0.7, 0.7, 1.0)), 0)

    def test_whipsaw_pairs_are_non_overlapping(self) -> None:
        self.assertEqual(whipsaws_for((0.7, 0.3, 0.7, 0.3, 0.7)), 2)

    def test_first_measured_target_is_not_an_artificial_schedule_change(self) -> None:
        diagnostics = diagnostics_for((0.7, 0.7, 0.3))
        self.assertEqual(diagnostics.schedule_exposure_changes, 1)

    def test_zero_changes_has_none_whipsaw_rate(self) -> None:
        diagnostics = diagnostics_for((0.7, 0.7, 0.7))
        self.assertIsNone(diagnostics.whipsaw_rate)

    def test_reentry_lag_and_incomplete_recovery_are_counted(self) -> None:
        # Use explicit signal points where 30% boundary qualifies at session 2,
        # overlay crosses at session 4, one recovery reaches 100%, and one remains open.
        diagnostics = _stabilization_diagnostics(fixture_points, start=..., end=..., include_reentry_detail=True)
        self.assertEqual(diagnostics.reentry_lags, (3,))
        self.assertEqual(diagnostics.recovery_durations, (4,))
        self.assertEqual(diagnostics.incomplete_recoveries, 1)
```

Fill the final fixture with literal dates and explicit `StabilizationSignalPoint` values; do not leave ellipses in committed tests.

- [ ] **Step 2: Run focused tests and verify RED**

Run focused suite; expected missing diagnostics.

- [ ] **Step 3: Implement diagnostics**

Add:

```python
@dataclass(frozen=True, slots=True)
class StabilizationDiagnostics:
    schedule_exposure_changes: int
    whipsaw_pairs: int
    whipsaw_rate: float | None
    delayed_below_cap_sessions: int
    reentry_lags: tuple[int, ...]
    mean_reentry_lag: float | None
    median_reentry_lag: float | None
    recovery_durations: tuple[int, ...]
    incomplete_recoveries: int
```

Whipsaw implementation must scan actual schedule changes, compare each opener to the exposure immediately before that change, search at most the next five **signal sessions** for the first opposite-direction change returning to or beyond the pre-change exposure, then resume after the paired closer. Do not use portfolio opening exposure from zero as an opener.

For period diagnostics, retain the immediately preceding signal point outside the requested start only as context for deciding whether the first in-period target is a real schedule change; count only opening changes whose current signal date is in the requested period.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run focused suite. Expected: all diagnostic tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/private_quant/backtest/regime_stabilization.py tests/test_regime_stabilization.py
git commit -m "feat: add stabilization diagnostics"
```

---

### Task 6: Implement Fixed Candidate Selection Through 2020

**Files:**
- Modify: `src/private_quant/backtest/regime_stabilization.py`
- Modify: `tests/test_regime_stabilization.py`

**Interfaces:**
- Produces:
  - `CandidatePeriodResult`
  - `CandidateQualification`
  - `CandidateSelectionResult`
  - `select_regime_stabilization_candidate(spy_bars, bil_bars, *, engine=None, initial_capital=100_000.0) -> CandidateSelectionResult`.
- Public function accepts no custom candidate grid, split dates, margins, confirmation arrays, or transaction-cost values.

- [ ] **Step 1: Write failing selection protocol tests**

Add tests for exact grid, isolation, gates, and ranking:

```python
class StabilizationSelectionTests(unittest.TestCase):
    def test_public_selection_signature_has_no_optimization_inputs(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(select_regime_stabilization_candidate).parameters),
            ("spy_bars", "bil_bars", "engine", "initial_capital"),
        )

    def test_selection_returns_exactly_12_candidate_records(self) -> None:
        result = select_fixture()
        self.assertEqual(tuple(r.candidate for r in result.candidates), FIXED_STABILIZATION_CANDIDATES)

    def test_valid_dated_2021_price_content_cannot_change_selection(self) -> None:
        baseline = select_regime_stabilization_candidate(spy, bil, engine=engine)
        changed = select_regime_stabilization_candidate(spy_with_2021_nan_price, bil_with_2021_nan_price, engine=engine)
        self.assertEqual(changed, baseline)

    def test_candidate_must_pass_every_gate(self) -> None:
        qualification = qualify_fixture(
            dev_dd=-0.19,
            val_dd=-0.21,
            combined_cagr=0.10,
            baseline_combined_cagr=0.09,
            turnover_reduction=0.20,
            whipsaw_reduction=0.30,
        )
        self.assertFalse(qualification.qualified)

    def test_cagr_tie_band_then_whipsaw_then_drawdown_then_confirmation_then_margin(self) -> None:
        winner = rank_literal_candidate_results(...)
        self.assertEqual(winner, StabilizationCandidate(5, 2))

    def test_no_qualified_candidate_is_explicit(self) -> None:
        result = selection_result_with_no_passers()
        self.assertIs(result.status, SelectionStatus.NO_QUALIFIED_CANDIDATE)
        self.assertIsNone(result.winner)
```

The committed ranking test must construct literal candidate ranking records for at least five candidates so every tie-break level is exercised without relying on historical price fixtures.

- [ ] **Step 2: Run focused tests and verify RED**

Run focused suite; expected missing selection contracts/orchestration.

- [ ] **Step 3: Implement selection result contracts**

Add:

```python
@dataclass(frozen=True, slots=True)
class CandidatePeriodResult:
    candidate: StabilizationCandidate | None  # None means unchanged V1 baseline
    period: ResearchPeriod
    metrics: PerformanceMetrics
    diagnostics: StabilizationDiagnostics


@dataclass(frozen=True, slots=True)
class CandidateQualification:
    candidate: StabilizationCandidate
    gates: tuple[GateResult, ...]
    qualified: bool


@dataclass(frozen=True, slots=True)
class CandidateSelectionResult:
    status: SelectionStatus
    baseline: tuple[CandidatePeriodResult, ...]
    candidates: tuple[CandidatePeriodResult, ...]
    qualifications: tuple[CandidateQualification, ...]
    winner: StabilizationCandidate | None
```

Store candidate period rows in deterministic order: candidate-grid order, then `DEVELOPMENT`, `VALIDATION`, `COMBINED`.

- [ ] **Step 4: Implement qualification and deterministic ranking**

Use decimal-return units:

```python
combined_cagr_pass = candidate_combined.cagr > baseline_combined.cagr
dev_cagr_pass = candidate_dev.cagr >= baseline_dev.cagr - SPLIT_CAGR_ALLOWANCE
val_cagr_pass = candidate_val.cagr >= baseline_val.cagr - SPLIT_CAGR_ALLOWANCE
turnover_pass = candidate_turnover <= baseline_turnover * (1.0 - TURNOVER_REDUCTION)
whipsaw_pass = candidate_whipsaws <= baseline_whipsaws * (1.0 - WHIPSAW_REDUCTION)
```

If baseline turnover is `None`, `<= 0`, or baseline whipsaw count is `0`, emit `NOT_EVALUABLE` for the relevant required-reduction gate and do not qualify the candidate.

Ranking algorithm:

```python
top_cagr = max(row.combined_cagr for row in qualified)
return_tied = [row for row in qualified if top_cagr - row.combined_cagr <= WINNER_CAGR_TIE_BAND]
winner = min(
    return_tied,
    key=lambda row: (
        row.combined_whipsaw_pairs,
        abs(row.combined_max_drawdown),
        row.candidate.confirmation_sessions,
        row.candidate.margin,
    ),
).candidate
```

- [ ] **Step 5: Implement selection orchestration with structural 2020 cutoff**

Algorithm:

```python
aligned = _align_evaluation_history(
    spy_bars,
    bil_bars,
    evaluation_start=DEVELOPMENT_START,
    evaluation_end=SELECTION_END,
)
final_signal_date = aligned.intervals[-1].signal_date
v1_signals = _build_v1_signals(aligned.spy_history, final_signal_date=final_signal_date, engine=engine)
```

Then:

1. Run the unchanged V1 baseline schedule from the V1 caps aligned to measured interval signal dates.
2. Simulate the baseline once at 5 bps.
3. Build state-machine paths for all 12 fixed candidates using the full pre-measurement warm-up signals.
4. Extract measured exposures matching `aligned.intervals` exactly and simulate each at 5 bps.
5. Slice Development, Validation, and Combined metrics from continuous paths.
6. Calculate schedule diagnostics on identical date boundaries.
7. Qualify all candidates and freeze at most one winner.

Assert measured signal dates exactly equal `tuple(interval.signal_date for interval in aligned.intervals)` for baseline and every candidate; fail rather than zip/truncate mismatched schedules.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run focused suite. Also run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation -v
```

Expected: selection tests and existing V1.1 tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src/private_quant/backtest/regime_stabilization.py tests/test_regime_stabilization.py
git commit -m "feat: add fixed regime stabilization candidate selection"
```

---

### Task 7: Implement Structurally Separate Locked Evaluation and Promotion Gates

**Files:**
- Modify: `src/private_quant/backtest/regime_stabilization.py`
- Modify: `tests/test_regime_stabilization.py`

**Interfaces:**
- Produces:
  - `LockedEvaluationResult`
  - `evaluate_locked_regime_stabilization(spy_bars, bil_bars, *, frozen_candidate, engine=None, initial_capital=100_000.0) -> LockedEvaluationResult`.
- Locked evaluator accepts one concrete fixed-grid candidate only; it has no candidate search or ranking input.

- [ ] **Step 1: Write failing locked-protocol tests**

```python
class StabilizationLockedEvaluationTests(unittest.TestCase):
    def test_locked_signature_requires_one_frozen_candidate_and_no_grid(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(evaluate_locked_regime_stabilization).parameters),
            ("spy_bars", "bil_bars", "frozen_candidate", "engine", "initial_capital"),
        )

    def test_locked_rejects_candidate_outside_fixed_grid(self) -> None:
        bad = object.__new__(StabilizationCandidate)
        object.__setattr__(bad, "margin", 7)
        object.__setattr__(bad, "confirmation_sessions", 4)
        with self.assertRaises(ValueError):
            evaluate_locked_regime_stabilization(spy, bil, frozen_candidate=bad)

    def test_locked_state_is_reconstructed_from_pre_2021_signals_without_pre_2021_performance(self) -> None:
        result = locked_fixture()
        self.assertEqual(result.baseline.period, ResearchPeriod.LOCKED)
        self.assertGreaterEqual(result.baseline.metrics.initial_capital, 100.0)
        self.assertTrue(all(p.signal_date >= LOCKED_START for p in result.candidate_points))

    def test_locked_evaluator_does_not_replace_failed_winner(self) -> None:
        result = locked_fixture_where_promotion_fails()
        self.assertEqual(result.frozen_candidate, requested_candidate)
        self.assertIs(result.status, PromotionStatus.NO_V1_2_PROMOTION)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run focused suite; expected missing locked evaluator.

- [ ] **Step 3: Implement locked result and promotion gates**

Add:

```python
@dataclass(frozen=True, slots=True)
class LockedEvaluationResult:
    frozen_candidate: StabilizationCandidate
    baseline: CandidatePeriodResult
    candidate: CandidatePeriodResult
    promotion_gates: tuple[GateResult, ...]
    status: PromotionStatus
    baseline_points: tuple[EvaluationPoint, ...]
    candidate_points: tuple[EvaluationPoint, ...]
```

Locked orchestration:

```python
aligned = _align_evaluation_history(
    spy_bars,
    bil_bars,
    evaluation_start=LOCKED_START,
    evaluation_end=None,
)
final_signal_date = aligned.intervals[-1].signal_date
v1_signals = _build_v1_signals(aligned.spy_history, final_signal_date=final_signal_date, engine=engine)
state_points = _run_stabilization_state_machine(v1_signals, frozen_candidate)
```

Use all pre-2021 V1 signals only to reconstruct state. Simulated portfolio points come only from the locked common intervals. Both baseline and candidate start locked measured capital at USD 100,000 and pay the V1.1 opening exposure-change cost from zero; pre-2021 signal warm-up does not create a portfolio.

Promotion gates:

```python
drawdown_pass = candidate.metrics.max_drawdown >= RISK_FLOOR
cagr_pass = candidate.metrics.cagr >= baseline.metrics.cagr + LOCKED_CAGR_IMPROVEMENT
turnover_pass = candidate.metrics.annualized_turnover <= baseline.metrics.annualized_turnover * 0.85
whipsaw_pass = candidate.diagnostics.whipsaw_pairs <= baseline.diagnostics.whipsaw_pairs * 0.80
```

Use `NOT_EVALUABLE` and final `NO_V1_2_PROMOTION` when a required baseline denominator is unavailable or zero.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run focused suite. Expected: locked tests pass with no candidate-search path.

- [ ] **Step 5: Commit**

```powershell
git add src/private_quant/backtest/regime_stabilization.py tests/test_regime_stabilization.py
git commit -m "feat: add locked regime stabilization evaluation"
```

---

### Task 8: Add Post-selection Diagnostics Without Reopening Winner Selection

**Files:**
- Modify: `src/private_quant/backtest/regime_stabilization.py`
- Modify: `tests/test_regime_stabilization.py`

**Interfaces:**
- Produces:
  - `StabilizationCostScenario`
  - `StabilizationHistoricalWindow`
  - `build_stabilization_post_selection_diagnostics(spy_bars, bil_bars, *, frozen_candidate, engine=None, initial_capital=100_000.0)`.
- This function accepts exactly one frozen candidate and cannot rank candidates.

- [ ] **Step 1: Write failing diagnostic-isolation tests**

Assert:

```python
class StabilizationPostSelectionTests(unittest.TestCase):
    def test_post_selection_accepts_one_candidate_and_fixed_costs_only(self) -> None:
        result = build_stabilization_post_selection_diagnostics(spy, bil, frozen_candidate=candidate)
        self.assertEqual({row.cost_bps for row in result.cost_scenarios}, {0.0, 2.0, 5.0, 10.0})

    def test_fixed_windows_are_exact(self) -> None:
        self.assertEqual(
            tuple((row.requested_start, row.requested_end) for row in result.windows[:4]),
            (
                (date(2007, 10, 1), date(2009, 6, 30)),
                (date(2020, 1, 1), date(2020, 12, 31)),
                (date(2022, 1, 1), date(2022, 12, 31)),
                (date(2023, 1, 1), date(2025, 12, 31)),
            ),
        )

    def test_post_selection_function_has_no_candidate_grid_or_ranking_output(self) -> None:
        self.assertNotIn("candidates", inspect.signature(build_stabilization_post_selection_diagnostics).parameters)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run focused suite.

- [ ] **Step 3: Implement fixed diagnostics**

Reuse the same state-machine path and V1.1 simulation with only `cost_bps in (0.0, 2.0, 5.0, 10.0)`. Produce full-period baseline-versus-winner metrics and fixed windows:

```python
POST_SELECTION_WINDOWS = (
    ("2008 financial crisis", date(2007, 10, 1), date(2009, 6, 30)),
    ("2020 COVID crash and recovery", date(2020, 1, 1), date(2020, 12, 31)),
    ("2022 bear market", date(2022, 1, 1), date(2022, 12, 31)),
    ("2023-2025 recovery and bull period", date(2023, 1, 1), date(2025, 12, 31)),
)
```

No post-selection metric feeds back into `select_regime_stabilization_candidate`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run focused suite and existing V1.1 tests.

- [ ] **Step 5: Commit**

```powershell
git add src/private_quant/backtest/regime_stabilization.py tests/test_regime_stabilization.py
git commit -m "feat: add stabilization post selection diagnostics"
```

---

### Task 9: Export Public V1.2 Research API and Enforce Source Safety

**Files:**
- Modify: `src/private_quant/backtest/__init__.py`
- Modify: `tests/test_regime_stabilization.py`

**Interfaces:**
- Public exports: fixed candidate/result enums and dataclasses plus `select_regime_stabilization_candidate`, `evaluate_locked_regime_stabilization`, and `build_stabilization_post_selection_diagnostics`.
- Private helpers remain private.

- [ ] **Step 1: Write failing export and source-safety tests**

Add AST-based checks patterned after V1.1:

```python
class StabilizationSourceSafetyTests(unittest.TestCase):
    def test_module_has_no_provider_ui_broker_order_or_env_dependency(self) -> None:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported = imported_module_names(tree)
        for forbidden in (
            "streamlit",
            "dotenv",
            "ibapi",
            "private_quant.broker",
            "private_quant.app.paper_trading",
        ):
            self.assertFalse(any(name == forbidden or name.startswith(forbidden + ".") for name in imported))
        names = referenced_names(tree)
        self.assertNotIn("placeOrder", names)
        self.assertNotIn("build_market_data_provider", names)
        self.assertFalse(any(isinstance(node, ast.Constant) and isinstance(node.value, str) and ".env" in node.value for node in ast.walk(tree)))

    def test_stabilization_module_has_no_qqq_parameter_or_confidence_dependency(self) -> None:
        source = source_path.read_text(encoding="utf-8")
        self.assertNotIn("qqq_bars", source)
        self.assertNotIn("RegimeConfidence", source)
```

Also import public names from `private_quant.backtest` and assert they resolve.

- [ ] **Step 2: Run focused tests and verify RED**

Expected: package exports missing.

- [ ] **Step 3: Add intended exports only**

Modify `src/private_quant/backtest/__init__.py` to import and expose the V1.2 public contracts/functions. Do not export private state-machine or qualification helpers.

- [ ] **Step 4: Run focused and full existing backtest tests**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_regime_stabilization.py" -v
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add src/private_quant/backtest/__init__.py tests/test_regime_stabilization.py
git commit -m "feat: export regime stabilization research api"
```

---

### Task 10: Document V1.2 Research Protocol Without Claiming a Winner

**Files:**
- Modify: `docs/MARKET_REGIME_V1.md`
- Modify: `docs/ROADMAP.md`
- Test: `tests/test_regime_stabilization.py`

**Interfaces:**
- Documentation must describe deterministic implementation status only; no empirical winner or promotion before manual Stage 1/2.

- [ ] **Step 1: Add failing documentation assertions**

Read docs as text and assert they contain:

```python
self.assertIn("Market Regime Stabilization & Re-entry V1.2", market_regime_doc)
self.assertIn("NO_QUALIFIED_CANDIDATE", market_regime_doc)
self.assertIn("2021-01-01", market_regime_doc)
self.assertIn("must be rechecked", roadmap_doc)
self.assertNotIn("V1.2 winner:", market_regime_doc)
self.assertNotIn("PROMOTE_V1_2_RESEARCH confirmed", market_regime_doc)
```

- [ ] **Step 2: Run focused tests and verify RED**

Expected: docs not yet updated.

- [ ] **Step 3: Update research docs**

Add a V1.2 section explaining:

- V1 classifier remains unchanged.
- Fast de-risk / confirmed re-entry overlay only.
- Exact 12-candidate grid.
- Development / Validation / Locked date boundaries.
- 5 bps BIL-cash primary baseline.
- Qualification, deterministic ranking, and locked promotion gates.
- Locked period is not pristine blind OOS.
- Failure outcomes are valid and do not trigger retuning.
- Manual Stage 1 selects/freeze winner through 2020 only after authorization.
- Manual Stage 2 opens 2021+ only after winner review and a second authorization.
- No broker or execution path is added.

In `ROADMAP.md`, add checkboxes for deterministic implementation and tests as complete only after Task 11 verification; leave both manual Stage 1 and Stage 2 empirical validation items unchecked.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run focused suite.

- [ ] **Step 5: Commit**

```powershell
git add docs/MARKET_REGIME_V1.md docs/ROADMAP.md tests/test_regime_stabilization.py
git commit -m "docs: document regime stabilization v1.2 protocol"
```

---

### Task 11: Final Deterministic Verification and Explicit Manual Stage 1 Authorization Gate

**Files:**
- Verify all changed files; no implementation changes unless verification exposes a defect.

**Interfaces:**
- Produces a sanitized completion report only.
- Must stop before reading `.env` or contacting Tiingo.

- [ ] **Step 1: Run focused V1.2 suite**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_regime_stabilization.py" -v
```

Expected: PASS. Record exact test count.

- [ ] **Step 2: Run full repository suite**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: all tests pass; count must be greater than the pre-V1.2 baseline of 269.

- [ ] **Step 3: Run static/runtime integrity checks**

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pip check
git diff --check
git status --short --branch
```

Expected: compileall PASS, pip check reports no broken requirements, `git diff --check` PASS, working tree clean after commits.

- [ ] **Step 4: Prove frozen V1 and execution-path diffs are empty**

Run against the branch base/main merge point:

```powershell
git diff main...HEAD -- src/private_quant/risk/market_regime.py
git diff main...HEAD -- src/private_quant/broker
git diff main...HEAD -- src/private_quant/app/paper_trading.py
git diff main...HEAD -- .env .env.example
```

Expected: all four commands produce no diff. Also verify no configuration or Streamlit application files are changed with:

```powershell
git diff --name-only main...HEAD
```

The changed-file list should be limited to the planned V1.2 module/test/exports/docs/spec/plan files.

- [ ] **Step 5: Scan committed diff for secret/data artifacts**

```powershell
git diff --check main...HEAD
git diff --name-only main...HEAD
```

Confirm no downloaded market-data files, raw provider payloads, API keys, `.env` contents, account data, or validation console dumps are committed.

- [ ] **Step 6: STOP at Manual Tiingo Stage 1 gate**

Do **not** read `.env`, call Tiingo, connect to TWS/IBKR, or run any order path.

Return exactly this information for review:

```text
Branch: <current feature branch>
HEAD: <full SHA>
Changed files: <exact git diff --name-only main...HEAD list>
Focused V1.2 tests: <N> passed
Full suite: <N> passed
compileall: PASS
pip check: PASS
 git diff --check: PASS
Working tree: clean
MarketRegimeEngine diff: empty
Broker/IBKR/order/paper-trading diff: empty
.env/.env.example diff: empty
Configuration/Streamlit diff: empty
Secrets/raw market data/provider payloads committed: NO

I am waiting for authorization to run Manual Tiingo Stage 1 candidate selection through 2020-12-31 only.
```

Manual Stage 1 is **not** part of automated completion and cannot begin without explicit authorization.

---

## Manual Stage 1 Protocol After Separate Authorization

This section is execution guidance for the later authorized run, not permission to run it now.

When explicitly authorized:

1. Read local `.env` only through the existing configuration loader.
2. Fetch only SPY and BIL history needed for V1 warm-up and evaluation through `2020-12-31`; do not fetch 2021+ data for candidate selection.
3. Do not request QQQ for the stabilization study.
4. Run `select_regime_stabilization_candidate` only.
5. Report sanitized SPY/BIL coverage, Development/Validation/Combined baseline metrics, all 12 candidates and gate outcomes, and the exact frozen winner or `NO_QUALIFIED_CANDIDATE`.
6. Do not alter parameters after seeing results.
7. If no candidate qualifies, stop and do not open the locked period.
8. If a candidate wins, stop for human review and explicit freeze/Stage 2 authorization.
9. Never print API keys, `.env` contents, configuration objects, headers, raw responses, or downloaded price history.
10. Never connect to TWS/IBKR or touch order code.

## Manual Stage 2 Protocol After a Second Separate Authorization

Only after a Stage 1 winner has been reviewed and explicitly frozen:

1. Fetch/read the required SPY/BIL history through the latest complete common interval.
2. Pass exactly the frozen Stage 1 candidate to `evaluate_locked_regime_stabilization`.
3. Report locked-period baseline and winner metrics, every promotion gate, re-entry/whipsaw diagnostics, and final `PROMOTE_V1_2_RESEARCH` or `NO_V1_2_PROMOTION`.
4. Run fixed post-selection 0/2/5/10 bps and historical-window diagnostics only after the winner remains frozen.
5. Do not retune or replace the candidate based on locked results.
6. Do not connect to TWS/IBKR or touch orders.
