# Social Buzz Design

Date: 2026-08-26

## Goal

Extend the existing local Streamlit Stock Research page with public Reddit stock-discussion activity from ApeWisdom. The section is called **Social Buzz**, not sentiment, because the public ApeWisdom API does not document a bullish/bearish sentiment score.

## Scope

For the ticker submitted through the existing stock search form, show:

- Reddit rank
- mentions in the latest 24 hours
- mentions in the previous 24 hours
- percentage change in mentions
- upvotes
- buzz trend: `Rising`, `Falling`, or `Flat`
- source copy: `Source: ApeWisdom — Reddit stock communities`

Do not scrape ApeWisdom HTML, require an ApeWisdom API key, add trading functionality, or change Tiingo credentials or configuration.

## Architecture

Create a framework-agnostic provider in `src/private_quant/social/apewisdom.py`. It owns ApeWisdom URLs, HTTP/JSON handling, payload validation, ticker matching, pagination, metric calculation, and provider-specific exceptions. It must not import Streamlit or reference Tiingo.

The Streamlit app owns a thin cached page loader decorated with:

```python
@st.cache_data(ttl="5m", max_entries=10)
```

The cached loader calls the provider's public page-fetch function. `ApeWisdomProvider` receives that loader through dependency injection, so provider tests use mocked page responses without Streamlit.

The existing Tiingo price lookup and the new Social Buzz lookup run as independent result paths after a ticker has been normalized. A Tiingo failure must not be relabeled as an ApeWisdom failure, and an ApeWisdom failure must not suppress successfully loaded price data.

## Provider model and calculations

Return an immutable `SocialBuzz` result with:

- normalized ticker
- integer Reddit rank
- integer current mentions
- integer previous mentions
- optional mention-change percentage
- integer upvotes
- trend string

Calculate mention change as:

```text
(current mentions - previous mentions) / previous mentions * 100
```

If previous mentions are zero, return no percentage rather than inventing a mathematically misleading value. Trend is still `Rising` when current mentions are positive, `Flat` when both are zero, and otherwise follows the numeric comparison.

## Pagination and caching

Start at the unpaged endpoint:

```text
https://apewisdom.io/api/v1.0/filter/all-stocks
```

For subsequent pages use:

```text
https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page}
```

Stop as soon as the case-insensitive ticker match is found. Never fetch beyond the lesser of the API's reported page count and ten pages. Cache each page response for five minutes with at most ten cached entries, allowing multiple ticker searches to reuse the same public responses.

## User interface

After a valid search, render a `Social Buzz` section independently of the existing price and Fundamentals sections.

When data is found, show a ticker-specific subheading and responsive metric cards for rank, current mentions, previous mentions, change percentage, upvotes, and trend. Format counts with thousands separators, rank with `#`, and percentage with a sign and one decimal place. Display `N/A` when prior mentions are zero.

Always display:

```text
Source: ApeWisdom — Reddit stock communities
```

When a ticker is not in the capped results, show a neutral message that it is not currently discussed. When ApeWisdom is unavailable or returns invalid data, show a fixed retryable warning without exception details. The existing price result or price error remains visible.

## Error handling and security

- Use the public JSON API only.
- Use no ApeWisdom credential.
- Do not read, print, modify, or commit `.env` during implementation or verification.
- Never access, display, modify, or pass `MARKET_DATA_API_KEY` to ApeWisdom code.
- Convert HTTP, network, and invalid-JSON failures into an `ApeWisdomRequestError`.
- Convert structurally invalid API data into an `ApeWisdomResponseError`.
- The UI maps both to fixed Social Buzz warnings and never renders provider exception text.

## Testing

Use mocked ApeWisdom page loaders to cover:

- ticker normalization and first-page matches
- later-page matches and early stopping
- the ten-page maximum
- API-reported page limits smaller than ten
- missing tickers
- mention percentage and Rising/Falling/Flat rules
- zero previous mentions
- malformed page and row payloads
- HTTP, network, and invalid-JSON mapping
- Streamlit page-cache reuse
- UI formatting, missing-discussion copy, and safe provider-error copy
- independence of Tiingo price rendering and Social Buzz rendering

Run the entire existing test suite, Python compile checks, Streamlit AppTest coverage, and browser searches for AAPL and QQQ. Browser verification may allow the application itself to load its normal local configuration, but implementation tools must not directly open or print `.env` or any API key.

## Delivery

Commit the feature to `codex/streamlit-stock-research`, push it, and update existing pull request #9 targeting `main`.
