# Market Regime Evaluation V1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, point-in-time research comparison that measures SPY buy-and-hold, a prior-session 200-session trend benchmark, Regime V1 with zero-yield residual cash, and Regime V1 with BIL-return residual cash across fixed transaction-cost scenarios and historical windows.

**Architecture:** Extend the existing provider-independent `regime_evaluation.py` module without changing `MarketRegimeEngine`. A new public orchestration function will create one exact SPY/BIL interval sequence, derive all four exposure schedules, simulate each schedule at fixed 0/2/5/10 bps costs, calculate immutable metrics, and slice continuous results into fixed historical windows. Every interval record explicitly distinguishes `signal_date`/interval start from `return_end_date`.

**Tech Stack:** Python 3.11+, standard-library `dataclasses`, `enum`, `math`, `statistics`, existing `PriceBar` and `MarketRegimeEngine`, `unittest`, Markdown documentation.

## Global Constraints

- Follow `docs/superpowers/specs/2026-08-27-regime-evaluation-v1-1-design.md` exactly.
- Do not change Market Regime V1 scoring, thresholds, confidence logic, or `100% / 70% / 30% / 0%` exposure mapping.
- A signal using data through `T` applies only to adjusted-close return `T -> T+1`.
- Every `EvaluationPoint` must expose `signal_date` and `return_end_date`; do not add an ambiguous generic `trading_date` field.
- Initial capital exists at `D0` before cost/return, opening cost is charged at `D0`, and the first ending value is dated `D1`.
- BIL adjusted-close return is a residual-cash return proxy only, not a traded BIL position.
- Charge transaction costs only on changes in target SPY exposure; do not model an extra BIL leg.
- Public sensitivity scenarios are fixed at `0`, `2`, `5`, and `10` bps and must not be optimized.
- All four strategies and all cost scenarios must use identical ordered `(signal_date, return_end_date)` pairs.
- Missing, duplicate, malformed, non-finite, or non-positive BIL data inside the active common period fails safely; do not fill or drop internal dates.
- Future valid-dated SPY/BIL content must not alter an earlier bounded evaluation.
- Automated tests use deterministic synthetic fixtures only and must not access `.env`, external providers, brokers, TWS, or order methods.
- Do not add Streamlit UI or modify broker, IBKR, paper-trading, live-trading, or order code.
- Sharpe and Sortino use an explicitly documented zero daily hurdle; no risk-free series is subtracted.
- Preserve the existing `evaluate_regime_history` API and behavior.

---

## File Map

- Modify: `src/private_quant/backtest/regime_evaluation.py`
  - Add immutable V1.1 contracts, point-in-time alignment helpers, exposure schedules, interval simulation, metrics, windows, and `evaluate_regime_v1_1`.
- Modify: `src/private_quant/backtest/__init__.py`
  - Export only the new public V1.1 contracts, constants, error, and evaluator.
- Modify: `tests/test_regime_evaluation.py`
  - Add deterministic V1.1 contract, alignment, look-ahead, signal-lag, cash, cost, metric, window, orchestration, and source-safety tests.
- Modify: `docs/MARKET_REGIME_V1.md`
  - Document V1.1 comparisons, exact interval timeline, BIL proxy, costs, metrics, fixed windows, and limitations.
- Modify: `docs/ROADMAP.md`
  - Add a narrow Evaluation V1.1 implementation/validation status item without implying a methodology or execution change.

No Streamlit, provider, broker, order, configuration, or `.env` file is modified.

---

### Task 1: Add the immutable Evaluation V1.1 contract

**Files:**
- Modify: `src/private_quant/backtest/regime_evaluation.py`
- Modify: `src/private_quant/backtest/__init__.py`
- Test: `tests/test_regime_evaluation.py`

**Interfaces:**
- Consumes: existing `date`, `PriceBar`, and frozen/slotted dataclass style.
- Produces: `EvaluationStrategy`, `EvaluationAvailability`, `ExposureBucketPercentage`, `EvaluationPoint`, `PerformanceMetrics`, `StrategyScenarioResult`, `HistoricalWindowResult`, `RegimeEvaluationV11Result`, `InvalidEvaluationDataError`, and `EVALUATION_TRANSACTION_COST_BPS`.

- [ ] **Step 1: Write failing contract tests**

Add imports for the new names and this test class to `tests/test_regime_evaluation.py`:

```python
class RegimeEvaluationV11ContractTests(unittest.TestCase):
    def test_evaluation_point_has_explicit_interval_dates_and_is_immutable(self) -> None:
        point = EvaluationPoint(
            signal_date=date(2024, 1, 2),
            return_end_date=date(2024, 1, 3),
            starting_value=100.0,
            ending_value=101.0,
            target_spy_exposure=1.0,
            spy_return=0.01,
            residual_cash_return=0.0,
            net_return=0.01,
            exposure_change=1.0,
            transaction_cost=0.0,
        )

        self.assertFalse(hasattr(point, "trading_date"))
        self.assertEqual(point.signal_date, date(2024, 1, 2))
        self.assertEqual(point.return_end_date, date(2024, 1, 3))
        with self.assertRaises(FrozenInstanceError):
            point.ending_value = 102.0

    def test_v11_constants_and_strategy_names_are_fixed(self) -> None:
        self.assertEqual(EVALUATION_TRANSACTION_COST_BPS, (0.0, 2.0, 5.0, 10.0))
        self.assertEqual(
            tuple(strategy.value for strategy in EvaluationStrategy),
            (
                "spy_buy_and_hold",
                "trend_200",
                "regime_v1_zero_yield_cash",
                "regime_v1_bil_cash_proxy",
            ),
        )
```

- [ ] **Step 2: Run the contract tests and confirm RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation.RegimeEvaluationV11ContractTests -v
```

Expected: import errors for the V1.1 types because they do not exist yet.

- [ ] **Step 3: Add the minimal immutable contracts**

Add these exact public shapes to `regime_evaluation.py`:

```python
class InvalidEvaluationDataError(ValueError):
    """Raised when Evaluation V1.1 cannot build a safe common history."""


class EvaluationStrategy(str, Enum):
    SPY_BUY_AND_HOLD = "spy_buy_and_hold"
    TREND_200 = "trend_200"
    REGIME_ZERO_YIELD_CASH = "regime_v1_zero_yield_cash"
    REGIME_BIL_CASH_PROXY = "regime_v1_bil_cash_proxy"


class EvaluationAvailability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


EVALUATION_TRANSACTION_COST_BPS = (0.0, 2.0, 5.0, 10.0)


@dataclass(frozen=True, slots=True)
class ExposureBucketPercentage:
    exposure: float
    percent_sessions: float


@dataclass(frozen=True, slots=True)
class EvaluationPoint:
    signal_date: date
    return_end_date: date
    starting_value: float
    ending_value: float
    target_spy_exposure: float
    spy_return: float
    residual_cash_return: float
    net_return: float
    exposure_change: float
    transaction_cost: float


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    initial_capital: float
    final_value: float
    total_return: float
    cagr: float | None
    max_drawdown: float
    annualized_volatility: float | None
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    total_transaction_cost: float
    annualized_turnover: float | None
    exposure_changes: int
    average_spy_exposure: float | None
    exposure_buckets: tuple[ExposureBucketPercentage, ...]


@dataclass(frozen=True, slots=True)
class StrategyScenarioResult:
    strategy: EvaluationStrategy
    transaction_cost_bps: float
    first_signal_date: date
    final_return_end_date: date
    metrics: PerformanceMetrics
    points: tuple[EvaluationPoint, ...]


