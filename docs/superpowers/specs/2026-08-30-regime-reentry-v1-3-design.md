# Market Regime V1.3 — Recovery-Episode Re-entry Structure Study

Date: 2026-08-30. Status: approved architectural research contract; implementation only.
Base: `6a2f400b09b9b6051727ebe9c67a96339fc830c5`.
Branch: `codex/regime-reentry-v1-3`, isolated worktree.

## Objective and scope

Test whether episode-gated limited fast re-entry preserves participation while
retaining immediate V1 de-risking and the frozen V1.2 success gates. V1.2's
failed selection remains closed; it is not the qualification baseline. V1.3
is not a classifier, strategy optimizer, execution system, or promotion claim.
Manual Stage 1 and Stage 2 have NOT run for V1.3.

Freeze MarketRegimeEngine, score construction, thresholds, regimes, confidence,
QQQ behavior, and mapping BULL=1.0, CAUTIOUS_BULL=0.7, RISK_OFF=0.3, BEAR=0.0.
The overlay consumes only V1 regime, raw score, maximum_long_exposure, and its
own prior state. No QQQ input or additional market features enter V1.3.
No broker, IBKR, TWS, order, UI, configuration, provider, or environment-file
changes. No network or environment access in tests or research orchestration.

## Architecture and reuse

Add `src/private_quant/backtest/regime_reentry_v1_3.py` and
`tests/test_regime_reentry_v1_3.py`. Define explicit new-module exports only for
the public V1.3 result/candidate contracts and three orchestration functions.
Preserve the existing package export set, which is a tested V1.2 contract.
Keep state-machine helpers private. Update only MARKET_REGIME_V1.md and
ROADMAP.md for research status, plus this spec and its implementation plan.

Reuse stable provider-independent helpers from regime_evaluation and
regime_stabilization for alignment, V1 signal construction with QQQ absent,
BIL cash accounting, period metrics, whipsaw counting, qualification gates,
and locked carry-in accounting. Do not extract or change V1.2 helpers.
Wrap generic qualification outputs in V1.3 result contracts. Implement V1.3
ranking separately because its structural tie-break includes turnover.
No optional V1.2 comparator is needed: it adds no qualification information.

Alternatives considered: extending V1.2 would mix distinct protocols;
duplicating its accounting would risk drift. A focused module with existing
helper reuse preserves the frozen methodology with the smallest change.

## Fixed contracts

`V13ReentryStructure` has exactly three enum members in conservative order:
DEEP_RECOVERY, DEFENSIVE_RECOVERY, BROAD_BULL_CATCH_UP.
`V13ReentryCandidate` is a frozen, slotted dataclass containing only a structure.
Reject arbitrary strings, other enums, subclasses, mutated structures, and
equality-spoof objects at orchestration boundaries. Construct a canonical
fixed tuple of exactly three candidates. No score/session/margin parameter.

Internal immutable recovery state contains active, origin_exposure, and
minimum_v1_cap; inactive means both optional fields are None. Initial overlay
is 0.0 with inactive episode. Each private signal point records signal_date,
V1 inputs, prior and resulting overlay, prior and resulting episode state,
and transition HOLD / DE_RISK / NORMAL_RE_ENTRY / FAST_RE_ENTRY. Preserve the
episode minimum reached on a closing session in the diagnostic record even
though persisted episode state clears after closing.

Public contracts: V13RecoveryDiagnostics, V13SelectionStatus,
V13CandidateSelectionResult, V13PromotionStatus, V13LockedEvaluationResult,
V13PostSelectionResult; nested immutable period/qualification/episode/path/
cost/window records are defined in the module but are not in its public exports.
All returned collections are tuples, not mutable lists or maps.

## Session transition (strict order)

1. Read prior overlay and episode; update an active episode's minimum cap.
2. If cap < prior overlay: immediately set overlay=cap, classify DE_RISK,
   open an episode if inactive (origin=prior overlay, minimum=cap); otherwise
   preserve the original origin. Never re-enter on that same session.
