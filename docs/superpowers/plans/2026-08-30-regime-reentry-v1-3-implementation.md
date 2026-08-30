# Market Regime V1.3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved three-structure recovery-episode experiment without executing manual market-data stages.

**Architecture:** One focused V1.3 module owns the overlay, diagnostics, and research orchestration. Reuse existing provider-independent V1.1/V1.2 helpers unchanged; isolate state, frozen protocol, and release integration as three reviewable deliverables.

**Tech Stack:** Python 3.11+, stdlib dataclasses/enums/unittest, existing evaluation layer. No new dependencies.

## Global Constraints

- Base SHA `6a2f400b09b9b6051727ebe9c67a96339fc830c5`; isolated branch `codex/regime-reentry-v1-3`.
- Binding design: `docs/superpowers/specs/2026-08-30-regime-reentry-v1-3-design.md`; read it before implementing your assigned task.
- Freeze MarketRegimeEngine, score construction, thresholds, regimes, confidence, QQQ behavior, and mapping BULL=1.0, CAUTIOUS_BULL=0.7, RISK_OFF=0.3, BEAR=0.0.
- The overlay consumes only V1 regime, raw score, maximum_long_exposure, and its own prior state. No QQQ input or additional market features enter V1.3.
- No broker, IBKR, TWS, order, UI, configuration, provider, or environment-file changes. No network or environment access in tests or research orchestration.
- Do not read .env, contact Tiingo, run manual stages, inspect real 2021+ prices, or merge. Synthetic post-2020 fixtures are permitted and required.
- Exactly DEEP_RECOVERY, DEFENSIVE_RECOVERY, BROAD_BULL_CATCH_UP. No additional parameters or candidates.
- Shared V1.2 helpers remain unchanged. Existing tests remain unchanged, including historical V1.2 release-state guards.
- Preserve signal_date -> return_end_date and BIL residual-cash proxy semantics; no extra transaction leg.
- All implementation steps are RED -> GREEN -> review -> commit. Report actual commands and expected failure reasons.
- Run from the new worktree with `$env:PYTHONPATH='src'` so its source takes precedence over the shared existing virtual environment's editable path. Use `.\.venv\Scripts\python.exe`; local ignored .venv junction points to the existing project interpreter.
- User explicitly requires release-state text assertions and AST coupling/export guards; retain these requested safety tests in addition to behavior tests.

## File responsibilities

- Create `src/private_quant/backtest/regime_reentry_v1_3.py`: immutable contracts, private state/diagnostics, public orchestration.
- Create `tests/test_regime_reentry_v1_3.py`: deterministic synthetic fixtures and V1.3 regression groups.
- Modify `src/private_quant/backtest/__init__.py`: narrow explicit public exports only.
- Modify `docs/MARKET_REGIME_V1.md` and `docs/ROADMAP.md`: methodology and implementation/manual-stage separation.
- No other implementation files change. Spec and plan are separate documentation commits before code.

### Task 1: Fixed candidates, recovery transitions, and diagnostics

**Files:** Create module and test file listed above. No exports or other files yet.

**Interfaces:**
- Consume `_V1Signal` and `_stabilization_diagnostics` from unchanged regime_stabilization.
- Produce `V13ReentryStructure`, `V13ReentryCandidate`, `FIXED_V13_CANDIDATES`, `_validate_candidate(candidate)` (raise ValueError on invalid), `_run_reentry_state_machine(signals, candidate)` -> tuple of private signal points, `_recovery_diagnostics(state_points, *, start, end)` -> `V13RecoveryDiagnostics`.
- Signal points expose `signal_date`, `v1_score`, `v1_regime`, `v1_maximum_long_exposure`, `prior_overlay_exposure`, `overlay_exposure`, `transition`, and enough immutable prior/result episode state to reconstruct closing-session minimum. Diagnostics expose `schedule_exposure_changes`, `whipsaw_pairs`, `whipsaw_rate`, `total_recovery_episodes`, `completed_recovery_episodes`, `incomplete_recovery_episodes`, `fast_path_activation_count`, `fast_path_activation_rate`, `ordinary_one_level_reentry_count`, `fast_two_level_reentry_count`, `delayed_below_cap_sessions`, `reentry_lags`, `recovery_durations`, means/medians, and immutable episode records.