@dataclass(frozen=True, slots=True)
class HistoricalWindowResult:
    window_name: str
    requested_start: date
    requested_end: date
    strategy: EvaluationStrategy
    transaction_cost_bps: float
    availability: EvaluationAvailability
    effective_signal_date: date | None
    effective_return_end_date: date | None
    interval_count: int
    normalized_start_value: float | None
    normalized_end_value: float | None
    strategy_return: float | None
    max_drawdown: float | None
    exposure_changes: int | None
    average_spy_exposure: float | None
    transaction_cost: float | None


@dataclass(frozen=True, slots=True)
class RegimeEvaluationV11Result:
    common_intervals: tuple[tuple[date, date], ...]
    scenarios: tuple[StrategyScenarioResult, ...]
    windows: tuple[HistoricalWindowResult, ...]
```

Import `Enum`, add the new public names to `regime_evaluation.py::__all__`, and re-export them from `src/private_quant/backtest/__init__.py`. Do not alter existing types.

- [ ] **Step 4: Run contract and existing evaluator tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the contract**

```powershell
git add -- src/private_quant/backtest/regime_evaluation.py src/private_quant/backtest/__init__.py tests/test_regime_evaluation.py
git commit -m "feat: add regime evaluation v1.1 contracts"
```

---

### Task 2: Build exact SPY/BIL interval alignment and common-start truncation

**Files:**
- Modify: `src/private_quant/backtest/regime_evaluation.py`
- Test: `tests/test_regime_evaluation.py`

**Interfaces:**
- Consumes: canonical dates from `_canonical_trading_date`, SPY/BIL `PriceBar` sequences, optional evaluation start/end.
- Produces: private `_PriceInterval`, `_AlignedEvaluationHistory`, and `_align_evaluation_history(...)` used by all later tasks.

- [ ] **Step 1: Add deterministic series helpers and failing alignment tests**

Add a symbol-aware helper in the test file:

```python
def make_symbol_bars(
    symbol: str,
    dates: list[date],
    prices: list[float] | None = None,
) -> list[PriceBar]:
    closes = prices or [100.0 + index for index in range(len(dates))]
    return [
        PriceBar(symbol, day, close, close, close, close, close, 1_000_000)
        for day, close in zip(dates, closes)
    ]
```

Add tests that use deterministic synthetic session dates and call `_align_evaluation_history`:

```python
class RegimeEvaluationV11AlignmentTests(unittest.TestCase):
    def test_bil_late_start_truncates_to_one_exact_common_interval_sequence(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(260)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates[254:])

        aligned = _align_evaluation_history(spy, bil)

        self.assertEqual(aligned.intervals[0].signal_date, dates[254])
        self.assertEqual(aligned.intervals[0].return_end_date, dates[255])
        self.assertEqual(aligned.intervals[-1].return_end_date, dates[-1])
        self.assertEqual(
            tuple((item.signal_date, item.return_end_date) for item in aligned.intervals),
            tuple(zip(dates[254:-1], dates[255:])),
        )

    def test_missing_internal_bil_date_fails_instead_of_intersecting_it_away(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(258)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates[251:254] + dates[255:])

        with self.assertRaisesRegex(
            InvalidEvaluationDataError,
            "BIL history is missing an active SPY trading date",
        ):
            _align_evaluation_history(spy, bil)

    def test_explicit_start_and_end_select_complete_interval_boundaries(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(260)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)

        aligned = _align_evaluation_history(
            spy,
            bil,
            evaluation_start=dates[253],
            evaluation_end=dates[257],
        )

        self.assertEqual(
            tuple((item.signal_date, item.return_end_date) for item in aligned.intervals),
            tuple(zip(dates[253:257], dates[254:258])),
        )
```

- [ ] **Step 2: Run alignment tests and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation.RegimeEvaluationV11AlignmentTests -v
```

Expected: import/name errors for `_align_evaluation_history`.

- [ ] **Step 3: Implement date-first alignment without filling data**

Add private immutable structures:

```python
@dataclass(frozen=True, slots=True)
class _PriceInterval:
    signal_date: date
    return_end_date: date
    spy_return: float
    bil_return: float


@dataclass(frozen=True, slots=True)
class _AlignedEvaluationHistory:
    spy_history: tuple[PriceBar, ...]
    intervals: tuple[_PriceInterval, ...]
```

Implement `_align_evaluation_history` with this exact contract:

```python
def _align_evaluation_history(
    spy_bars: Sequence[PriceBar],
    bil_bars: Sequence[PriceBar],
    *,
    evaluation_start: date | None = None,
    evaluation_end: date | None = None,
) -> _AlignedEvaluationHistory:
    """Build one exact SPY/BIL interval sequence after 252-session warm-up."""
```

The helper must:

1. canonicalize dates before reading symbol or adjusted-close content;
2. use the earlier of requested end, last SPY date, and last BIL date as the outer return-end boundary;
3. retain enough SPY history before the common start for the unchanged 252-session regime warm-up;
4. define the first eligible signal at SPY index 251;
5. set first common signal to the first eligible SPY date on/after both requested start and BIL's first canonical date;
6. require exact BIL observations for every SPY signal and return-end date after that start;
7. reject active duplicates, wrong symbols, malformed/non-finite/non-positive adjusted closes with fixed messages; and
8. construct only consecutive SPY `(signal_date, return_end_date)` pairs.

Use `_finite_number` for numeric conversion, but explicitly reject values `<= 0`. Do not forward-fill or scan past a missing BIL date to find a later start.

- [ ] **Step 4: Run alignment and existing point-in-time tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit exact alignment**

```powershell
git add -- src/private_quant/backtest/regime_evaluation.py tests/test_regime_evaluation.py
git commit -m "feat: align regime evaluation spy and bil dates"
```

---

### Task 3: Enforce active-period validation and future-data isolation

**Files:**
- Modify: `src/private_quant/backtest/regime_evaluation.py`
- Test: `tests/test_regime_evaluation.py`

**Interfaces:**
- Consumes: `_align_evaluation_history(...)` from Task 2.
- Produces: stable bounded output when valid-dated future SPY/BIL content is malformed; safe failures for active data and unplaceable dates.

- [ ] **Step 1: Write failing active-data and future-contamination regressions**

Add table-driven mutation helpers that bypass `PriceBar.__post_init__` only inside tests:

```python
def replace_field(bar: PriceBar, field: str, value: object) -> PriceBar:
    changed = object.__new__(PriceBar)
    for name in (
        "symbol", "trading_date", "open", "high", "low", "close",
        "adjusted_close", "volume",
    ):
        object.__setattr__(changed, name, value if name == field else getattr(bar, name))
    return changed


def without_field(bar: PriceBar, omitted: str) -> PriceBar:
    changed = object.__new__(PriceBar)
    for name in (
        "symbol", "trading_date", "open", "high", "low", "close",
        "adjusted_close", "volume",
    ):
        if name != omitted:
            object.__setattr__(changed, name, getattr(bar, name))
    return changed
```

Add these method bodies inside `RegimeEvaluationV11AlignmentTests`:

