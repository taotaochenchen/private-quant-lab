# Data Source Inventory

Research date: 2026-08-26

The project must not be coupled to a single vendor. Strategy code consumes our internal provider interfaces; vendor adapters translate external payloads into `PriceBar` and `BalanceSheetSnapshot` objects.

## Decision summary

### Recommended V1 stack

**Do not buy a large data subscription yet.** For the first ETF momentum backtest, use a long-history EOD price source and keep the universe small enough to fit a free tier. For U.S. fundamentals, use SEC EDGAR as the source of truth while we learn exactly which fields we need.

1. **EOD prices: Tiingo Starter first.** Its free individual tier currently allows 500 unique symbols per month, 1,000 requests per day, and long EOD history. That is enough for the ETF strategy and a controlled equity pilot.
2. **U.S. fundamentals / debt: SEC EDGAR first.** No API key or subscription is required. Company submissions and XBRL Company Facts are available as JSON, and bulk files are available. Filing dates let us build point-in-time logic instead of accidentally using future information.
3. **If normalized fundamentals become the bottleneck: evaluate FMP Premium.** FMP Premium is currently advertised at $59/month billed annually and includes 30+ years of historical data plus full fundamentals and ratios. We still must validate filing-date/as-reported behavior before trusting it for point-in-time backtests.
4. **If we expand globally or need delisted/global EOD coverage: evaluate EODHD.** Its EOD all-world package is currently $19.99/month and its fundamentals package $59.99/month. Exact delisted-data entitlement and point-in-time behavior must be tested before adoption.
5. **Do not pay for real-time data for V1.** Monthly/weekly strategies do not need real-time quotes, websockets, or tick data.

### Important backtest constraint

SEC XBRL Company Facts are strongest from the XBRL era (mandatory reporting began in 2009). If the equity multi-factor backtest must begin in 2007, pre-XBRL fundamentals will require raw-filing parsing or a historical vendor. For V1, a clean solution is:

- ETF momentum backtest: use long EOD price history and test through 2007-2009.
- Multi-factor equity backtest: begin around 2010 unless/until we buy or build reliable pre-XBRL fundamentals.

## Market Regime Engine v1 data semantics

The Market Regime Engine consumes the existing configured EOD provider through
the repository's `MarketDataProvider` abstraction; it does not introduce a
second HTTP client or provider-specific calculation path. It uses
provider-supplied adjusted daily closes for every SPY/QQQ calculation, so
splits and dividends are reflected as the provider defines them. Each bar date
is treated as a U.S. exchange session date, not an intraday timestamp.

SPY is mandatory: the engine needs at least 252 valid sessions and will reject
duplicate dates, non-positive/non-finite adjusted closes, an internal trailing
gap longer than ten calendar days, and dashboard data more than four calendar
days stale. It filters all data after the requested date before calculation.
Missing or unusable SPY data produces a safe unavailable result rather than a
substitute price.

QQQ is optional confirmation only. It needs 201 valid sessions under the same
date/freshness checks. Missing, invalid, stale, or provider-failed QQQ becomes
an unavailable confirmation warning; it cannot block a valid SPY result or
change its score/regime. VIX and market breadth are deliberately absent from
v1: VIX coverage/symbol semantics are not yet established, and the project has
no point-in-time breadth or historical-constituent source. Do not backfill
today's constituents into historical breadth calculations.

No vendor-history or current-regime run was performed during automated work:
`.env` and secrets were intentionally off-limits. Any future manual Tiingo run
must validate the returned adjusted-close coverage, session dates, freshness,
and license terms before its results are relied on.

## Provider matrix

