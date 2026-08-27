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
- [ ] Run the documented historical windows on live Tiingo EOD history. This
  remains unchecked because automated work did not read `.env` or use a
  secret-backed provider run.
- [ ] Validate adjusted-close coverage, session dates, and provider freshness
  with an authorized manual data run before relying on historical results.

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
- [ ] Run the authorized manual Tiingo validation through the latest common
  complete SPY/BIL interval and report sanitized SPY/BIL/QQQ coverage.
- [ ] Confirm provider freshness relative to the manual run date before
  treating the latest interval as current.

Evaluation V1.1 changes research measurement only. Market Regime V1 scoring,
thresholds, confidence, and its 100% / 70% / 30% / 0% exposure mapping are
unchanged, and no broker or trading behavior is added.

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