```python
def test_future_invalid_bil_content_cannot_change_earlier_alignment(self) -> None:
    dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(260)]
    spy = make_symbol_bars("SPY", dates)
    bil = make_symbol_bars("BIL", dates)
    cutoff = dates[257]
    baseline = _align_evaluation_history(spy, bil, evaluation_end=cutoff)

    for field, value in (
        ("adjusted_close", float("nan")),
        ("adjusted_close", float("inf")),
        ("adjusted_close", 0.0),
        ("adjusted_close", -1.0),
        ("adjusted_close", "malformed"),
        ("symbol", "SPY"),
    ):
        with self.subTest(field=field, value=value):
            changed = bil[:-1] + [replace_field(bil[-1], field, value)]
            self.assertEqual(
                _align_evaluation_history(spy, changed, evaluation_end=cutoff),
                baseline,
            )
    self.assertEqual(
        _align_evaluation_history(
            spy,
            bil[:-1] + [without_field(bil[-1], "adjusted_close")],
            evaluation_end=cutoff,
        ),
        baseline,
    )
    self.assertEqual(
        _align_evaluation_history(spy, bil + [bil[-1]], evaluation_end=cutoff),
        baseline,
    )

def test_future_invalid_spy_content_cannot_change_earlier_alignment(self) -> None:
    dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(260)]
    spy = make_symbol_bars("SPY", dates)
    bil = make_symbol_bars("BIL", dates)
    cutoff = dates[257]
    baseline = _align_evaluation_history(spy, bil, evaluation_end=cutoff)
    for field, value in (
        ("adjusted_close", float("nan")),
        ("adjusted_close", float("inf")),
        ("adjusted_close", 0.0),
        ("adjusted_close", -1.0),
        ("adjusted_close", "malformed"),
        ("symbol", "QQQ"),
    ):
        with self.subTest(field=field, value=value):
            changed = spy[:-1] + [replace_field(spy[-1], field, value)]
            self.assertEqual(
                _align_evaluation_history(changed, bil, evaluation_end=cutoff),
                baseline,
            )
    self.assertEqual(
        _align_evaluation_history(
            spy[:-1] + [without_field(spy[-1], "adjusted_close")],
            bil,
            evaluation_end=cutoff,
        ),
        baseline,
    )

def test_invalid_active_bil_values_fail_with_fixed_message(self) -> None:
    dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(258)]
    spy = make_symbol_bars("SPY", dates)
    bil = make_symbol_bars("BIL", dates)

    for value in (float("nan"), float("inf"), 0.0, -1.0, "malformed", 10 ** 1000):
        with self.subTest(value=value), self.assertRaisesRegex(
            InvalidEvaluationDataError,
            "BIL adjusted close must be finite and positive",
        ):
            changed = bil[:253] + [replace_field(bil[253], "adjusted_close", value)] + bil[254:]
            _align_evaluation_history(spy, changed)
    with self.assertRaisesRegex(
        InvalidEvaluationDataError,
        "BIL adjusted close must be finite and positive",
    ):
        changed = bil[:253] + [without_field(bil[253], "adjusted_close")] + bil[254:]
        _align_evaluation_history(spy, changed)

def test_invalid_active_spy_value_fails_at_the_v11_boundary(self) -> None:
    dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(258)]
    spy = make_symbol_bars("SPY", dates)
    bil = make_symbol_bars("BIL", dates)
    changed = spy[:253] + [replace_field(spy[253], "adjusted_close", float("nan"))] + spy[254:]

    with self.assertRaisesRegex(
        InvalidEvaluationDataError,
        "SPY adjusted close must be finite and positive",
    ):
        _align_evaluation_history(changed, bil)

def test_missing_or_unparseable_date_fails_because_temporal_position_is_unknown(self) -> None:
    dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(258)]
    spy = make_symbol_bars("SPY", dates)
    bil = make_symbol_bars("BIL", dates)
    changed = bil[:-1] + [replace_field(bil[-1], "trading_date", "not-a-date")]

    with self.assertRaisesRegex(InvalidEvaluationDataError, "BIL trading date is invalid"):
        _align_evaluation_history(spy, changed, evaluation_end=dates[-2])
```

Add these active duplicate-date and wrong-symbol cases in the same class:

```python
def test_active_duplicate_dates_fail_with_fixed_messages(self) -> None:
    dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(258)]
    spy = make_symbol_bars("SPY", dates)
    bil = make_symbol_bars("BIL", dates)
    duplicate_spy = spy + [spy[-1]]
    duplicate_bil = bil + [bil[-1]]

    with self.assertRaisesRegex(InvalidEvaluationDataError, "SPY has duplicate active trading dates"):
        _align_evaluation_history(duplicate_spy, bil)
    with self.assertRaisesRegex(InvalidEvaluationDataError, "BIL has duplicate active trading dates"):
        _align_evaluation_history(spy, duplicate_bil)

def test_active_wrong_symbols_fail_with_fixed_messages(self) -> None:
    dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(258)]
    spy = make_symbol_bars("SPY", dates)
    bil = make_symbol_bars("BIL", dates)
    wrong_spy = spy[:253] + [replace_field(spy[253], "symbol", "QQQ")] + spy[254:]
    wrong_bil = bil[:253] + [replace_field(bil[253], "symbol", "SPY")] + bil[254:]

    with self.assertRaisesRegex(InvalidEvaluationDataError, "SPY history contains the wrong symbol"):
        _align_evaluation_history(wrong_spy, bil)
    with self.assertRaisesRegex(InvalidEvaluationDataError, "BIL history contains the wrong symbol"):
        _align_evaluation_history(spy, wrong_bil)
```

- [ ] **Step 2: Run the new regressions and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation.RegimeEvaluationV11AlignmentTests -v
```

Expected: at least the future malformed-content cases fail if alignment validates content before applying the end boundary.

- [ ] **Step 3: Move content validation behind the canonical-date boundary**

Refine alignment into two private phases:

```python
def _date_bars(bars: Sequence[PriceBar], *, series_name: str) -> tuple[tuple[date, PriceBar], ...]:
    """Read only canonical dates, failing when temporal placement is impossible."""


def _validate_active_bars(
    dated_bars: Sequence[tuple[date, PriceBar]],
    *,
    symbol: str,
    start: date | None,
    end: date,
) -> tuple[tuple[date, PriceBar], ...]:
    """Validate symbol/date/adjusted close only inside the active boundary."""
```

`_date_bars` may inspect only `trading_date`. `_validate_active_bars` filters by canonical date before reading `symbol` or `adjusted_close`. Duplicate detection also occurs after the active boundary is selected. Treat missing attributes, `TypeError`, `ValueError`, and numeric `OverflowError` as fixed `InvalidEvaluationDataError` failures; never include `repr(bar)`, raw values, or provider exceptions.

- [ ] **Step 4: Run all point-in-time and alignment tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation tests.test_market_regime.MarketRegimeEngineTests -v
```

Expected: all selected tests pass, including existing QQQ no-look-ahead regressions.

- [ ] **Step 5: Commit point-in-time isolation**

```powershell
git add -- src/private_quant/backtest/regime_evaluation.py tests/test_regime_evaluation.py
git commit -m "fix: isolate future regime evaluation prices"
```

---

### Task 4: Derive the four point-in-time exposure schedules

**Files:**
- Modify: `src/private_quant/backtest/regime_evaluation.py`
- Test: `tests/test_regime_evaluation.py`

**Interfaces:**
- Consumes: `_AlignedEvaluationHistory`, optional QQQ bars, optional `MarketRegimeEngine`.
- Produces: `_target_exposures(...) -> Mapping[EvaluationStrategy, tuple[float, ...]]` in exact interval order.

- [ ] **Step 1: Write failing exposure and one-session-lag tests**

