# Roadmap

## Phase 0 — Foundation

- [x] Repository, collaboration rules, secret hygiene.
- [x] Data-provider interfaces.
- [x] Initial API/vendor evaluation matrix.
- [x] Minimal automated tests.
- [ ] Mainland China connectivity smoke test for candidate providers.
- [ ] Implement Tiingo EOD price adapter behind `MarketDataProvider`.
- [ ] Implement SEC EDGAR filing-aware fundamentals adapter behind `FundamentalsProvider`.

**Current default:** avoid paid subscriptions until a free-tier limitation blocks research. Tiingo is the first price-provider candidate; SEC EDGAR is the first U.S. fundamentals candidate.

## Phase 1 — ETF Momentum Baseline

- End-of-day adjusted price data.
- 6-month and 12-month momentum features.
- Long-term trend filter.
- Monthly rebalance rule.
- Benchmark against buy-and-hold SPY/QQQ.
- Run across multiple market regimes, including 2008, 2020 and 2022 where data coverage permits.

## Phase 2 — Backtest Integrity

- Transaction costs and slippage.
- Train / validation / out-of-sample split.
- Max drawdown, CAGR, volatility, Sharpe, Sortino, turnover.
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
