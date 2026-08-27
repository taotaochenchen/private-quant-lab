# Market Regime Engine v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, point-in-time-safe Market Regime Engine that explains the current market state, confidence, and maximum long exposure, supports historical validation, and renders in a standalone Streamlit research page without connecting to broker execution.

**Architecture:** Reuse the existing `MarketDataProvider` and `PriceBar` contracts. Put immutable models, validation, indicators, scoring, confidence, and risk mapping in `private_quant.risk`; put forward-looking evaluation outputs and comparison curves in `private_quant.backtest`; keep provider construction, caching, safe errors, and rendering in the Streamlit app layer.

**Tech Stack:** Python 3.11+, standard-library dataclasses/enums/statistics/math, existing Tiingo EOD adapter, Streamlit 1.48+, and `unittest`/Streamlit `AppTest`.

## Global Constraints

- Start from merged PR #12 commit `3f081b3` on branch `codex/market-regime-engine-v1` in the isolated `.worktrees/codex-market-regime-engine-v1` checkout.
- Do not read, print, modify, or commit the real `.env`, API keys, credentials, or account identifiers.
- Do not connect to TWS or IB Gateway and do not call any broker order method.
- Do not submit, preview, stage, cancel, replace, or transmit a PAPER or LIVE order.
- Do not enable or alter `IBKR_PAPER_SUBMIT_ENABLED`; PR #12 broker safety behavior remains unchanged.
- Use only `BULL`, `CAUTIOUS_BULL`, `RISK_OFF`, and `BEAR` regime states.
- Use adjusted daily closes and only observations whose `trading_date <= as_of`.
- Require at least 252 valid SPY trading sessions and fail explicitly on stale, invalid, duplicated, or insufficient mandatory data.
- Use QQQ only as optional confidence confirmation; QQQ never contributes score points or changes the regime.
- Defer VIX scoring and breadth to later work; do not add a second market-data provider or HTTP stack.
- Keep the calculation engine framework-independent and free of Streamlit and broker imports.
- Forward returns are evaluation outputs only and must never enter the classifier.
- `BEAR` maps to zero maximum long exposure and never authorizes automatic shorting.
- The Streamlit page makes no provider call until the user selects **Evaluate regime**.
- Automated and browser tests use mocks or deterministic fixtures and make no real Tiingo or TWS request.
- Do not merge the PR.

---

### Task 1: Add immutable regime contracts and mandatory history validation

**Files:**
- Create: `src/private_quant/risk/market_regime.py`
- Modify: `src/private_quant/risk/__init__.py`
- Create: `tests/test_market_regime.py`
- Modify: `tests/test_package_imports.py`

**Interfaces:**
- Produces: `MarketRegime`, `RegimeConfidence`, `StrategyPermission`, and `ConfirmationStatus` string enums.
- Produces: frozen/slotted `RegimeMetric`, `RegimeComponent`, `RegimeConfidenceEvidence`, `RegimeDataQuality`, and `RegimeResult`.
- Produces: typed `RegimeEngineError`, `InsufficientRegimeHistoryError`, `InvalidRegimeDataError`, and `StaleRegimeDataError`.
- Produces: `_validated_history(bars: Sequence[PriceBar], *, symbol: str, as_of: date, minimum_observations: int, enforce_staleness: bool) -> tuple[PriceBar, ...]`.
- Preserves: existing `PriceBar` and provider contracts.

- [ ] **Step 1: Write failing contract and validation tests**

Add deterministic helpers that create real `PriceBar` objects without vendor data:

