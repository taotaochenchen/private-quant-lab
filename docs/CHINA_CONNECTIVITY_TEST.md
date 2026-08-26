# Mainland China Data Provider Connectivity Test

Use this checklist from a normal mainland China network. Do not commit or paste API keys anywhere in the repository.

## Providers to test

- SEC EDGAR / data.sec.gov
- Tiingo
- Financial Modeling Prep (FMP)
- EODHD
- Massive
- Twelve Data
- Finnhub
- Alpha Vantage

## Test steps for each provider

1. Signup/login page reachable without proxy: yes/no.
2. API hostname resolves and TLS connection succeeds: yes/no.
3. Authentication succeeds with a personal test key where required.
4. Fetch current AAPL or QQQ price; record HTTP status and latency.
5. Fetch five years of daily AAPL or QQQ bars; record status, latency, and row count.
6. If fundamentals are included, fetch AAPL balance-sheet history and confirm total assets, total liabilities, and a debt field.
7. Repeat 10 small calls and record timeouts or rate-limit responses.
8. Record test date, network type, provider plan, and whether any proxy/VPN was used.

## Result codes

- `PASS`
- `PASS-SLOW`
- `FAIL-DNS`
- `FAIL-TLS`
- `FAIL-AUTH`
- `FAIL-TIMEOUT`
- `RATE-LIMITED`

## Result table

| Provider | Date | Network | No-proxy signup | API status | Price test | 5Y bars | Fundamentals | Avg latency | 10-call stability | Result | Notes |
|---|---|---|---|---|---|---|---|---:|---|---|---|
| SEC EDGAR |  |  |  |  |  |  |  |  |  |  |  |
| Tiingo |  |  |  |  |  |  |  |  |  |  |  |
| FMP |  |  |  |  |  |  |  |  |  |  |  |
| EODHD |  |  |  |  |  |  |  |  |  |  |  |
| Massive |  |  |  |  |  |  |  |  |  |  |  |
| Twelve Data |  |  |  |  |  |  |  |  |  |  |  |
| Finnhub |  |  |  |  |  |  |  |  |  |  |  |
| Alpha Vantage |  |  |  |  |  |  |  |  |  |  |  |