Use the existing `RecordingEngine` and add this class:

```python
class RegimeEvaluationV11ExposureTests(unittest.TestCase):
    def test_target_exposures_use_signal_date_data_and_preserve_v1_mapping(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(255)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)
        aligned = _align_evaluation_history(spy, bil)
        expected = (1.0, 0.7, 0.3)
        engine = RecordingEngine(
            lambda as_of, visible: (
                (MarketRegime.BULL, 1.0),
                (MarketRegime.CAUTIOUS_BULL, 0.7),
                (MarketRegime.RISK_OFF, 0.3),
            )[dates[251:254].index(as_of)]
        )

        exposures = _target_exposures(aligned, engine=engine)

        self.assertEqual(exposures[EvaluationStrategy.SPY_BUY_AND_HOLD], (1.0, 1.0, 1.0))
        self.assertEqual(exposures[EvaluationStrategy.REGIME_ZERO_YIELD_CASH], expected)
        self.assertEqual(exposures[EvaluationStrategy.REGIME_BIL_CASH_PROXY], expected)
        self.assertEqual(tuple(call[0] for call in engine.calls), tuple(dates[251:254]))
        for signal_date, visible, _ in engine.calls:
            self.assertLessEqual(max(bar.trading_date for bar in visible), signal_date)

    def test_trend_signal_uses_200_closes_through_signal_date_and_equality_is_risk_on(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(254)]
        prices = [100.0] * 252 + [90.0, 90.0]
        spy = make_symbol_bars("SPY", dates, prices)
        bil = make_symbol_bars("BIL", dates)
        aligned = _align_evaluation_history(spy, bil)

        exposures = _target_exposures(aligned, engine=RecordingEngine())

        self.assertEqual(exposures[EvaluationStrategy.TREND_200], (1.0, 0.0))
```

The first assertion proves equality with the 200-session SMA is risk-on. The
second signal sees the lower close only after it occurs and applies it to the
next interval.

- [ ] **Step 2: Run the exposure tests and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation.RegimeEvaluationV11ExposureTests -v
```

Expected: `_target_exposures` is not defined.

- [ ] **Step 3: Implement schedules without changing the engine**

Implement:

```python
def _target_exposures(
    aligned: _AlignedEvaluationHistory,
    *,
    qqq_bars: Sequence[PriceBar] | None = None,
    engine: MarketRegimeEngine | None = None,
) -> Mapping[EvaluationStrategy, tuple[float, ...]]:
```

For each `signal_date`:

- buy-and-hold exposure is `1.0`;
- trend exposure is `1.0` when the SPY adjusted close at `signal_date` is `>= fmean(last_200_adjusted_closes)`, otherwise `0.0`;
- call the unchanged classifier with SPY and optional QQQ histories dated `<= signal_date`;
- use `result.maximum_long_exposure` unchanged for both Regime variants; and
- assert the regime result belongs to `(0.0, 0.3, 0.7, 1.0)`, raising a fixed evaluation error otherwise.

Do not copy scoring logic or use confidence to alter exposure.

- [ ] **Step 4: Run exposure, regime-engine, and old evaluator tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation.RegimeEvaluationV11ExposureTests tests.test_regime_evaluation tests.test_market_regime -v
```

Expected: all tests pass and existing Market Regime V1 outputs remain unchanged.

- [ ] **Step 5: Commit exposure schedules**

```powershell
git add -- src/private_quant/backtest/regime_evaluation.py tests/test_regime_evaluation.py
git commit -m "feat: add regime evaluation exposure schedules"
```

---

### Task 5: Simulate interval returns, BIL cash proxy, and transaction costs

**Files:**
- Modify: `src/private_quant/backtest/regime_evaluation.py`
- Test: `tests/test_regime_evaluation.py`

**Interfaces:**
- Consumes: ordered `_PriceInterval` values, an equal-length exposure tuple, strategy, capital, and one cost rate.
- Produces: `_simulate_intervals(...) -> tuple[EvaluationPoint, ...]` with explicit D0/D1 value ownership.

- [ ] **Step 1: Write failing cash and cost arithmetic tests**

```python
class RegimeEvaluationV11SimulationTests(unittest.TestCase):
    def test_first_point_charges_opening_cost_at_d0_and_dates_ending_value_d1(self) -> None:
        interval = _PriceInterval(date(2024, 1, 2), date(2024, 1, 3), 0.10, 0.01)

        points = _simulate_intervals(
            (interval,),
            (1.0,),
            strategy=EvaluationStrategy.SPY_BUY_AND_HOLD,
            initial_capital=100.0,
            transaction_cost_bps=10.0,
        )

        point = points[0]
        self.assertEqual(point.signal_date, date(2024, 1, 2))
        self.assertEqual(point.return_end_date, date(2024, 1, 3))
        self.assertAlmostEqual(point.starting_value, 100.0)
        self.assertAlmostEqual(point.exposure_change, 1.0)
        self.assertAlmostEqual(point.transaction_cost, 0.1)
        self.assertAlmostEqual(point.ending_value, 109.89)
        self.assertAlmostEqual(point.net_return, 0.0989)

    def test_bil_proxy_applies_only_to_residual_weight_without_second_cost_leg(self) -> None:
        interval = _PriceInterval(date(2024, 1, 2), date(2024, 1, 3), 0.10, 0.01)

        zero_cash = _simulate_intervals(
            (interval,), (0.3,),
            strategy=EvaluationStrategy.REGIME_ZERO_YIELD_CASH,
            initial_capital=100.0, transaction_cost_bps=0.0,
        )[0]
        bil_cash = _simulate_intervals(
            (interval,), (0.3,),
            strategy=EvaluationStrategy.REGIME_BIL_CASH_PROXY,
            initial_capital=100.0, transaction_cost_bps=0.0,
        )[0]

        self.assertAlmostEqual(zero_cash.ending_value, 103.0)
        self.assertAlmostEqual(zero_cash.residual_cash_return, 0.0)
        self.assertAlmostEqual(bil_cash.ending_value, 103.7)
        self.assertAlmostEqual(bil_cash.residual_cash_return, 0.01)
        self.assertEqual(bil_cash.transaction_cost, 0.0)

    def test_unchanged_target_has_no_new_cost_and_intervals_chain_exactly(self) -> None:
        intervals = (
            _PriceInterval(date(2024, 1, 2), date(2024, 1, 3), 0.01, 0.001),
            _PriceInterval(date(2024, 1, 3), date(2024, 1, 4), 0.02, 0.001),
        )
        points = _simulate_intervals(
            intervals, (0.7, 0.7),
            strategy=EvaluationStrategy.REGIME_ZERO_YIELD_CASH,
            initial_capital=100.0, transaction_cost_bps=5.0,
        )

        self.assertGreater(points[0].transaction_cost, 0.0)
        self.assertEqual(points[1].transaction_cost, 0.0)
        self.assertEqual(points[0].return_end_date, points[1].signal_date)
        self.assertEqual(points[0].ending_value, points[1].starting_value)

    def test_invalid_capital_and_cost_inputs_fail_closed(self) -> None:
        interval = _PriceInterval(date(2024, 1, 2), date(2024, 1, 3), 0.01, 0.001)
        for capital in (True, 0.0, -1.0, float("nan"), float("inf")):
            with self.subTest(capital=capital), self.assertRaises(ValueError):
                _simulate_intervals(
                    (interval,), (1.0,),
                    strategy=EvaluationStrategy.SPY_BUY_AND_HOLD,
                    initial_capital=capital,
                    transaction_cost_bps=0.0,
                )
        for cost in (True, -1.0, float("nan"), float("inf")):
            with self.subTest(cost=cost), self.assertRaises(ValueError):
                _simulate_intervals(
                    (interval,), (1.0,),
                    strategy=EvaluationStrategy.SPY_BUY_AND_HOLD,
                    initial_capital=100.0,
                    transaction_cost_bps=cost,
                )
```

