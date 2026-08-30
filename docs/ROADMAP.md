# Roadmap

## Phase 0 — Foundation

- [x] Repository, collaboration rules, secret hygiene.
- [x] Data-provider interfaces.
- [x] Initial API/vendor evaluation matrix.
- [x] Minimal automated tests.
- [ ] Mainland China connectivity smoke test for candidate providers.
- [x] Implement Tiingo EOD price adapter behind `MarketDataProvider`.
- [ ] Implement SEC EDGAR filing-aware fundamentals adapter behind `FundamentalsProvider`.

**Current default:** avoid paid subscriptions until a free-tier limitation blocks research. Tiingo is the first price-provider candidate; SEC EDGAR is the first U.S. fundamentals candidate.

## Phase 1 — ETF Momentum Baseline

- [x] Define USD 100,000 virtual portfolio and ETF universe.
- [x] Implement 6-month and 12-month momentum features.
- [x] Implement 200-trading-day trend filter.
- [x] Implement monthly rebalance with prior-date signal to avoid look-ahead.
- [x] Model configurable transaction costs.
- [x] Implement CAGR, max drawdown, volatility, Sharpe and turnover metrics.
- [x] Implement SPY/QQQ buy-and-hold benchmark engine.
- [ ] Run the full historical backtest on live Tiingo EOD data.
- [ ] Validate results across multiple market regimes, including 2008, 2020 and 2022 where data coverage permits.

## Phase 2 — Backtest Integrity

- Transaction costs and slippage sensitivity.
- Train / validation / out-of-sample split where parameter tuning is introduced.
- Sortino ratio and additional downside-risk metrics.
- Bias checklist: look-ahead, survivorship, data snooping.
- Corporate-action and adjusted-price validation.
- Provider consistency checks on overlapping samples.

## Market Regime Engine v1 — Implemented research baseline

- [x] Deterministic SPY adjusted-close regime engine with trend, momentum,
  drawdown, and realized-volatility components.
- [x] Inclusive regime thresholds, confidence evidence, maximum-long-exposure
  guidance, and optional QQQ confirmation.
- [x] Point-in-time historical evaluator with forward-return reporting,
  episodes, transitions, whipsaw statistics, and regime-capped comparison.
- [x] Read-only Streamlit Market Regime dashboard using the existing EOD
  provider abstraction only after the user selects **Evaluate regime**.
- [x] Source-safety regression for broker/order isolation and direct `.env`
  access.
- [x] Completed the documented historical-window validation with an authorized,
  sanitized Tiingo run on 2026-08-27 using data through 2026-08-26.
- [x] Validated adjusted-close coverage, session dates, and provider freshness
  for the 2026-08-27 run. Freshness is not permanent and must be rechecked on
  every future run. No market data, validation console output, credentials,
  API keys, or `.env` content is committed.

## Market Regime Evaluation V1.1 — Implemented research comparison

- [x] Compare SPY buy-and-hold, the prior-session 200-session trend benchmark,
  Regime V1 with zero-yield residual cash, and Regime V1 with a BIL-return
  residual cash proxy on one common interval calendar.
- [x] Apply the explicit `signal_date` to `return_end_date` one-session lag and
  deterministic 0/2/5/10-basis-point SPY exposure-cost sensitivity.
- [x] Report fixed performance, turnover, exposure, and historical-window
  summaries with synthetic point-in-time regression coverage.
- [x] Enforce research-layer source safety: no UI, broker, order, configuration,
  `.env`, or external-provider dependency in the evaluator.
- [x] Completed the authorized manual Tiingo validation on 2026-08-27 through
  the latest common complete SPY/BIL interval, with sanitized SPY/BIL/QQQ
  coverage through 2026-08-26.
- [x] Confirmed provider freshness relative to the 2026-08-27 manual run date.
  Freshness is specific to that run and must be rechecked on every future run
  before treating its latest interval as current.

Evaluation V1.1 changes research measurement only. Market Regime V1 scoring,
thresholds, confidence, and its 100% / 70% / 30% / 0% exposure mapping are
unchanged, and no broker or trading behavior is added.

## Market Regime Stabilization & Re-entry V1.2 — Closed research study

- [x] Implement and verify the unchanged-V1 downstream state machine with
  immediate de-risking, one-level confirmed re-entry, and the exact 12 fixed
  `{0, 5, 10} x {1, 2, 3, 5}` candidate grid.
- [x] Verify the fixed Development, Validation, Combined selection, locked,
  and descriptive diagnostic windows; the 5 bps Regime V1 + BIL residual-cash
  baseline; and the predeclared qualification, tie-break, and promotion gates.
- [x] Verify deterministic failure outcomes (`NO_QUALIFIED_CANDIDATE` and
  `NO_V1_2_PROMOTION`), source isolation, and absence of an execution path.
- [x] Manual Stage 1 completed under the predeclared protocol using only SPY/BIL
  history through 2020-12-31. The fixed 12-candidate search completed and no
  candidate passed every qualification gate: `NO_QUALIFIED_CANDIDATE`.
- [x] V1.2 research promotion rejected. No winner was frozen, and the Stage 2
  decision gate was closed without running Stage 2 because no qualifying
  candidate existed.

The Stage 1 result was accepted without after-the-fact parameter retuning.
No 2021+ data was fetched or inspected during Stage 1. No V1.2 research result
changes Market Regime V1 or authorizes broker, paper, or live execution.

## Market Regime V1.3 — Re-entry Structure Study (future research)

**Closed after Manual Stage 1 (2026-08-30).** The original future-research
heading is retained as a historical roadmap label; this study is now closed.
It was conducted under a new separately approved design and protocol.

- [x] V1.3 infrastructure implemented and synthetically verified: exactly three
  fixed recovery-episode structures, unchanged V1 + BIL accounting, frozen
  selection/promotion gates, diagnostics, narrow exports, and source safety.
- [x] V1.3 Manual Stage 1 completed on 2026-08-30: exactly one authorized
  fixed-protocol run, using SPY 2006-09-01 through 2020-12-31 (3,608 rows)
  and BIL 2007-10-01 through 2020-12-31 (3,338 rows), with no QQQ.
  The common evaluation covered 3,337 intervals from 2007-10-01 through
  2020-12-31. Result: `NO_QUALIFIED_V1_3_CANDIDATE`.
- [ ] V1.3 Manual Stage 2 closed without running: no candidate qualified.

`winner = None`; qualifier ranking `()`. There is no empirical winner and
no V1.3 promotion; V1.3 research promotion is rejected. All three candidates
passed the first five gates but failed the frozen turnover and whipsaw gates.
See `MARKET_REGIME_V1.md` for the sanitized baseline/candidate results and
the bounded interpretation. No real 2021+ V1.3 data was fetched or inspected.

No retuning occurred. V1.3 implementation remains unchanged by this
documentation closure; Market Regime V1 and V1.2 are unchanged. There is no
broker, order, paper-trading, or live-trading implication.
Any successor research requires a new separately approved design.

## Phase 3 — Equity Multi-Factor

- Fundamentals and filing-date-aware data.
- Begin the first clean fundamental backtest around the XBRL era (approximately 2010+) unless reliable pre-XBRL data is added.
- Momentum, quality, growth, value, and risk factors.
- Ranking and portfolio construction.
- Compare engineering cost of raw SEC normalization with a paid normalized provider before purchasing one.

## Phase 4 — Paper Trading

- Signal generation separated from execution.
- Position and exposure limits.
- Broker paper-account adapter.
- Order and decision audit log.

## Phase 5 — Small Live Deployment

Only after an agreed paper-trading period and explicit review of live-risk controls.