- [ ] Write `ReentryContractTests`, `ReentryTransitionTests`, `RecoveryDiagnosticsTests` with hand-derived fixtures. Test exactly three immutable structures; rejection of strings, wrong enums, subclass/mutated/spoof candidates. Cover every transition and trigger condition, initial warm-up, persistent origin, minimum cap, closing and clearing, no same-day recovery after de-risk, finite input and date ordering. Example expected schedule:

```python
signals = tuple(_V1Signal(date(2020, 1, i + 1), score, regime, cap)
                for i, (score, regime, cap) in enumerate([
                    (45, MarketRegime.BULL, 1.0),
                    (45, MarketRegime.BULL, 1.0),
                    (45, MarketRegime.BULL, 1.0),
                    (-30, MarketRegime.BEAR, 0.0),
                    (45, MarketRegime.BULL, 1.0),
                    (45, MarketRegime.BULL, 1.0)]))
points = module._run_reentry_state_machine(signals, deep)
self.assertEqual(tuple(p.overlay_exposure for p in points),
                 (0.3, 0.7, 1.0, 0.0, 0.7, 1.0))
```

- [ ] Run `.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_regime_reentry_v1_3.py -v`; record RED (missing module/contracts, then missing behavior).
- [ ] Implement frozen/slotted contracts and the strict ordered state machine. No arbitrary grid construction. `_validate_candidate` checks exact class and exact enum type on every external candidate entry. Use enum identity, not overloaded equality, for depth choices. Reject bool/nonfinite/unrecognized scalar inputs. Follow all six transition steps from spec.

```python
if cap < prior_overlay:
    overlay = cap
    # Preserve active origin; otherwise open at prior_overlay.
elif cap > prior_overlay:
    step = 2 if fast_eligible else 1
    overlay = levels[min(levels.index(prior_overlay) + step, levels.index(cap))]
else:
    overlay = prior_overlay
```

- [ ] Diagnostics tests: literal whipsaw schedule `(1.0, 0.3, 0.7, 1.0, 0.3, 1.0)` has 5 changes and 2 nonoverlapping pairs; compare unchanged V1.2 helper too. Test episode carry-in, multiple de-risks, closed/incomplete episodes, end cutoff preventing future minimum/closure contamination, one-level fast completion vs two-level jumps, no-episode None rate, inclusive per-boundary lags and lost-permission reset. Ordinary warm-up rises do not invent episodes.
- [ ] Implement diagnostics by reusing unchanged V1.2 whipsaw/count helper with re-entry detail disabled, then derive V1.3 episode and boundary-lag details from context only through end. Count transitions only in measured range; episode overlap and lag definitions must match spec.
- [ ] Run focused tests GREEN, self-review all transition branches, run full suite once, commit `feat: add recovery-episode re-entry state machine`. Submit task review; repair Critical/Important findings before Task 2.

### Task 2: Frozen selection, locked evaluation, and descriptive orchestration

**Files:** Modify only new V1.3 module/test file.