- [ ] **Step 2: Run simulation tests and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation.RegimeEvaluationV11SimulationTests -v
```

Expected: `_simulate_intervals` is not defined.

- [ ] **Step 3: Implement the exact cost-before-return timeline**

```python
def _simulate_intervals(
    intervals: Sequence[_PriceInterval],
    exposures: Sequence[float],
    *,
    strategy: EvaluationStrategy,
    initial_capital: float,
    transaction_cost_bps: float,
) -> tuple[EvaluationPoint, ...]:
```

Validate equal lengths, positive finite capital, and non-negative finite cost. Initialize `prior_exposure = 0.0`. For each interval use:

```python
cash_return = (
    interval.bil_return
    if strategy is EvaluationStrategy.REGIME_BIL_CASH_PROXY
    else 0.0
)
gross_return = exposure * interval.spy_return + (1.0 - exposure) * cash_return
exposure_change = abs(exposure - prior_exposure)
cost = starting_value * exposure_change * transaction_cost_bps / 10_000.0
ending_value = (starting_value - cost) * (1.0 + gross_return)
net_return = ending_value / starting_value - 1.0
```

Reject an exposure outside `[0.0, 1.0]`, non-finite calculations, non-positive resulting equity, or non-consecutive interval boundaries with fixed messages. Do not add a BIL exposure or cost variable.

- [ ] **Step 4: Run simulation and old comparison tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation -v
```

Expected: all selected tests pass, including the existing V1 cost comparison.

- [ ] **Step 5: Commit simulation mechanics**

```powershell
git add -- src/private_quant/backtest/regime_evaluation.py tests/test_regime_evaluation.py
git commit -m "feat: simulate regime evaluation cash and costs"
```

---

### Task 6: Calculate deterministic performance, turnover, and exposure metrics

**Files:**
- Modify: `src/private_quant/backtest/regime_evaluation.py`
- Test: `tests/test_regime_evaluation.py`

**Interfaces:**
- Consumes: initial capital, immutable interval points, and the strategy's applicable exposure buckets.
- Produces: `_performance_metrics(...) -> PerformanceMetrics` using the approved formulas and zero hurdle.

- [ ] **Step 1: Write failing hand-calculated metric tests**

Import `math` in the test file. Create two chained points with starting values
`100` and `110`, ending values `110` and `99`, exposures `0.3` and `0.7`,
exposure changes `0.3` and `0.4`, and dates January 1-3, 2024. Add:

```python
def metric_fixture_points() -> tuple[EvaluationPoint, ...]:
    return (
        EvaluationPoint(
            date(2024, 1, 1), date(2024, 1, 2),
            100.0, 110.0, 0.3, 0.10, 0.0, 0.10, 0.3, 0.0,
        ),
        EvaluationPoint(
            date(2024, 1, 2), date(2024, 1, 3),
            110.0, 99.0, 0.7, -0.10, 0.0, -0.10, 0.4, 0.0,
        ),
    )


class RegimeEvaluationV11PerformanceMetricTests(unittest.TestCase):
    def test_metrics_match_deterministic_two_interval_fixture(self) -> None:
        metrics = _performance_metrics(
            100.0,
            metric_fixture_points(),
            applicable_exposures=(0.0, 0.3, 0.7, 1.0),
        )

        expected_cagr = (99.0 / 100.0) ** (365.25 / 2.0) - 1.0
        self.assertEqual(metrics.initial_capital, 100.0)
        self.assertEqual(metrics.final_value, 99.0)
        self.assertAlmostEqual(metrics.total_return, -0.01)
        self.assertAlmostEqual(metrics.cagr, expected_cagr)
        self.assertAlmostEqual(metrics.max_drawdown, -0.10)
        self.assertAlmostEqual(metrics.annualized_volatility, 0.1 * math.sqrt(252.0))
        self.assertAlmostEqual(metrics.sharpe, 0.0)
        self.assertAlmostEqual(metrics.sortino, 0.0)
        self.assertAlmostEqual(metrics.calmar, expected_cagr / 0.10)
        self.assertAlmostEqual(metrics.annualized_turnover, 88.8)
        self.assertEqual(metrics.exposure_changes, 2)
        self.assertAlmostEqual(metrics.average_spy_exposure, 0.5)
        self.assertEqual(
            tuple((bucket.exposure, bucket.percent_sessions) for bucket in metrics.exposure_buckets),
            ((0.0, 0.0), (0.3, 50.0), (0.7, 50.0), (1.0, 0.0)),
        )
        self.assertAlmostEqual(
            sum(bucket.percent_sessions for bucket in metrics.exposure_buckets),
            100.0,
        )

    def test_zero_denominators_are_none_instead_of_invented_ratios(self) -> None:
        point = EvaluationPoint(
            date(2024, 1, 2), date(2024, 1, 3),
            100.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        )
        metrics = _performance_metrics(
            100.0,
            (point,),
            applicable_exposures=(0.0, 1.0),
        )

        self.assertIsNone(metrics.annualized_volatility)
        self.assertIsNone(metrics.sharpe)
        self.assertIsNone(metrics.sortino)
        self.assertIsNone(metrics.calmar)
```

Add a strategy-specific bucket test:

```python
    def test_applicable_exposure_buckets_are_not_invented(self) -> None:
        buy_hold_point = EvaluationPoint(
            date(2024, 1, 1), date(2024, 1, 2),
            100.0, 101.0, 1.0, 0.01, 0.0, 0.01, 1.0, 0.0,
        )
        buy_hold = _performance_metrics(
            100.0,
            (buy_hold_point,),
            applicable_exposures=(1.0,),
        )
        trend = _performance_metrics(
            100.0,
            (
                EvaluationPoint(
                    date(2024, 1, 1), date(2024, 1, 2),
                    100.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                ),
                EvaluationPoint(
                    date(2024, 1, 2), date(2024, 1, 3),
                    100.0, 101.0, 1.0, 0.01, 0.0, 0.01, 1.0, 0.0,
                ),
            ),
            applicable_exposures=(0.0, 1.0),
        )

        self.assertEqual(
            tuple(bucket.exposure for bucket in buy_hold.exposure_buckets),
            (1.0,),
        )
        self.assertEqual(
            tuple(bucket.exposure for bucket in trend.exposure_buckets),
            (0.0, 1.0),
        )
        self.assertAlmostEqual(
            sum(bucket.percent_sessions for bucket in trend.exposure_buckets),
            100.0,
        )
```

