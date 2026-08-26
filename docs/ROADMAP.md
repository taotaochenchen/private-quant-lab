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