**Interfaces:**
- Consume Task 1 contracts/functions above. Reuse `_align_evaluation_history`, `_build_v1_signals`, `_baseline_state_points`, `_measured_state_points`, `_simulate_bil_cash_schedule`, `_simulate_locked_bil_cash_schedule`, `_prelocked_target`, `_slice_period_points`, `_rebased_period_metrics`, `_performance_metrics`, `_qualify_candidate`, `_locked_promotion_decision`, `GateStatus`, `ResearchPeriod`, and frozen period/cost constants without modifying helpers.
- Produce immutable V13SelectionStatus (V1_3_CANDIDATE_SELECTED / NO_QUALIFIED_V1_3_CANDIDATE), V13PromotionStatus (PROMOTE_V1_3_RESEARCH / NO_V1_3_PROMOTION), V13CandidateSelectionResult, V13LockedEvaluationResult, V13PostSelectionResult and nested period/qualification/path/cost/window records.
- Public signatures: `select_regime_reentry_v1_3_candidate(spy_bars, bil_bars, *, engine=None, initial_capital=100_000.0)`; `evaluate_locked_regime_reentry_v1_3(spy_bars, bil_bars, *, frozen_candidate, engine=None, initial_capital=100_000.0)`; `build_regime_reentry_v1_3_post_selection_diagnostics(spy_bars, bil_bars, *, frozen_candidate, engine=None, initial_capital=100_000.0)`.

- [ ] Add `SelectionProtocolTests`, `LockedProtocolTests`, `ReentryOrchestrationTests`, `PostSelectionTests`. Literal period metrics isolate seven gates: baseline CAGR .10, turnover 1.0, whipsaws 10; candidate combined .1001, turnover .85, whipsaws 8 and split CAGR .095 must pass when drawdowns -.20. Equality Combined .10 fails; .850001 turnover fails; 9 whipsaws fails; split .094999 fails; -.200001 drawdown fails. None/zero/nonpositive denominators produce NOT_EVALUABLE. Locked candidate .1025 against .10 is exact pass; .102499 fails.

```python
result = module.select_regime_reentry_v1_3_candidate(spy, bil, engine=engine)
self.assertEqual(len(result.candidates), 3)
self.assertIsNone(result.winner)  # constant-cap fixture has zero baseline whipsaws
self.assertIs(result.status, module.V13SelectionStatus.NO_QUALIFIED_V1_3_CANDIDATE)
self.assertEqual(result.common_intervals[-1][1], date(2020, 12, 31))
```

- [ ] Run focused suite RED before orchestration implementation. Use sparse explicit synthetic dates plus 260 pre-start synthetic warm-up rows as existing tests do; no external fixtures. Inject only classifier stub needed to prescribe caps; also include a real MarketRegimeEngine synthetic integration case.
- [ ] Add immutable result contracts. Selection aligns once at exact Development start/Selection end, builds chronological V1 signals once (QQQ absent), reconstructs each candidate from first eligible signal, and simulates one continuous path. Split summaries use complete intervals, matching measured signal endpoints for diagnostics. Reuse `_qualify_candidate` numerical gates, copying its gates/qualified into V1.3 qualification records rather than returning misleading V1.2 candidate annotations.
- [ ] Implement ranking: top return tie group uses `cagr >= top_cagr - .0005`; key `(whipsaws, -max_drawdown, turnover, conservative_index)`. Test each precedence by holding earlier keys equal, candidates outside tie band, shuffled inputs, all tied, and no qualifier.
- [ ] Add cutoff/continuity tests before implementation: append valid-dated 2021+ objects whose adjusted_close property raises; selection unchanged and no property read. Unparseable dates fail before engine calls. Active missing/duplicate/nonpositive SPY/BIL fail. Check exact date alignment and no QQQ passed. Test warm-up gradual ramp; episode carried across 2015 and 2021 (origin/minimum preserved), no same-session returns, opening and carried locked cost against hand calculations. A future valid-dated malformed content test may use SimpleNamespace or a property-raising fixture but never real price data.
- [ ] Implement locked wrapper that validates exactly one fixed candidate before processing input, reconstructs prelocked state, verifies first eligible locked boundary, reuses carried exposure accounting, maps four gates to V1.3 promotion status. No selection invocation in locked or descriptive functions.
- [ ] Implement descriptive 0/2/5/10 bps full-path and fixed windows for one validated candidate. Use explicit unavailable windows, normalized 100 metrics, actual carried cost, diagnostic end=last included signal, never terminal return date. Test all four costs, all four windows, missing window, and terminal signal exclusion. Public output must expose performance/turnover/cost/exposure metrics and Task 1 diagnostics.
- [ ] Run GREEN focused and full suite, self-review cutoff before content/classifier, exact seven/four gate reuse and ranking; commit `feat: add frozen v1.3 research orchestration`. Submit task review and resolve Critical/Important issues before Task 3.