- [ ] **Step 2: Run metrics tests and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation.RegimeEvaluationV11PerformanceMetricTests -v
```

Expected: `_performance_metrics` is not defined.

- [ ] **Step 3: Implement each documented formula directly**

```python
def _performance_metrics(
    initial_capital: float,
    points: Sequence[EvaluationPoint],
    *,
    applicable_exposures: Sequence[float],
) -> PerformanceMetrics:
```

Implementation rules:

Add `pstdev` to the evaluator's existing `statistics` imports; the module
already imports `math`.

- value path is `[initial_capital] + [point.ending_value ...]`;
- daily net returns are `point.net_return`;
- CAGR uses calendar days between first `signal_date` and last `return_end_date` with `365.25`;
- drawdown uses the running peak including initial capital;
- volatility uses `pstdev(returns) * sqrt(252)` and requires at least two returns;
- Sharpe uses `fmean(returns) / pstdev(returns) * sqrt(252)` with zero hurdle;
- downside deviation is `sqrt(fmean(min(value, 0.0) ** 2 for value in returns))` over all returns;
- Calmar is `cagr / abs(max_drawdown)`;
- traded notional is `point.starting_value * point.exposure_change`;
- annualized turnover is `(sum_notional / mean_starting_value) / (len(points) / 252)`;
- exposure changes count values greater than a small numeric tolerance;
- average exposure is an arithmetic interval mean; and
- exposure buckets retain the caller-supplied order and report percentages from interval counts.

Return `None` exactly where the approved spec defines an undefined denominator.

- [ ] **Step 4: Run metric, simulation, and ETF metric regressions**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation.RegimeEvaluationV11PerformanceMetricTests tests.test_regime_evaluation.RegimeEvaluationV11SimulationTests tests.test_etf_momentum -v
```

Expected: all selected tests pass; the unrelated ETF backtest remains unchanged.

- [ ] **Step 5: Commit metrics**

```powershell
git add -- src/private_quant/backtest/regime_evaluation.py tests/test_regime_evaluation.py
git commit -m "feat: add regime evaluation performance metrics"
```

---

### Task 7: Add continuous historical-window summaries

**Files:**
- Modify: `src/private_quant/backtest/regime_evaluation.py`
- Test: `tests/test_regime_evaluation.py`

**Interfaces:**
- Consumes: one `StrategyScenarioResult` and `HISTORICAL_REGIME_WINDOWS`.
- Produces: `_historical_window_result(...) -> HistoricalWindowResult` and all fixed window rows without resetting exposure.

- [ ] **Step 1: Write failing boundary and rebasing tests**

Use points spanning December 31, 2019 through January 6, 2020. Make the first included interval `2020-01-02 -> 2020-01-03` start at `110`, end at `121`, and incur cost `1.10`. Add:

```python
def window_fixture_scenario() -> StrategyScenarioResult:
    points = (
        EvaluationPoint(
            date(2019, 12, 31), date(2020, 1, 2),
            100.0, 110.0, 0.3, 0.10, 0.0, 0.10, 0.3, 0.0,
        ),
        EvaluationPoint(
            date(2020, 1, 2), date(2020, 1, 3),
            110.0, 121.0, 0.7, 0.10, 0.0, 0.10, 0.4, 1.10,
        ),
        EvaluationPoint(
            date(2020, 1, 3), date(2020, 1, 6),
            121.0, 108.9, 0.3, -0.10, 0.0, -0.10, 0.4, 1.21,
        ),
    )
    return StrategyScenarioResult(
        strategy=EvaluationStrategy.REGIME_ZERO_YIELD_CASH,
        transaction_cost_bps=100.0,
        first_signal_date=points[0].signal_date,
        final_return_end_date=points[-1].return_end_date,
        metrics=_performance_metrics(
            100.0,
            points,
            applicable_exposures=(0.0, 0.3, 0.7, 1.0),
        ),
        points=points,
    )


class RegimeEvaluationV11WindowTests(unittest.TestCase):
    def test_window_uses_complete_intervals_and_rebases_pre_cost_start_to_100(self) -> None:
        scenario = window_fixture_scenario()

        result = _historical_window_result(
            scenario,
            window_name="Calendar 2020",
            requested_start=date(2020, 1, 1),
            requested_end=date(2020, 12, 31),
        )

        self.assertIs(result.availability, EvaluationAvailability.AVAILABLE)
        self.assertEqual(result.effective_signal_date, date(2020, 1, 2))
        self.assertEqual(result.effective_return_end_date, date(2020, 1, 6))
        self.assertEqual(result.normalized_start_value, 100.0)
        self.assertAlmostEqual(
            result.normalized_end_value,
            scenario.points[-1].ending_value / 110.0 * 100.0,
        )
        self.assertAlmostEqual(
            result.transaction_cost,
            sum(point.transaction_cost for point in scenario.points[1:]) / 110.0 * 100.0,
        )
        self.assertEqual(
            result.exposure_changes,
            sum(point.exposure_change > 1e-12 for point in scenario.points[1:]),
        )

    def test_window_does_not_include_interval_that_only_ends_inside_window(self) -> None:
        result = _historical_window_result(
            window_fixture_scenario(),
            window_name="Calendar 2020",
            requested_start=date(2020, 1, 1),
            requested_end=date(2020, 12, 31),
        )
        self.assertNotEqual(result.effective_signal_date, date(2019, 12, 31))

    def test_window_without_complete_interval_is_explicitly_unavailable(self) -> None:
        result = _historical_window_result(
            window_fixture_scenario(),
            window_name="Calendar 2022",
            requested_start=date(2022, 1, 1),
            requested_end=date(2022, 12, 31),
        )

        self.assertIs(result.availability, EvaluationAvailability.UNAVAILABLE)
        self.assertIsNone(result.effective_signal_date)
        self.assertIsNone(result.effective_return_end_date)
        self.assertIsNone(result.normalized_end_value)
```

