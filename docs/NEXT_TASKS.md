# Next Tasks

## 1. Mainland China connectivity validation

Owner: collaborator in mainland China.

Use `docs/CHINA_CONNECTIVITY_TEST.md` and fill the result table for SEC EDGAR, Tiingo, FMP, EODHD, Massive, Twelve Data, Finnhub, and Alpha Vantage. Test without proxy first. Never commit API keys.

Done when:
- Every provider has a result code.
- Tiingo and SEC EDGAR have full price/fundamental smoke-test results.
- Any provider requiring a proxy is explicitly marked.

## 2. Tiingo EOD adapter

Implement a concrete `MarketDataProvider` that returns internal `PriceBar` objects.

Acceptance criteria:
- Reads API key from environment/config, never source control.
- `get_price_history(symbol, start, end)` returns oldest-to-newest bars.
- Maps raw OHLC, adjusted close, volume, and trading date correctly.
- Handles HTTP errors, auth errors, empty data, and rate limits with explicit exceptions.
- Unit tests use fixtures/mocks and require no live API key.
- Add one optional manual smoke test for QQQ.

## 3. SEC EDGAR fundamentals adapter

Implement a concrete `FundamentalsProvider` that returns filing-aware `BalanceSheetSnapshot` objects.

Acceptance criteria:
- Resolves ticker to CIK using a cached mapping.
- Uses SEC Company Facts / submissions data with a declared User-Agent.
- Preserves `period_end` and `filed_date`; never substitutes report period for filing date.
- Maps total assets and total liabilities from standard concepts.
- Computes or maps total debt only when a defensible debt concept set is available; otherwise returns `None` rather than guessing.
- Deduplicates amended/restated facts deterministically.
- Unit tests cover multiple tags, amendments, missing debt, and out-of-order filings.
- Rate limiting stays within SEC fair-access guidance.

## 4. ETF momentum baseline

Start only after the Tiingo adapter is working.

Acceptance criteria:
- Universe configured in a plain config file.
- 6-month and 12-month momentum features.
- Long-term trend filter.
- Monthly rebalance.
- Transaction-cost parameter.
- Compare CAGR, max drawdown, volatility, Sharpe, and turnover against SPY and QQQ buy-and-hold.