```python
def make_bars(
    symbol: str = "SPY",
    *,
    count: int = 252,
    end: date = date(2026, 8, 26),
    start_price: float = 100.0,
    daily_return: float = 0.001,
) -> tuple[PriceBar, ...]:
    trading_days: list[date] = []
    day = end
    while len(trading_days) < count:
        if day.weekday() < 5:
            trading_days.append(day)
        day -= timedelta(days=1)
    trading_days.reverse()

    bars: list[PriceBar] = []
    price = start_price
    for trading_day in trading_days:
        price *= 1.0 + daily_return
        bars.append(
            PriceBar(
                symbol=symbol,
                trading_date=trading_day,
                open=price,
                high=price,
                low=price,
                close=price,
                adjusted_close=price,
                volume=1_000_000,
            )
        )
    return tuple(bars)
```

Test that:

- each result model rejects an invalid score, exposure, data-age, or component
  weight in `__post_init__`;
- frozen models raise `FrozenInstanceError` on mutation;
- 251 SPY observations raise `InsufficientRegimeHistoryError`;
- an empty sequence raises the same fixed-message error;
- a non-SPY mandatory symbol, duplicate date, adjusted close of NaN, infinity,
  zero, or a negative number raises `InvalidRegimeDataError`;
- a gap greater than ten calendar days inside the trailing 252 observations
  raises `InvalidRegimeDataError`;
- observations after `as_of` are filtered before validation;
- latest data more than four calendar days before `as_of` raises
  `StaleRegimeDataError`; and
- fixed exception messages do not contain the invalid numeric value or raw
  object representation.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
$env:PYTHONUTF8='1'
..\..\.venv\Scripts\python.exe -m unittest tests.test_market_regime tests.test_package_imports -v
```

Expected: imports fail because `private_quant.risk.market_regime` does not
exist.

- [ ] **Step 3: Implement exact contracts and validation**

Define the enums with `StrEnum` and exact values:

```python
class MarketRegime(StrEnum):
    BULL = "BULL"
    CAUTIOUS_BULL = "CAUTIOUS_BULL"
    RISK_OFF = "RISK_OFF"
    BEAR = "BEAR"


class RegimeConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class StrategyPermission(StrEnum):
    NORMAL = "NORMAL"
    REDUCED = "REDUCED"
    DEFENSIVE = "DEFENSIVE"
    BLOCKED = "BLOCKED"


class ConfirmationStatus(StrEnum):
    CONFIRMS_POSITIVE = "CONFIRMS_POSITIVE"
    CONFIRMS_NEGATIVE = "CONFIRMS_NEGATIVE"
    MIXED = "MIXED"
    UNAVAILABLE = "UNAVAILABLE"
```

Define immutable models with these exact fields:

```python
@dataclass(frozen=True, slots=True)
class RegimeMetric:
    name: str
    value: float
    unit: str
    reference: str