- [ ] **Step 2: Run window tests and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation.RegimeEvaluationV11WindowTests -v
```

Expected: `_historical_window_result` is not defined.

- [ ] **Step 3: Implement complete-interval slicing**

Reuse the existing immutable `HISTORICAL_REGIME_WINDOWS` boundaries without
changing or selecting them from results:

```python
{
    "2008 financial crisis": (date(2007, 10, 1), date(2009, 6, 30)),
    "2020 COVID crash and recovery": (date(2020, 1, 1), date(2020, 12, 31)),
    "2022 bear market": (date(2022, 1, 1), date(2022, 12, 31)),
    "2023-2025 recovery and bull period": (date(2023, 1, 1), date(2025, 12, 31)),
}
```

```python
def _historical_window_result(
    scenario: StrategyScenarioResult,
    *,
    window_name: str,
    requested_start: date,
    requested_end: date,
) -> HistoricalWindowResult:
```

Select only points satisfying both:

```python
requested_start <= point.signal_date
point.return_end_date <= requested_end
```

If none match, return the unavailable model with every optional metric `None` and interval count zero. Otherwise:

- normalize from the first included point's `starting_value`, before its cost;
- do not recompute exposure changes or create a boundary trade;
- include costs already stored on included points and scale them by the same `100 / starting_value` factor;
- calculate drawdown from normalized start `100` and included ending values;
- use existing point exposure changes and arithmetic average exposure; and
- report first included `signal_date` and last included `return_end_date`.

- [ ] **Step 4: Run window and metric tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation.RegimeEvaluationV11WindowTests tests.test_regime_evaluation.RegimeEvaluationV11PerformanceMetricTests -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit window summaries**

```powershell
git add -- src/private_quant/backtest/regime_evaluation.py tests/test_regime_evaluation.py
git commit -m "feat: add regime evaluation historical windows"
```

---

### Task 8: Orchestrate all strategies and fixed cost scenarios safely

**Files:**
- Modify: `src/private_quant/backtest/regime_evaluation.py`
- Modify: `src/private_quant/backtest/__init__.py`
- Test: `tests/test_regime_evaluation.py`

**Interfaces:**
- Consumes: all helpers from Tasks 2-7.
- Produces: public `evaluate_regime_v1_1(...) -> RegimeEvaluationV11Result`.

- [ ] **Step 1: Write failing end-to-end deterministic tests**

```python
class RegimeEvaluationV11IntegrationTests(unittest.TestCase):
    def test_all_strategies_and_costs_share_exact_interval_pairs(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(260)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates, [100.0 + index * 0.01 for index in range(260)])

        result = evaluate_regime_v1_1(spy, bil, engine=RecordingEngine())

        self.assertEqual(len(result.scenarios), 16)
        self.assertEqual(
            {scenario.transaction_cost_bps for scenario in result.scenarios},
            {0.0, 2.0, 5.0, 10.0},
        )
        self.assertEqual(
            {scenario.strategy for scenario in result.scenarios},
            set(EvaluationStrategy),
        )
        for scenario in result.scenarios:
            self.assertEqual(
                tuple((point.signal_date, point.return_end_date) for point in scenario.points),
                result.common_intervals,
            )

    def test_repeated_evaluation_is_deterministic(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(260)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)

        first = evaluate_regime_v1_1(spy, bil, engine=RecordingEngine())
        second = evaluate_regime_v1_1(spy, bil, engine=RecordingEngine())

        self.assertEqual(first, second)

    def test_cost_sensitivity_changes_values_not_dates_or_exposure(self) -> None:
        dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(260)]
        spy = make_symbol_bars("SPY", dates)
        bil = make_symbol_bars("BIL", dates)
        result = evaluate_regime_v1_1(spy, bil, engine=RecordingEngine())
        buy_hold = [
            scenario for scenario in result.scenarios
            if scenario.strategy is EvaluationStrategy.SPY_BUY_AND_HOLD
        ]

        self.assertEqual(
            len({tuple((p.signal_date, p.return_end_date) for p in row.points) for row in buy_hold}),
            1,
        )
        self.assertEqual(
            len({tuple(p.target_spy_exposure for p in row.points) for row in buy_hold}),
            1,
        )
        self.assertGreater(buy_hold[0].metrics.final_value, buy_hold[-1].metrics.final_value)
```

Extend the first integration test with exact window-count and boundary assertions:

```python
        self.assertEqual(
            len(result.windows),
            16 * len(HISTORICAL_REGIME_WINDOWS),
        )
        for window_name in HISTORICAL_REGIME_WINDOWS:
            rows = [row for row in result.windows if row.window_name == window_name]
            self.assertEqual(len(rows), 16)
            self.assertEqual(
                len({
                    (row.effective_signal_date, row.effective_return_end_date)
                    for row in rows
                }),
                1,
            )
```

- [ ] **Step 2: Run integration tests and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation.RegimeEvaluationV11IntegrationTests -v
```

Expected: `evaluate_regime_v1_1` is not defined.

- [ ] **Step 3: Implement the public orchestration function**

```python
def evaluate_regime_v1_1(
    spy_bars: Sequence[PriceBar],
    bil_bars: Sequence[PriceBar],
    *,
    qqq_bars: Sequence[PriceBar] | None = None,
    engine: MarketRegimeEngine | None = None,
    initial_capital: float = 100_000.0,
    evaluation_start: date | None = None,
    evaluation_end: date | None = None,
) -> RegimeEvaluationV11Result:
```

The public function must not accept arbitrary strategy parameters, exposure mappings, SMA windows, or cost rates. It must:

1. align SPY/BIL once;
2. derive all four exposure tuples once;
3. loop in `EvaluationStrategy` declaration order and fixed `EVALUATION_TRANSACTION_COST_BPS` order;
4. call `_simulate_intervals` and `_performance_metrics` with applicable buckets:
   - buy-and-hold `(1.0,)`;
   - trend `(0.0, 1.0)`;
   - both regime variants `(0.0, 0.3, 0.7, 1.0)`;
5. build every fixed historical-window row from each continuous scenario;
6. assert all point boundary pairs equal `common_intervals`; and
7. return tuples in deterministic order.

Export the function and public models from both `regime_evaluation.py` and `backtest/__init__.py`.

- [ ] **Step 4: Add a source-safety regression**

In `tests/test_regime_evaluation.py`, import `inspect`, read only the evaluator
source path, and add:

```python
class RegimeEvaluationV11SourceSafetyTests(unittest.TestCase):
    def test_v11_source_has_no_ui_provider_broker_order_or_env_dependency(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "src" / "private_quant" / "backtest" / "regime_evaluation.py"
        ).read_text(encoding="utf-8")

        for forbidden in (
            "streamlit",
            "private_quant.broker",
            "ibapi",
            "placeOrder",
            "dotenv",
            ".env",
            "build_market_data_provider",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

        self.assertEqual(
            tuple(inspect.signature(evaluate_regime_v1_1).parameters),
            (
                "spy_bars",
                "bil_bars",
                "qqq_bars",
                "engine",
                "initial_capital",
                "evaluation_start",
                "evaluation_end",
            ),
        )
```

- [ ] **Step 5: Run the complete regime evaluation and source-safety tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation tests.test_market_regime tests.test_package_imports -v
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the public evaluator**

```powershell
git add -- src/private_quant/backtest/regime_evaluation.py src/private_quant/backtest/__init__.py tests/test_regime_evaluation.py
git commit -m "feat: add regime evaluation v1.1 comparison"
```

---

### Task 9: Document methodology and roadmap status

**Files:**
- Modify: `docs/MARKET_REGIME_V1.md`
- Modify: `docs/ROADMAP.md`
- Test: `tests/test_regime_evaluation.py`

**Interfaces:**
- Consumes: implemented public contracts and approved formulas.
- Produces: durable user-facing methodology that does not imply BIL execution, risk-free substitution, optimization, or trading integration.

- [ ] **Step 1: Add a failing documentation-contract test**

```python
class RegimeEvaluationV11DocumentationTests(unittest.TestCase):
    def test_v11_methodology_documents_required_safety_assumptions(self) -> None:
        root = Path(__file__).resolve().parents[1]
        methodology = (root / "docs" / "MARKET_REGIME_V1.md").read_text(encoding="utf-8")

        for required in (
            "Evaluation V1.1",
            "BIL-return residual cash proxy",
            "not a claim that the strategy trades BIL",
            "signal_date",
            "return_end_date",
            "zero daily hurdle",
            "0, 2, 5, and 10 basis points",
            "does not fully isolate the causal effect of the exposure mapping",
        ):
            with self.subTest(required=required):
                self.assertIn(required, methodology)
```

