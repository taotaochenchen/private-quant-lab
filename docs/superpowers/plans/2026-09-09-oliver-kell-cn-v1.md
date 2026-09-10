# Oliver Kell CN V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, point-in-time-safe A-share Cycle of Price Action research backtest inside `private-quant-lab` without changing existing strategy behavior.

**Architecture:** Add focused data contracts and research helpers for point-in-time fundamentals, universe state, and CPA signals; compose them in a strategy module; simulate China-market execution in a separate backtest module. Keep real data providers replaceable and validate behavior first on deterministic synthetic fixtures.

**Tech Stack:** Python 3.11+, standard library (`dataclasses`, `datetime`, `math`, `statistics`, `unittest`), existing project package structure. No new runtime dependency for V1.

**Spec:** `docs/superpowers/specs/2026-09-09-oliver-kell-cn-v1-design.md`

## Global Constraints

- Research only; no broker or live-trading integration.
- Long-only, no leverage, maximum 10 positions.
- Fundamentals are usable only when `available_from <= decision_date`.
- V1 default fundamental thresholds: revenue YoY >= 30%, net-profit YoY >= 30%, ROE >= 8%, EPS > 0, float market cap RMB 5B-50B inclusive.
- Model A-share T+1, 100-share board lots, costs, suspension, and blocked limit fills.
- Development window is 2015-01-01 to 2021-12-31; out-of-sample starts 2022-01-01 and must not be used for tuning.
- Do not add Qlib or `cn-trader` as runtime dependencies.

---

### Task 1: Point-in-time fundamental contract and filter

**Files:**
- Create: `src/private_quant/research/oliver_kell/__init__.py`
- Create: `src/private_quant/research/oliver_kell/fundamentals.py`
- Create: `tests/test_oliver_kell_filters.py`

**Interfaces:**
- Produces: `FundamentalRecord`, `FundamentalThresholds`, `latest_available_record(records, decision_date)`, `passes_fundamental_screen(record, thresholds)`, `is_fundamentally_eligible(records, decision_date, thresholds)`.

- [ ] **Step 1: Write failing tests** proving records are invisible before `available_from`, thresholds are inclusive where specified, and a future restatement cannot alter an earlier decision.
- [ ] **Step 2: Run** `python -m unittest tests.test_oliver_kell_filters -v` and confirm failure because the module is missing.
- [ ] **Step 3: Implement minimal immutable dataclasses and selection/filter functions.** Selection must sort only records satisfying `available_from <= decision_date`, preferring the greatest `(available_from, report_period)`.
- [ ] **Step 4: Re-run the focused test** and require PASS.
- [ ] **Step 5: Commit** with `feat: add point-in-time CPA fundamental filter`.

### Task 2: Universe and A-share tradability state

**Files:**
- Create: `src/private_quant/research/oliver_kell/universe.py`
- Extend: `tests/test_oliver_kell_filters.py`

**Interfaces:**
- Produces: `SecurityState`, `UniverseRules`, `is_universe_eligible(state, decision_date, rules)`.