@dataclass(frozen=True, slots=True)
class RegimeComponent:
    name: str
    score: int
    max_abs_score: int
    metrics: tuple[RegimeMetric, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class RegimeConfidenceEvidence:
    boundary_distance: int
    agreeing_components: int
    qqq_status: ConfirmationStatus


@dataclass(frozen=True, slots=True)
class RegimeDataQuality:
    requested_date: date
    latest_spy_date: date
    data_age_days: int
    observations_used: int
    required_observations: int
    is_valid: bool
    qqq_status: ConfirmationStatus
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegimeResult:
    evaluation_date: date
    regime: MarketRegime
    score: int
    confidence: RegimeConfidence
    confidence_evidence: RegimeConfidenceEvidence
    maximum_long_exposure: float
    strategy_permission: StrategyPermission
    components: tuple[RegimeComponent, ...]
    reasons: tuple[str, ...]
    data_quality: RegimeDataQuality
```

Validate bounded numeric fields, nonempty names/explanations, and finite
metric values. Implement `_validated_history` in this order: filter dates,
normalize/check symbol, sort, reject duplicates, reject invalid adjusted
closes, check the trailing-window gaps, check observation count, then check
latest-date staleness. Use only fixed exception messages.

Export the public types from `risk/__init__.py`. Do not export
`MarketRegimeEngine` until Task 2 defines the class. Add
`private_quant.risk.market_regime` to the package-import test now.

- [ ] **Step 4: Run validation tests and verify GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add -- src/private_quant/risk/market_regime.py src/private_quant/risk/__init__.py tests/test_market_regime.py tests/test_package_imports.py
git commit -m "feat: add market regime contracts and validation"
```

---

### Task 2: Implement deterministic components, classification, confidence, and explanations

**Files:**
- Modify: `src/private_quant/risk/market_regime.py`
- Modify: `src/private_quant/risk/__init__.py`
- Modify: `tests/test_market_regime.py`

**Interfaces:**
- Consumes: Task 1 contracts and `_validated_history`.
- Produces: `score_drawdown(drawdown: float) -> int`.
- Produces: `score_realized_volatility(volatility: float) -> int`.
- Produces: `regime_from_score(score: int) -> MarketRegime`.
- Produces: `risk_mapping_for(regime: MarketRegime) -> tuple[float, StrategyPermission]`.
- Produces: `MarketRegimeEngine.evaluate(spy_bars: Sequence[PriceBar], *, as_of: date, qqq_bars: Sequence[PriceBar] | None = None) -> RegimeResult`.

- [ ] **Step 1: Write failing pure threshold tests**

Use literal assertions for every inclusive boundary:

```python
def test_regime_score_boundaries(self) -> None:
    self.assertIs(regime_from_score(45), MarketRegime.BULL)
    self.assertIs(regime_from_score(44), MarketRegime.CAUTIOUS_BULL)
    self.assertIs(regime_from_score(15), MarketRegime.CAUTIOUS_BULL)
    self.assertIs(regime_from_score(14), MarketRegime.RISK_OFF)
    self.assertIs(regime_from_score(-20), MarketRegime.RISK_OFF)
    self.assertIs(regime_from_score(-21), MarketRegime.BEAR)
```

Assert drawdown scores at `-0.05`, immediately below `-0.05`, `-0.10`,
immediately below `-0.10`, `-0.15`, `-0.20`, and below `-0.20`. Assert
volatility scores at `0.15`, immediately above `0.15`, `0.20`, `0.30`,
`0.40`, and above `0.40`. Reject non-finite inputs.

Assert risk mappings exactly:

```python
expected = {
    MarketRegime.BULL: (1.0, StrategyPermission.NORMAL),
    MarketRegime.CAUTIOUS_BULL: (0.7, StrategyPermission.REDUCED),
    MarketRegime.RISK_OFF: (0.3, StrategyPermission.DEFENSIVE),
    MarketRegime.BEAR: (0.0, StrategyPermission.BLOCKED),
}
```

- [ ] **Step 2: Write failing end-to-end engine tests**

Build deterministic real histories for:

- steadily rising, low-volatility prices producing `BULL`;
- positive long trend with weakened tail momentum/drawdown producing
  `CAUTIOUS_BULL`;
- mixed/negative trend evidence and material stress producing `RISK_OFF`;
- persistent decline and drawdown producing `BEAR`.

For each result assert:

- exact regime, score range, exposure, and permission;
- component names are exactly `Primary trend`, `Momentum`, `Drawdown`, and
  `Realized volatility`;
- component scores sum to `result.score`;
- every component contains raw metrics and a nonempty explanation;
- repeated evaluation returns an equal immutable result.

Add a future-leak regression:

```python
baseline = engine.evaluate(history, as_of=cutoff)
with_future = engine.evaluate(
    history + make_crash_bars_after(cutoff),
    as_of=cutoff,
)
self.assertEqual(with_future, baseline)
```

Add equality tests using constant adjusted closes: trend comparisons,
momentum, and SMA200 slope contribute zero rather than positive or negative
points.

- [ ] **Step 3: Write failing QQQ and confidence tests**

Assert:

- valid positive QQQ can produce `HIGH` only when boundary distance is at
  least 10 and at least three components agree;
- missing or insufficient QQQ yields `UNAVAILABLE`, adds a fixed warning,
  leaves score/regime unchanged, and caps confidence at `MEDIUM`;
- contradictory QQQ yields `LOW` without changing score/regime;
- mixed QQQ cannot produce `HIGH`;
- exact total score zero gives agreement count zero and `LOW`; and
- confidence evidence exposes the exact boundary distance and agreement
  count.

- [ ] **Step 4: Run Task 2 tests and verify RED**

Run:

```powershell
$env:PYTHONUTF8='1'
..\..\.venv\Scripts\python.exe -m unittest tests.test_market_regime -v
```

Expected: missing scoring and engine symbols fail.

- [ ] **Step 5: Implement indicators and component scoring**

Use standard-library functions and exact formulas:

```python
def _mean(values: Sequence[float]) -> float:
    return fmean(values)


def _return_over(prices: Sequence[float], sessions: int) -> float:
    return prices[-1] / prices[-1 - sessions] - 1.0


def _realized_volatility(prices: Sequence[float]) -> float:
    returns = tuple(
        prices[index] / prices[index - 1] - 1.0
        for index in range(len(prices) - 20, len(prices))
    )
    return pstdev(returns) * sqrt(252.0)
```

Calculate current SMA50/SMA200 and the SMA200 ending 20 observations earlier.
Score comparisons with a helper returning positive points, negative points,
or zero on equality. Implement the exact design tables:

- trend weights: `8`, `12`, `12`, `8`;
- momentum weights: `8`, `12`;
- drawdown tiers: `25`, `10`, `-5`, `-15`, `-25`;
- volatility tiers: `15`, `8`, `0`, `-8`, `-15`.

Implement `regime_from_score` with inclusive thresholds `45`, `15`, and
`-20`; reject scores outside `[-100, 100]` and `bool` values.

- [ ] **Step 6: Implement optional QQQ confirmation and confidence**

Validate QQQ with `minimum_observations=201` and the same `as_of`, but catch
only the three typed regime-data exceptions and map them to `UNAVAILABLE`.
QQQ never changes component or total scores.

Calculate:

```python
boundary_distance = min(abs(score - boundary) for boundary in (-20, 15, 45))
if score > 0:
    agreeing = sum(component.score > 0 for component in components)
elif score < 0:
    agreeing = sum(component.score < 0 for component in components)
else:
    agreeing = 0
```

Apply exact confidence rules from the design. Positive QQQ agrees with the two
bull regimes; negative QQQ agrees with the two defensive regimes. Mixed and
unavailable are neutral for `MEDIUM` but cannot satisfy `HIGH`.

- [ ] **Step 7: Assemble `RegimeResult` and fixed explanations**

Use the latest SPY session as `evaluation_date`. Populate data quality with
the requested date, latest date, age, 252 observations used, QQQ status, and
fixed warnings. Reasons are concise component conclusions plus QQQ status;
they never claim certainty or include provider payloads.

Export the engine and public models/functions from `risk/__init__.py`.

- [ ] **Step 8: Run Task 1 and Task 2 tests**

```powershell
$env:PYTHONUTF8='1'
..\..\.venv\Scripts\python.exe -m unittest tests.test_market_regime tests.test_data_contracts tests.test_package_imports -v
```

Expected: all pass.

- [ ] **Step 9: Commit Task 2**

```powershell
git add -- src/private_quant/risk/market_regime.py src/private_quant/risk/__init__.py tests/test_market_regime.py
git commit -m "feat: classify deterministic market regimes"
```

---

### Task 3: Add point-in-time historical regime evaluation

**Files:**
- Create: `src/private_quant/backtest/regime_evaluation.py`
- Modify: `src/private_quant/backtest/__init__.py`
- Create: `tests/test_regime_evaluation.py`

**Interfaces:**
- Consumes: `MarketRegimeEngine`, `MarketRegime`, `RegimeResult`, and `PriceBar`.
- Produces: frozen/slotted `RegimeObservation`, `RegimeBucketStats`, `RegimeEquityPoint`, `RegimeComparison`, and `RegimeEvaluationResult`.
- Produces: `evaluate_regime_history(spy_bars: Sequence[PriceBar], *, qqq_bars: Sequence[PriceBar] | None = None, engine: MarketRegimeEngine | None = None, initial_capital: float = 100_000.0, transaction_cost_bps: float = 5.0) -> RegimeEvaluationResult`.
- Produces: `HISTORICAL_REGIME_WINDOWS`, an immutable mapping of crisis/recovery labels to date pairs.

- [ ] **Step 1: Write failing point-in-time and output-model tests**

Define exact models:

```python
@dataclass(frozen=True, slots=True)
class RegimeObservation:
    trading_date: date
    result: RegimeResult
    spy_adjusted_close: float
    forward_return_20: float | None
    forward_return_60: float | None


@dataclass(frozen=True, slots=True)
class RegimeBucketStats:
    regime: MarketRegime
    sessions: int
    percent_sessions: float
    mean_forward_return_20: float | None
    mean_forward_return_60: float | None
    episode_count: int
    mean_duration: float
    median_duration: float
    max_duration: int
    worst_episode_drawdown: float


@dataclass(frozen=True, slots=True)
class RegimeEquityPoint:
    trading_date: date
    value: float


@dataclass(frozen=True, slots=True)
class RegimeComparison:
    initial_capital: float
    final_value: float
    max_drawdown: float
    transaction_cost: float
    equity_curve: tuple[RegimeEquityPoint, ...]


@dataclass(frozen=True, slots=True)
class RegimeEvaluationResult:
    observations: tuple[RegimeObservation, ...]
    bucket_stats: tuple[RegimeBucketStats, ...]
    transition_count: int
    annualized_transitions: float
    whipsaw_count: int
    whipsaw_rate: float
    buy_and_hold: RegimeComparison
    regime_capped: RegimeComparison
```

Use a recording fake engine whose `evaluate` method asserts every input bar is
`<= as_of`. Assert the evaluator calls it once for each eligible SPY day,
beginning with index 251, and that arbitrary future bars do not alter an
earlier `RegimeObservation.result`.

- [ ] **Step 2: Write failing evaluation-metric tests**

With a deterministic fake engine returning a known regime sequence, assert:

- session counts and percentages sum to all observations and `100%`;
- incomplete 20/60-session tail horizons remain `None` and are excluded from
  means;
- episodes are contiguous runs;
- an `A -> B -> A` pattern where B lasts at most ten sessions counts one
  whipsaw;
- transitions per year equal `transition_count / observations * 252`;
- worst episode drawdown uses only prices inside that episode; and
- all four regimes appear in `bucket_stats`, including zero-session regimes.

- [ ] **Step 3: Write failing comparison-curve tests**

Use a fake engine sequence with exposures `1.0`, `0.3`, and `0.0`. Assert:

- the result calculated on `T` affects the return from `T` to the next trading
  session, never the return ending on `T`;
- initial exposure change from cash incurs cost;
- later cost occurs only when exposure changes;
- zero-yield cash receives no return;
- buy-and-hold and regime-capped curves begin with the same initial capital
  and date; and
- max drawdown is calculated independently for both curves.

- [ ] **Step 4: Run evaluator tests and verify RED**

```powershell
$env:PYTHONUTF8='1'
..\..\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation -v
```

Expected: import failure for the new evaluator module.

- [ ] **Step 5: Implement point-in-time observations and statistics**

Sort SPY bars, reject duplicate dates through the engine, and evaluate each
eligible date. Compute forward returns only after all classifications exist:

```python
forward_20 = (
    prices[index + 20] / prices[index] - 1.0
    if index + 20 < len(prices)
    else None
)
```

Use the same rule for 60 sessions. Build episodes from adjacent equal regimes.
Define a whipsaw as an interior episode lasting ten sessions or fewer whose
previous and next episode regimes are identical.

- [ ] **Step 6: Implement comparison curves**

Begin on the first eligible evaluation date. For each next trading session:

1. take the prior observation's maximum exposure;
2. charge `abs(new_exposure - old_exposure) * portfolio_value * cost_rate`;
3. apply the next SPY adjusted-close return to the invested fraction; and
4. leave the cash fraction unchanged.

Buy-and-hold applies the full next-session return without transaction cost.
Reject non-positive initial capital, negative costs, and bool numeric values.

Define fixed windows:

```python
HISTORICAL_REGIME_WINDOWS = MappingProxyType(
    {
        "2008 financial crisis": (date(2007, 10, 1), date(2009, 6, 30)),
        "2020 COVID crash and recovery": (date(2020, 1, 1), date(2020, 12, 31)),
        "2022 bear market": (date(2022, 1, 1), date(2022, 12, 31)),
        "2023-2025 recovery and bull period": (date(2023, 1, 1), date(2025, 12, 31)),
    }
)
```

- [ ] **Step 7: Run evaluator and engine tests**

```powershell
$env:PYTHONUTF8='1'
..\..\.venv\Scripts\python.exe -m unittest tests.test_regime_evaluation tests.test_market_regime tests.test_etf_momentum -v
```

Expected: all pass without network access.

- [ ] **Step 8: Commit Task 3**

```powershell
git add -- src/private_quant/backtest/regime_evaluation.py src/private_quant/backtest/__init__.py tests/test_regime_evaluation.py
git commit -m "feat: evaluate market regimes historically"
```

---

### Task 4: Add the safe Streamlit Market Regime dashboard

**Files:**
- Create: `src/private_quant/app/market_regime.py`
- Create: `tests/test_market_regime_app.py`

**Interfaces:**
- Consumes: existing `load_app_configuration()` and `build_market_data_provider()`.
- Consumes: `MarketRegimeEngine.evaluate()` and immutable result models.
- Produces: `load_regime_histories(as_of: date) -> tuple[tuple[PriceBar, ...], tuple[PriceBar, ...]]`, cached only in the app layer.
- Produces: `evaluate_current_regime(as_of: date, *, history_loader: Callable[[date], tuple[tuple[PriceBar, ...], tuple[PriceBar, ...]]] = load_regime_histories) -> RegimeResult`.
- Produces: `regime_error_message(error: Exception) -> str` and pure row-formatting helpers.

- [ ] **Step 1: Read the installed Streamlit session-state, dashboard, and data-display references**

Run the installed Streamlit skill discovery with `PYTHONUTF8=1`, then read its
`references/session-state.md`, `references/dashboards.md`, and
`references/data-display.md`. Follow installed-version APIs and do not add
deprecated `use_container_width`.

- [ ] **Step 2: Write failing app-loader tests**

Test through injected fakes that:

- the loader requests both SPY and QQQ from `as_of - 550 days` through
  `as_of` using one existing provider abstraction;
- SPY provider failure propagates to safe UI error mapping;
- a QQQ provider failure becomes an empty optional history and does not
  suppress a valid SPY result;
- the engine receives the exact requested date; and
- no provider/configuration loader runs merely by importing the module.

Use `load_regime_histories.clear()` around cache tests and patch provider
construction; never load the real configuration.

- [ ] **Step 3: Write failing Streamlit rendering tests**

Use `AppTest.from_string` with a literal real `RegimeResult`. Assert the page
shows:

- `Market Regime` title and research/not-investment-advice warning;
- regime, signed score, confidence, maximum exposure, and strategy permission
  metrics;
- one evidence row per component with raw values, score, and explanation;
- reasons and data-quality fields;
- QQQ unavailable warning when applicable; and
- no button, link, or text containing `BUY`, `SELL`, `Submit order`, or live
  trading controls.

Use `AppTest.from_file` to assert the initial page has one
`Evaluate regime` button, no provider result, and no exception. Inject a fake
loader before clicking in a separate test; restore every module monkeypatch in
`finally`.

- [ ] **Step 4: Run app tests and verify RED**

```powershell
$env:PYTHONUTF8='1'
..\..\.venv\Scripts\python.exe -m unittest tests.test_market_regime_app -v
```

Expected: import failure for the new page.

- [ ] **Step 5: Implement cached provider loading and safe errors**

Decorate only the raw app loader:

```python
@st.cache_data(ttl="15m", max_entries=8, show_spinner=False)
def load_regime_histories(
    as_of: date,
) -> tuple[tuple[PriceBar, ...], tuple[PriceBar, ...]]:
    configuration = load_app_configuration()
    provider = build_market_data_provider(configuration)
    start = as_of - timedelta(days=550)
    spy = tuple(provider.get_price_history("SPY", start, as_of))
    try:
        qqq = tuple(provider.get_price_history("QQQ", start, as_of))
    except (TiingoError, ValueError):
        qqq = ()
    return spy, qqq
```

Map configuration, authentication, rate-limit, transport, missing-data,
invalid-data, insufficient-history, and stale-data exceptions to fixed safe
messages. Never interpolate `str(error)`.

- [ ] **Step 6: Implement initial-safe dashboard rendering**

Render title, purpose, method caption, and **Evaluate regime** before any slow
call. Only call `evaluate_current_regime(date.today())` inside the button
branch. Use native `st.container(horizontal=True)` metrics and a dataframe or
bordered containers for component evidence. Include exact copy:

```text
Research guidance only — this deterministic regime estimate is not investment advice or certainty, and it cannot place orders.
```

Format exposures as whole percentages, scores with a sign, and ratios/returns
as percentages. The page must not import `private_quant.broker`.

- [ ] **Step 7: Run dashboard and safety tests**

```powershell
$env:PYTHONUTF8='1'
..\..\.venv\Scripts\python.exe -m unittest tests.test_market_regime_app tests.test_market_regime tests.test_broker_config tests.test_paper_trading_app -v
```

Expected: all pass with no network/TWS activity.

- [ ] **Step 8: Commit Task 4**

```powershell
git add -- src/private_quant/app/market_regime.py tests/test_market_regime_app.py
git commit -m "feat: add market regime dashboard"
```

---

### Task 5: Document methodology, verify the full branch, and prepare the PR

**Files:**
- Create: `docs/MARKET_REGIME_V1.md`
- Modify: `README.md`
- Modify: `docs/DATA_SOURCES.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/superpowers/specs/2026-08-27-market-regime-engine-v1-design.md` only if implementation reveals a factual mismatch
- Modify: `docs/superpowers/plans/2026-08-27-market-regime-engine-v1.md` only if implementation reveals a factual mismatch

**Interfaces:**
- Documents: score tables, confidence rules, exposure mapping, data semantics, point-in-time protections, historical windows, limitations, and local launch commands.
- Produces: reviewed PR targeting `main`, without merging it.

- [ ] **Step 1: Write focused methodology documentation**

`docs/MARKET_REGIME_V1.md` must include:

- all component weights and inclusive boundaries;
- regime thresholds and exposure/permission mapping;
- adjusted-close and U.S. session-date semantics;
- minimum 252-session history and four-calendar-day freshness rule;
- optional QQQ behavior;
- explicit VIX and breadth deferrals;
- confidence calculation;
- point-in-time filtering and next-session evaluation semantics;
- 2008, 2020, 2022, and 2023-2025 analysis windows;
- forward returns as evaluation-only outputs;
- historical evaluator metrics and regime-capped comparison assumptions;
- limitations, including no actual vendor-history run during automated work
  because `.env` and secrets are off-limits; and
- no auto-trading, auto-sizing, liquidation, or shorting.

- [ ] **Step 2: Update user-facing repository documentation**

Add Windows PowerShell launch instructions to `README.md`:

```powershell
python -m streamlit run src/private_quant/app/market_regime.py
```

State that opening the page makes no request and **Evaluate regime** uses the
existing configured EOD provider. Preserve the guarded `.env` copy instruction
and do not add or change secrets.

Update `docs/DATA_SOURCES.md` with adjusted-close, date, freshness, missing
data, optional QQQ, and VIX/breadth limitations. Update `docs/ROADMAP.md` with
the implemented engine/evaluator/dashboard items while leaving live historical
execution unchecked because no secret-backed Tiingo run occurred.

- [ ] **Step 3: Add a source-safety regression**

In the most relevant existing source-safety test or
`tests/test_market_regime_app.py`, parse the risk, evaluator, and app modules
with `ast` and assert:

- risk/evaluator do not import `streamlit` or `private_quant.broker`;
- no regime file accesses `.env` directly except through the existing app
  configuration loader;
- no attribute call names are `placeOrder`, `submit_order`, `preview_order`,
  `cancelOrder`, or `reqIds`; and
- `IBKR_PAPER_SUBMIT_ENABLED` is absent from every new regime source file.

- [ ] **Step 4: Run the complete fresh verification**

```powershell
$env:PYTHONUTF8='1'
..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v
..\..\.venv\Scripts\python.exe -m compileall -q src tests
..\..\.venv\Scripts\python.exe -m pip check
git diff --check origin/main..HEAD
git status --short
```

Expected: zero test failures, successful compilation, no broken requirements,
clean branch-range whitespace check, and only intended tracked files.

- [ ] **Step 5: Browser-test the initial page without data access**

Start on an unused local port:

```powershell
..\..\.venv\Scripts\python.exe -m streamlit run src/private_quant/app/market_regime.py --server.headless true --server.port 8514 --browser.gatherUsageStats false
```

Verify in a real browser:

- page title and research-only warning render;
- **Evaluate regime** is visible;
- no result is loaded initially;
- no BUY, SELL, broker, or order control is present;
- browser console has no errors; and
- no button is clicked.

Stop the server and confirm port 8514 is no longer listening. This browser
test must not read `.env` or contact Tiingo/TWS.

- [ ] **Step 6: Commit documentation and verification changes**

```powershell
git add -- README.md docs/DATA_SOURCES.md docs/ROADMAP.md docs/MARKET_REGIME_V1.md tests/test_market_regime_app.py docs/superpowers/specs/2026-08-27-market-regime-engine-v1-design.md docs/superpowers/plans/2026-08-27-market-regime-engine-v1.md
git commit -m "docs: explain market regime engine v1"
```

- [ ] **Step 7: Request whole-branch code review and address findings**

Review `origin/main..HEAD` for methodology accuracy, inclusive boundaries,
point-in-time safety, future-return separation, optional-data handling,
framework/provider boundaries, broker isolation, test quality, and
documentation consistency. Fix every Critical or Important finding, run the
covering tests, and perform one scoped re-review.

- [ ] **Step 8: Rerun the full suite on the final committed tree**

Repeat Step 4 after every review fix. Do not rely on an earlier run.

- [ ] **Step 9: Push and create the PR**

```powershell
git push -u origin codex/market-regime-engine-v1
gh pr create --base main --head codex/market-regime-engine-v1
```

The PR description must state:

- exact regime methodology and score thresholds;
- confidence calculation;
- Tiingo through the existing provider abstraction and adjusted-close use;
- look-ahead protections and next-session comparison semantics;
- historical evaluation windows and whether real vendor data was run;
- VIX, breadth, and data-freshness limitations;
- all test/compile/dependency/browser results;
- current regime/score/confidence/exposure if fresh data was available without
  violating secret boundaries, otherwise an explicit unavailable statement;
- no `.env`, TWS, Tiingo, or broker/order connection occurred during automated
  verification; and
- no auto-trading, auto-sizing, shorting, liquidation, or PR #12 safety change.

Stop with the PR open and unmerged. Preserve the worktree for review feedback.