- [ ] **Step 2: Run the documentation test and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation.RegimeEvaluationV11DocumentationTests -v
```

Expected: required V1.1 wording is absent.

- [ ] **Step 3: Add the Evaluation V1.1 methodology section**

Update `docs/MARKET_REGIME_V1.md` with:

- the four exact strategies;
- one common SPY/BIL interval sequence and BIL common-start truncation;
- the six-step D0-before-cost through D1-ending-value timeline;
- BIL as a residual-cash return proxy, not a traded security or risk-free series;
- SPY exposure-change cost formula and no extra BIL leg;
- fixed 0/2/5/10 bps sensitivity scenarios;
- exact CAGR, drawdown, population volatility, zero-hurdle Sharpe/Sortino, Calmar, turnover, change-count, average-exposure, and bucket formulas;
- continuous/rebased fixed-window semantics;
- the four predeclared diagnostic contrasts; and
- the limitation that required comparisons measure participation drag but do not causally isolate mapping from signal timing.

Add a `Market Regime Evaluation V1.1` roadmap subsection with implemented checkboxes for deterministic comparison/tests and unchecked checkboxes for authorized live Tiingo history validation. State that scoring and trading behavior did not change.

- [ ] **Step 4: Run documentation and regime tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation tests.test_market_regime -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit documentation**

```powershell
git add -- docs/MARKET_REGIME_V1.md docs/ROADMAP.md tests/test_regime_evaluation.py
git commit -m "docs: document regime evaluation v1.1"
```

---

### Task 10: Run final regression and authorized Tiingo validation

**Files:**
- Verify only; no planned source changes.

**Interfaces:**
- Consumes: complete V1.1 implementation and local project environment.
- Produces: clean automated verification evidence plus a separately
  authorized, sanitized current provider-coverage validation.

- [ ] **Step 1: Run the complete deterministic evaluation tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation tests.test_market_regime -v
```

Expected: all point-in-time, no-look-ahead, alignment, cost, metric, window, and unchanged-engine tests pass.

- [ ] **Step 2: Run the complete repository test suite**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: all repository tests pass without network access, `.env` access, TWS, or order calls.

- [ ] **Step 3: Run static and dependency checks**

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pip check
git diff --check
git status --short --branch
```

Expected: compilation succeeds, dependencies are consistent, no whitespace errors exist, and only intended branch changes are present.

- [ ] **Step 4: Review safety-sensitive diffs**

```powershell
git diff origin/main...HEAD -- src/private_quant/risk/market_regime.py
git diff origin/main...HEAD -- src/private_quant/broker src/private_quant/app/paper_trading.py
git diff origin/main...HEAD -- .env .env.example
```

Expected: no changes to the Market Regime V1 engine, broker/order/paper-trading code, or `.env` files. An empty diff is the required result for each command.

- [ ] **Step 5: Obtain explicit authorization before the manual Tiingo check**

Do not run the next command until the repository owner explicitly authorizes reading the local `.env` and calling Tiingo for this validation. If authorization is absent, record the manual step as not run; do not substitute fabricated or cached results.

- [ ] **Step 6: After authorization, run one sanitized Tiingo coverage validation through today**

Run from the repository root in PowerShell. This command loads local
configuration but never prints it or the API key. It fetches all three series
through the manual `run_date`, evaluates through the latest common complete
interval, and reports no strategy-performance metrics:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
@'
from datetime import date

from private_quant.app.config import build_market_data_provider, load_app_configuration
from private_quant.backtest import evaluate_regime_v1_1

start = date(2006, 1, 1)
run_date = date.today()
try:
    configuration = load_app_configuration()
    provider = build_market_data_provider(configuration)
    spy = tuple(provider.get_price_history("SPY", start, run_date))
    bil = tuple(provider.get_price_history("BIL", start, run_date))
    qqq = tuple(provider.get_price_history("QQQ", start, run_date))
except Exception:
    raise SystemExit(
        "Manual validation failed before source coverage could be established."
    ) from None


def print_source_coverage(symbol, bars):
    if not bars:
        raise SystemExit(f"{symbol} source coverage is unavailable.")
    try:
        dates = tuple(bar.trading_date for bar in bars)
    except Exception:
        raise SystemExit(
            f"{symbol} source coverage could not be summarized safely."
        ) from None
    print(
        f"{symbol} source coverage: "
        f"first={min(dates)} last={max(dates)} rows={len(bars)}"
    )


print_source_coverage("SPY", spy)
print_source_coverage("BIL", bil)
print_source_coverage("QQQ", qqq)

try:
    result = evaluate_regime_v1_1(
        spy,
        bil,
        qqq_bars=qqq,
        evaluation_start=date(2007, 10, 1),
        evaluation_end=run_date,
    )
except Exception:
    raise SystemExit("Manual V1.1 evaluation failed safely.") from None

if not result.common_intervals:
    raise SystemExit("Evaluation produced no common complete intervals.")

first_common = result.common_intervals[0]
final_common = result.common_intervals[-1]
final_return_end_date = final_common[1]
age_days = (run_date - final_return_end_date).days
if age_days < 0:
    freshness = "INVALID_FUTURE_DATE"
elif age_days <= 4:
    freshness = "CURRENT"
else:
    freshness = "STALE"

print(f"First common interval: {first_common}")
print(f"Final common interval: {final_common}")
print(f"Common interval count: {len(result.common_intervals)}")
print(
    "Evaluation coverage freshness: "
    f"status={freshness} run_date={run_date} "
    f"final_return_end_date={final_return_end_date} "
    f"age_calendar_days={age_days} allowed_age_calendar_days=4"
)

if freshness != "CURRENT":
    raise SystemExit(
        "Manual validation failed: final common return_end_date is not reasonably current."
    )
'@ | .\.venv\Scripts\python.exe -
```

Expected safeguards:

- SPY, BIL, and QQQ coverage each reports only first trading date, last
  trading date, and row count;
- evaluation coverage reports only first common interval, final common
  interval, common interval count, run date, final return-end date, calendar
  age, four-day allowance, and explicit freshness status;
- no configuration object, account data, headers, token, `.env` content, or raw provider payload is printed;
- provider/configuration/evaluation exceptions are replaced by fixed sanitized
  failure messages and are never printed or interpolated;
- `CURRENT` requires `0 <= age_calendar_days <= 4`, matching the existing
  Market Regime current-data allowance for weekends and long holiday
  weekends;
- `STALE` or `INVALID_FUTURE_DATE` is printed explicitly and fails the manual
  validation instead of claiming freshness;
- the fixed windows remain exactly 2007-10-01 through 2009-06-30, calendar
  2020, calendar 2022, and 2023-01-01 through 2025-12-31; fetching through
  `date.today()` does not extend or redefine those windows; and
- any missing/duplicate/invalid active BIL observation causes a sanitized failure instead of filling data.

- [ ] **Step 7: Record validation evidence without committing data or secrets**

Summarize source coverage dates/counts, common interval coverage, freshness
status, and pass/fail in the PR description or review notes. Do not record
strategy-performance metrics from this coverage-only command. Do not commit
downloaded price history, console output containing environment details,
`.env`, or credentials.

---

## Final Review Checklist

- [ ] The implementation changes no code in `src/private_quant/risk/market_regime.py`.
- [ ] Score thresholds, confidence logic, and `1.0 / 0.7 / 0.3 / 0.0` mapping are unchanged.
- [ ] Every interval explicitly stores `signal_date` and `return_end_date`.
- [ ] D0 initial value, D0 cost, D0->D1 return, and D1 ending value are verified by tests.
- [ ] All four strategies and all four cost rates share identical intervals.
- [ ] BIL is used only for residual-cash return in one strategy.
- [ ] No BIL cost leg, data fill, parameter optimization, or Streamlit UI exists.
- [ ] Future valid-dated malformed SPY/BIL observations cannot affect earlier bounded results.
- [ ] Active-period BIL gaps and invalid values fail safely.
- [ ] Metrics, turnover, exposure buckets, and historical windows match deterministic fixtures.
- [ ] Automated tests use no `.env`, provider, broker, TWS, or order dependency.
- [ ] Full repository tests and verification commands pass.
- [ ] Manual Tiingo validation runs only after explicit authorization, fetches
  through `date.today()`, reports source/common-interval coverage and explicit
  freshness, and prints no secret or strategy-performance metric.
