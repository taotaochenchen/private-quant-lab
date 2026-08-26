# Data Source Inventory

The project should not be coupled to a single vendor. Candidate data sources are evaluated here before an adapter is promoted into production research.

## Evaluation matrix

| Provider | Status | Price history | Fundamentals / debt | Point-in-time data | Free tier | Paid plan | Rate limits | Canada access | Mainland China access | Redistribution / license notes | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SEC EDGAR / companyfacts | Research | No | Yes, filing-derived | Filing timestamps available; normalization required | Yes | N/A | Public API policies apply | To verify | To verify | Raw public filings; respect SEC fair-access policy | Strong source of truth for U.S. filings, but requires cleaning/mapping |
| Candidate A | To evaluate |  |  |  |  |  |  |  |  |  |  |
| Candidate B | To evaluate |  |  |  |  |  |  |  |  |  |  |
| Candidate C | To evaluate |  |  |  |  |  |  |  |  |  |  |

## Required checks before adopting a provider

1. Coverage: exchanges, symbols, delisted securities, ETFs, corporate actions.
2. Historical depth: enough history for the strategy's intended test window.
3. Point-in-time correctness: whether historical fundamentals reflect what was actually known on each decision date.
4. Adjustments: splits, dividends, ticker changes, mergers, delistings.
5. Survivorship bias: whether delisted securities are preserved where needed.
6. Latency: end-of-day versus intraday requirements.
7. Cost: free tier, monthly price, overage model, commercial-use restrictions.
8. Rate limits: requests/minute, daily caps, bulk endpoints.
9. Terms: storage, caching, sharing, redistribution, team usage.
10. Cross-border reliability: whether both collaborators can reliably access the provider from Canada and mainland China.

## Adapter policy

Strategy code must consume internal interfaces rather than vendor-specific payloads. A provider adapter translates external responses into internal models. Replacing a vendor should not require rewriting strategy logic.