3. Otherwise, if cap > prior overlay, evaluate the fast trigger: active
   episode AND regime is BULL AND finite raw score >=45 AND cap==1.0 AND
   structure depth condition. DEEP requires minimum==0.0; DEFENSIVE requires
   minimum<=0.3; BROAD permits any active episode.
4. Eligible fast action advances at most two allowed levels: 0->0.7,
   0.3->1.0, 0.7->1.0. Otherwise advance exactly one: 0->0.3->0.7->1.0.
   Cap the action at V1 permission; cap==prior overlay means HOLD.
5. If overlay >= episode origin after the action, close and clear the episode.
6. Persist state. Always require overlay in (0.0,0.3,0.7,1.0) and overlay<=cap.

45 is the frozen V1 BULL boundary, not a tunable threshold. Validate finite
score, recognized regime, allowed non-boolean cap, and increasing signal dates
at the private signal boundary. Testing inconsistent but individually valid
regime/score/cap combinations proves every conjunct of the fast trigger.
Initial ramp-up from zero never earns episode privileges.

## Point-in-time, warm-up, and accounting

Date all source rows before classification. Unparseable dates fail safely
because temporal placement is impossible. Selection filters at 2020-12-31
before reading price content: later valid-dated malformed prices cannot affect
selection. Active SPY/BIL dates and adjusted closes follow existing strict
alignment rules: no guessing, fill, duplicates, nonfinite or nonpositive data.
Use the same common SPY/BIL intervals for baseline and all candidates.

Process every eligible SPY V1 signal (252-session warm-up) before the first
measured interval, starting overlay at zero; no warm-up portfolio returns.
One continuous state and portfolio path spans Development and Validation;
never reset on 2015-01-01. Reconstruct pre-2021 state for locked evaluation;
never reset overlay or episode on 2021-01-01. Locked opening cost is only the
change from the immediately preceding target, not a fictional fresh entry.

At D0 initial/starting capital exists before cost. Data through D0 yields the
signal and target; charge SPY exposure-change cost at D0; apply that target to
the D0->D1 return; ending value is dated D1. Public points retain explicit
signal_date and return_end_date. No same-session return attribution.

BIL adjusted-close return is only a residual-cash return proxy. No BIL trades,
commission leg, execution claim, or risk-free-series substitution. Primary cost
is 5 bps of absolute SPY exposure change. Reuse net compounding, CAGR, drawdown,
volatility, zero-hurdle Sharpe/Sortino, Calmar, value-weighted annualized turnover,
transaction-cost totals, average exposure, and bucket percentages from V1.1.
Initial capital defaults to 100,000; period/window metrics normalize start to
100 by scaling the continuous path, preserving actual carried boundary costs.

Development is 2007-10-01..2014-12-31; Validation 2015-01-01..2020-12-31;
Combined is 2007-10-01..2020-12-31. Slice complete intervals with signal>=start
and return_end<=end. A cross-split interval stays in Combined and the continuous
portfolio, but neither split summary. Locked starts with the first eligible
signal on/after 2021-01-01 and ends at the latest common complete interval.
Selection requires both exact outer boundaries and usable complete intervals
in each split. Locked history must cover its first eligible boundary.

## Frozen selection and promotion

Compare each candidate only with matching V1+BIL+5bps. All seven must pass:

1. Development max drawdown >= -0.20.
2. Validation max drawdown >= -0.20.
3. Combined CAGR strictly > baseline Combined CAGR.
4. Development CAGR >= baseline Development CAGR - 0.005.
5. Validation CAGR >= baseline Validation CAGR - 0.005.
6. Combined annualized turnover <= baseline * 0.85.
7. Combined whipsaw pairs <= baseline * 0.80.

Undefined or nonpositive reduction denominators are NOT_EVALUABLE and cannot
qualify. Among qualifiers take the maximum Combined CAGR; candidates within
0.0005 of that maximum form the top tie group. Order that group by lower
whipsaws, better max drawdown, lower annualized turnover, then conservative
structure order. Remaining qualifiers sort by descending CAGR then the same
tie-break keys. Freeze at most one. Outcomes are V1_3_CANDIDATE_SELECTED or
NO_QUALIFIED_V1_3_CANDIDATE with winner=None. No winner means Stage 2 unavailable.

