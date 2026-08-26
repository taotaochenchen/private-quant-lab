# ETF Momentum V1

## Goal

Test whether a simple, explainable U.S.-listed ETF rotation strategy can improve risk-adjusted returns versus passive SPY and QQQ buy-and-hold before adding individual stocks, machine learning, leverage, or intraday trading.

## Virtual portfolio

- Starting capital: **USD 100,000**
- Universe: SPY, QQQ, IWM, DIA, XLK, XLF, XLE, XLV, GLD, TLT
- Portfolio size: top 3 eligible ETFs
- Rebalance: monthly
- Default transaction-cost assumption: 5 bps of traded notional
- Fractional units: allowed in research backtests

## Signal

For each ETF on a decision date:

1. Calculate approximately 6-month total return using 126 trading days.
2. Calculate approximately 12-month total return using 252 trading days.
3. Score = average of the 6-month and 12-month returns.
4. Require adjusted close to be above the 200-trading-day moving average.
5. Rank eligible ETFs by score and hold the top 3 equally.
6. If no ETF passes the trend filter, remain in cash.

## Look-ahead control

The first available trading date of a new calendar month is the execution date. The ranking uses data only through the previous available trading date. Future prices are never included in the signal calculation.

## Evaluation

Report at least:

- Final portfolio value
- CAGR
- Maximum drawdown
- Annualized volatility
- Sharpe ratio
- Cumulative turnover
- Total modeled transaction cost
- SPY buy-and-hold metrics
- QQQ buy-and-hold metrics

The strategy is not considered useful merely because it makes money. It must be judged relative to passive benchmarks and across multiple market regimes.

## Data requirement

Use adjusted daily prices so splits and distributions do not create false signals. V1 is designed to run on Tiingo EOD data behind the internal `MarketDataProvider` interface.