- [ ] **Step 1: Add failing tests** for ST/*ST exclusion, suspension exclusion, IPO seasoning, minimum liquidity, and decision-date state.
- [ ] **Step 2: Run focused tests** and confirm the new symbols fail.
- [ ] **Step 3: Implement immutable security-state and universe-rule dataclasses plus deterministic eligibility function.**
- [ ] **Step 4: Run focused tests** and require PASS.
- [ ] **Step 5: Commit** with `feat: add A-share CPA universe guards`.

### Task 3: CPA indicator and signal engine

**Files:**
- Create: `src/private_quant/research/oliver_kell/price_action.py`
- Create: `tests/test_oliver_kell_signals.py`

**Interfaces:**
- Produces: `DailyBar`, `CpaSignal`, `ema(values, period)`, `sma(values, period)`, `relative_strength(close, benchmark_close)`, `detect_wedge_pop(...)`, `detect_ema_crossback(...)`, `detect_base_n_break(...)`.

- [ ] **Step 1: Write failing tests** with hand-constructed bar sequences whose expected EMA/SMA and signal dates are known exactly. Tests must assert no signal can depend on bars after the signal date.
- [ ] **Step 2: Run** `python -m unittest tests.test_oliver_kell_signals -v` and confirm failure.
- [ ] **Step 3: Implement simple list-based indicators** returning `None` until enough observations exist. Implement deterministic, parameterized signal predicates using only current/prior bars, volume confirmation, and relative-strength confirmation.
- [ ] **Step 4: Re-run focused tests** and require PASS.
- [ ] **Step 5: Commit** with `feat: add deterministic CPA signal engine`.

### Task 4: Strategy composition and frozen V1 config

**Files:**
- Create: `src/private_quant/strategies/oliver_kell_cpa.py`
- Create: `configs/oliver_kell_cn_v1.json`
- Create: `tests/test_oliver_kell_strategy.py`

**Interfaces:**
- Produces: `OliverKellCnConfig`, `evaluate_symbol(...) -> list[CpaSignal]` and `load_default_config(path)`.
- Consumes: Task 1-3 research contracts.

- [ ] **Step 1: Write failing tests** proving default variant B requires both universe/fundamental eligibility and a technical signal; technical-only mode bypasses the fundamental filter; market-regime integration is absent.
- [ ] **Step 2: Run focused test** and confirm failure.
- [ ] **Step 3: Implement config parsing and strategy composition** with default thresholds, 10/20 EMA, 50/200 SMA, maximum 10 positions, Base n' Break disabled by default, and explicit development/OOS date boundaries.
- [ ] **Step 4: Run focused tests** and require PASS.
- [ ] **Step 5: Commit** with `feat: compose Oliver Kell CN V1 strategy`.

### Task 5: A-share execution simulator

**Files:**
- Create: `src/private_quant/backtest/oliver_kell_cpa.py`
- Create: `tests/test_oliver_kell_backtest.py`

**Interfaces:**
- Produces: `ExecutionRules`, `OrderIntent`, `Fill`, `Position`, `PortfolioSnapshot`, `simulate_order(...)`, `run_cpa_backtest(...)`.
- Consumes: `CpaSignal` and strategy config from Tasks 3-4.

- [ ] **Step 1: Write failing tests** for 100-share lot rounding, insufficient cash, T+1 same-day sell rejection, suspended execution rejection, limit-up buy rejection, limit-down sell rejection, commission, sell-side stamp duty, and slippage.
- [ ] **Step 2: Run focused test** and confirm failure.
- [ ] **Step 3: Implement minimal deterministic fill logic and portfolio accounting.** Never synthesize a fill when the day's market state marks that side unavailable.
- [ ] **Step 4: Run focused tests** and require PASS.
- [ ] **Step 5: Commit** with `feat: add A-share CPA execution simulator`.

### Task 6: Metrics and synthetic end-to-end backtest

**Files:**
- Extend: `src/private_quant/backtest/oliver_kell_cpa.py`
- Extend: `tests/test_oliver_kell_backtest.py`

**Interfaces:**
- Produces: `BacktestMetrics` with total return, CAGR, max drawdown, Sharpe, Calmar, win rate, profit factor, average winner/loser, trades/year, turnover, benchmark return, and excess return.

- [ ] **Step 1: Add failing deterministic metric tests** using a small equity curve and known trade ledger.
- [ ] **Step 2: Add a failing end-to-end synthetic test** from point-in-time fundamentals + daily bars -> eligibility -> signal -> fills -> exit -> metrics, including a deliberately future-dated fundamental revision that must not affect earlier results.
- [ ] **Step 3: Implement metrics and the smallest orchestration needed** to satisfy the fixture.
- [ ] **Step 4: Run** `python -m unittest tests.test_oliver_kell_backtest -v` and require PASS.
- [ ] **Step 5: Commit** with `feat: add CPA backtest metrics and synthetic E2E`.

### Task 7: Documentation and full regression verification

**Files:**
- Create: `docs/OLIVER_KELL_CN_V1.md`
- Modify: `README.md`

**Interfaces:**
- Documents frozen V1 assumptions, limitations, point-in-time requirements, how to run focused tests, and why competition returns are not a target.

- [ ] **Step 1: Document the research hypothesis, config, bias controls, and commands.** State clearly that real A-share provider ingestion is not yet part of V1 unless a compliant point-in-time provider is configured later.
- [ ] **Step 2: Run all new tests** with `python -m unittest tests.test_oliver_kell_filters tests.test_oliver_kell_signals tests.test_oliver_kell_strategy tests.test_oliver_kell_backtest -v`.
- [ ] **Step 3: Run full regression suite** with `python -m unittest discover -s tests -v`.
- [ ] **Step 4: Review diff** for accidental market-regime, ETF momentum, broker, credential, or generated-data changes.
- [ ] **Step 5: Commit** with `docs: document Oliver Kell CN V1 experiment`.
- [ ] **Step 6: Open a PR** from `codex/oliver-kell-cn-v1` to `main` summarizing implemented safeguards and test evidence.