### Task 3: Narrow exports, documentation, and release/source guards

**Files:** Modify new test file, `src/private_quant/backtest/__init__.py`, `docs/MARKET_REGIME_V1.md`, `docs/ROADMAP.md` only.

**Interfaces:** Export precisely the nine V13 public candidate/result/status/diagnostics names in the spec and three public functions. Do not export FIXED_V13_CANDIDATES, private state/transition helpers, or nested records at package level. Existing exports stay intact.

- [ ] Add `ReentryPublicExportTests`, `ReentrySourceSafetyTests`, `ReentryReleaseStateTests` and run focused suite RED. Assert required public imports work and no private re-entry helpers enter package `__all__`. AST-test the new module and reused signal builder for no provider/config/env/broker/order/UI/network calls or QQQ input; allow only literal `qqq_bars=None` in reused V1.2 builder. Check input signatures exclude QQQ and data fetching.

```python
self.assertIn('select_regime_reentry_v1_3_candidate', backtest.__all__)
self.assertNotIn('_run_reentry_state_machine', backtest.__all__)
self.assertIn('- [ ] V1.3 Manual Stage 1', roadmap)
self.assertIn('- [ ] V1.3 Manual Stage 2', roadmap)
```

- [ ] Extend explicit imports/`__all__`; no dynamic exports.
- [ ] Document exact three structures, normal/fast transition limits, episode origin/minimum lifecycle, unchanged V1/gates, BIL accounting and timing, diagnostics definitions, and manual stages not run. Retain historical V1.2 closure text/headings required by existing guard; add infrastructure progress beneath the existing V1.3 future-research heading and clarify empirical research remains future. Use `- [ ] V1.3 Manual Stage 1` / `- [ ] V1.3 Manual Stage 2` to distinguish V1.3 from completed V1.2. State no empirical winner, promotion, or real 2021+ V1.3 result.
- [ ] Run focused and existing documentation/release guards GREEN; run full suite once; commit `docs: expose v1.3 research contracts and manual gates`. Submit task review.

## Final verification and stop

- [ ] Independent whole-branch review against spec and all user requirements; repair Critical/Important issues with failing regression first, then scoped re-review. No unrelated refactor.
- [ ] Run in isolated worktree:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_regime_reentry_v1_3.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pip check
git diff --check
git diff --check 6a2f400b09b9b6051727ebe9c67a96339fc830c5...HEAD
git diff --name-only 6a2f400b09b9b6051727ebe9c67a96339fc830c5...HEAD
git diff --exit-code 6a2f400b09b9b6051727ebe9c67a96339fc830c5...HEAD -- src/private_quant/risk src/private_quant/broker src/private_quant/app src/private_quant/data .env .env.example pyproject.toml
git status --short
git status --branch --short
```

- [ ] Confirm complete diff allowlist and no provider/config execution changes, secrets, downloaded data, or console dumps. Verify main unchanged locally and branch ancestry equals approved base.
- [ ] Push `codex/regime-reentry-v1-3`, optionally create main PR clearly stating: "V1.3 implementation only. Manual Stage 1 has not been run." Do not merge.
- [ ] Return requested 20-item report with actual SHAs, paths, counts, review findings/repairs, and explicit no-manual-run confirmations. STOP; future manual stages require separate authorization.

Self-review: tasks cover state/diagnostics, every frozen protocol gate, point-in-time boundaries, orchestration and release/safety tests. No placeholders, no protocol changes, no extra comparator or dependencies, no manual-data script execution. All task interfaces are defined above or in unchanged named helpers.
