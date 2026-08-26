# Roadmap

## Phase 0 — Foundation

- Repository, collaboration rules, secret hygiene.
- Data-provider interfaces.
- API/vendor evaluation matrix.
- Minimal automated tests.

## Phase 1 — ETF Momentum Baseline

- End-of-day adjusted price data.
- 6-month and 12-month momentum features.
- Long-term trend filter.
- Monthly rebalance rule.
- Benchmark against buy-and-hold SPY/QQQ.

## Phase 2 — Backtest Integrity

- Transaction costs and slippage.
- Train / validation / out-of-sample split.
- Max drawdown, CAGR, volatility, Sharpe, Sortino, turnover.
- Bias checklist: look-ahead, survivorship, data snooping.

## Phase 3 — Equity Multi-Factor

- Fundamentals and filing-date-aware data.
- Momentum, quality, growth, value, and risk factors.
- Ranking and portfolio construction.

## Phase 4 — Paper Trading

- Signal generation separated from execution.
- Position and exposure limits.
- Broker paper-account adapter.
- Order and decision audit log.

## Phase 5 — Small Live Deployment

Only after an agreed paper-trading period and explicit review of live-risk controls.