| Provider | Best use | Current entry price / limit | Historical depth relevant to us | Fundamentals / debt | Point-in-time posture | V1 verdict | Mainland China access |
|---|---|---|---|---|---|---|---|
| **SEC EDGAR / data.sec.gov** | U.S. filings, balance-sheet facts, filing metadata | Free; no API key; SEC fair-access guideline currently max 10 requests/sec | Filing indexes reach back to the 1990s; structured XBRL Company Facts strongest from 2009 onward | Yes, filing-derived XBRL; custom normalization required | **Strong candidate** because filing dates and original filings are available; we must map tags carefully | **Use now for U.S. fundamentals** | Friend must test from normal mainland network |
| **Tiingo** | Long-history EOD prices | Starter $0: 500 unique symbols/month, 50 req/hour, 1,000 req/day; Power $30/month: 10,000 req/hour, 100,000/day | Pricing advertises 30+ years; EOD product advertises data back to 1962 for supported securities | Stock fundamentals are a separate add-on; limited evaluation access | Price PIT is straightforward when using date-bounded EOD bars; fundamentals add-on needs separate validation | **Best first price provider** | Friend must test from normal mainland network |
| **Financial Modeling Prep (FMP)** | Normalized fundamentals + prices | Basic free: 250 calls/day; Starter $22/month billed annually; Premium $59/month billed annually; Ultimate $149/month billed annually | Basic/Starter up to ~5 years; Premium 30+ years; Ultimate full historical access | Yes; full statements, ratios, as-reported endpoints and filing dates are advertised across product set | **Needs validation.** Do not assume a normalized historical series is what was known at the time; verify filing dates/restatements | **Best paid normalized-fundamentals candidate** | Friend must test from normal mainland network |
| **EODHD** | Low-cost global EOD + fundamentals | Free 20 calls/day; EOD all-world $19.99/month; fundamentals $59.99/month; all-in-one $99.99/month | Global historical EOD; exact depth varies by exchange/security | Yes on fundamentals package | **Needs validation** for filing-date/as-reported history and revisions | **Strong global candidate; not needed for ETF V1** | Friend must test from normal mainland network |
| **Massive (formerly Polygon.io)** | High-quality U.S. price/reference/corporate-action data | Basic free: 5 calls/min, 2 years; Starter $29/month: 5 years; Developer $79/month: 10 years; Advanced $199/month: 20+ years and financials; financials-only expansion $29/month | 2 / 5 / 10 / 20+ years by tier | Yes on higher plan or financials expansion | Financials PIT behavior needs validation | **Too expensive for our required 2007+ history at V1; useful later** | Friend must test from normal mainland network |
| **Twelve Data** | Broad multi-market API / prototype | Basic free: 8 API credits/minute and 800/day; Grow starts at $29/month depending on credit tier | Plan-dependent | Fundamentals available on paid tiers; a statement request can consume 100 credits per symbol | Needs filing-date/restatement validation | **Good API, but free fundamentals are credit-expensive; not first choice** | Friend must test from normal mainland network |
| **Finnhub** | Market data, filings, estimates, transcripts | U.S./global market-data Basic currently $49.99/month with 150 calls/min | Basic advertises 10 years daily; higher tiers 25 and 40+ years | Available through separate/premium fundamental products | Needs PIT validation; some filing metadata is available | **Secondary candidate; no need to pay yet** | Friend must test from normal mainland network |
| **Alpha Vantage** | Quick prototypes / indicators | Free tier currently limited to 25 requests/day; premium removes daily limit | Endpoint/plan dependent | Many company/fundamental endpoints exist | Needs PIT validation for historical fundamentals | **Too rate-limited for broad research; keep as fallback/demo** | Friend must test from normal mainland network |

## What the pricing means for us

### ETF momentum V1

We only need daily adjusted OHLCV for a small ETF universe. This means we can likely run the first serious backtest for **$0/month**. Real-time market data adds no meaningful value to a monthly rebalance strategy.

### Multi-factor equity V1

The expensive part is not today's price; it is reliable historical fundamentals with correct publication timing, ticker changes, delistings, and revisions. A cheap API that returns a clean balance sheet today can still create a false backtest if it silently gives us restated data that was not known on the historical decision date.

Therefore the order is:

1. Prove factor logic on a smaller U.S. universe with SEC filing-aware data.
2. Measure how much engineering time normalization costs.
3. Only then compare that cost with a paid normalized vendor such as FMP or EODHD.

## Provider-specific notes

### SEC EDGAR