Locked evaluation accepts exactly one validated fixed candidate, not a sequence
or a selection search. Human review/freezing and separate authorization are
external gates, not inferable from a dataclass. No function fetches data.
All four locked gates must pass: max drawdown>=-0.20, CAGR>=baseline+0.0025,
turnover<=baseline*0.85, whipsaws<=baseline*0.80. Undefined/nonpositive reduction
denominators are NOT_EVALUABLE. Outcomes PROMOTE_V1_3_RESEARCH or
NO_V1_3_PROMOTION. No retuning, reselection, or winner replacement from 2021+.

## Diagnostics with deterministic definitions

Use only the measured signal dates (last signal, not terminal return date).
Reuse V1.2 schedule-change and nonoverlapping whipsaw counting exactly: do not
count the first in-period target; an opposite-direction change returning to
or crossing the pre-opening target within five subsequent signal sessions is
a pair. Rate=pairs/schedule changes, None if denominator zero.

Episode records contain opening signal date, origin exposure, minimum cap as
of diagnostic end, optional closing date, and full recovery duration (closing
signal index minus opening signal index). Include episodes overlapping the
diagnostic range, including carried-in episodes. Completed means closed by
range end; incomplete means still open at that end; total=completed+incomplete.
Never inspect later state to complete or deepen an earlier episode.

Fast activation count counts actual FAST_RE_ENTRY transitions in measured
signals, including eligible 0.7->1.0. Rate=activations/overlapping episodes
(None if zero); it is a ratio, may exceed one, and is not a percent probability.
Fast two-level count counts only actual two-level jumps; ordinary one-level
count counts only NORMAL_RE_ENTRY, not fast one-level completion.
Report sessions overlay<cap. For each upward boundary 0.3/0.7/1.0, re-entry lag
starts on the first consecutive signal with cap>=boundary and prior overlay
below it; records inclusive session count when crossed, resetting if permission
is lost. A two-level jump can record two boundary lags. Warm-up establishes
lag context, but record crossings only inside the requested diagnostic range.
Report tuple lags/durations and mean/median or None for empty samples.
Baseline retains existing V1.2 comparable schedule/whipsaw diagnostics;
episode/fast-path diagnostics describe only V1.3, not fabricated baseline state.

Post-selection function describes only one frozen structure, with 0/2/5/10bps
full-path comparisons and the existing 2007-10-01..2009-06-30, calendar 2020,
calendar 2022, 2023-01-01..2025-12-31 windows. Window metrics use normalized
100 start; absent windows are explicitly unavailable. No diagnostic selects,
qualifies, ranks, or promotes. Synthetic support does not authorize real runs.

## Manual gates and release state

Stage 1 requires future separate authorization: SPY warm-up plus SPY/BIL only
through 2020-12-31, no QQQ, exactly three candidates, frozen gates and ranking.
Stage 2 requires a reviewed frozen winner plus second explicit authorization.
This task performs neither. No credentials, raw market data, console dumps,
real 2021+ observations, provider connection, or trading integration.
ROADMAP distinguishes completed infrastructure from unchecked V1.3 manual
stages; the V1.2 closure wording and guards remain valid historical statements.

## Verification and self-review

TDD covers all three fixed structures; constructor/frozen-boundary attacks;
every transition/trigger conjunct; episode opening, deepening, closing and
origin persistence; warm-up, split/locked continuity; signal lag and costs;
future-content exclusion, invalid dates before classifier, no QQQ; all exact
selection/locked gates and tie-breaks; None/zero denominators; no-qualifier
status; diagnostic counts, carry-in and end cutoffs; explicit exports, AST
source safety, and V1.3 unchecked manual release state. Existing V1.2 tests
remain unchanged. Run full unittest suite, compileall, pip check, diff check,
and baseline sensitive-path comparison, followed by independent code review.

Self-review: no placeholders or parameter grids; episode ordering and
date/diagnostic boundaries are explicit; V1 and accounting are unchanged;
no empirical gate is silently executed; no methodology is optimized from
results. Push implementation branch and stop before any manual data run.