- REST JSON APIs provide submissions history and XBRL Company Facts without authentication.
- Bulk `companyfacts` and `submissions` archives are published for efficient large downloads.
- SEC fair-access guidance currently limits automated access to no more than 10 requests per second and asks automated clients to identify themselves with a declared user agent.
- Company Facts expose standard taxonomy facts, but issuers can use different tags and extensions. A debt metric often requires mapping multiple possible US-GAAP concepts rather than trusting one tag.
- For point-in-time research, store at least `period_end`, `filed_date`, `form`, `accession`, `value`, `unit`, and the taxonomy concept used.

### Tiingo

- Free tier is unusually useful for a private quant lab because it combines long EOD history with a 500-symbol monthly unique-symbol allowance.
- Price API data includes raw and adjusted fields plus split/dividend information.
- Paid Power tier is only worth considering after the free unique-symbol or request limits actually block us.
- Fundamental API access is a separate add-on, so do not assume the $30 Power plan solves our balance-sheet problem.

### FMP

- Attractive because it combines prices, normalized statements, ratios, delisted-company/reference data, and bulk endpoints in one API family.
- Starter's 5-year history is insufficient for our long backtest target.
- Premium is the first tier that aligns well with a 15-20 year research window.
- Before paying, test whether historical financial statements can be retrieved exactly as known on a historical date and how restatements are represented.

### EODHD

- Price is attractive for global EOD data, especially if we later add Canada and non-U.S. markets.
- Pricing pages advertise fundamentals and delisted data across the product family, but we should confirm the exact package entitlement before paying.
- Point-in-time fundamentals remain an explicit test item.

### Massive

- Excellent U.S. market-data product, but the free tier only gives two years of historical stock data.
- To cover our original 2007-2026 target from one Massive stock plan, the relevant tier is Advanced at $199/month. That is unnecessary for our current low-frequency MVP.

### Twelve Data

- Basic is generous for simple price calls but uses a weighted credit system.
- The pricing page's own example shows an income-statement request costing 100 credits per symbol, so broad fundamental pulls can consume quota quickly.
- Keep it in the candidate set, but do not design our V1 around it.

## China connectivity test protocol

A provider is not approved for team use until the collaborator in mainland China tests it from a normal local connection. Do not paste API keys into GitHub Issues or chat.

For each provider record:

1. Signup/login page reachable without proxy: yes/no.
2. API hostname DNS/TLS works: yes/no.
3. Authentication succeeds: yes/no.
4. Fetch current AAPL or QQQ price: HTTP status + latency.
5. Fetch five years of daily AAPL or QQQ bars: status + latency + row count.
6. If fundamentals are included, fetch AAPL balance-sheet history and confirm total assets, total liabilities, and a debt field.
7. Repeat 10 small calls and record any timeouts/429s.
8. Record test date, ISP/network type, provider, plan, and whether a proxy/VPN was used.

Use statuses: `PASS`, `PASS-SLOW`, `FAIL-DNS`, `FAIL-TLS`, `FAIL-AUTH`, `FAIL-TIMEOUT`, `RATE-LIMITED`.

## Non-negotiable checks before adopting any provider

1. **Coverage:** exchanges, symbols, ETFs, corporate actions, delisted securities.
2. **Historical depth:** enough history for the intended strategy window.
3. **Point-in-time correctness:** historical fundamentals must reflect what was actually knowable on the decision date.
4. **Adjustments:** splits, dividends, ticker changes, mergers, delistings.
5. **Survivorship bias:** preserve historical universe membership and delisted names where required.
6. **Latency:** EOD versus intraday requirements; do not buy intraday data for a monthly strategy.
7. **Cost:** free tier, monthly/annual price, overage model.
8. **Rate limits:** request/minute, daily caps, weighted credits, bulk endpoints.
9. **License:** storage, caching, team sharing, internal use, redistribution.
10. **Cross-border reliability:** both Canada and mainland China must be able to use the chosen provider reliably.

## Source notes

Facts above were checked against official provider pages on the research date: SEC Developer Resources and EDGAR API documentation; Tiingo Pricing and EOD product documentation; Financial Modeling Prep Pricing; EODHD Pricing; Massive Stocks Pricing; Twelve Data Individual Pricing; Finnhub market-data pricing/API documentation; Alpha Vantage Premium/API usage page.

Pricing and entitlements change. Re-check the official provider page immediately before purchasing a plan.
