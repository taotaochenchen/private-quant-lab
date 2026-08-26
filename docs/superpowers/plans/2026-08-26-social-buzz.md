# Social Buzz Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add cached ApeWisdom Reddit-discussion metrics to the existing Streamlit stock search without coupling ApeWisdom to Streamlit or Tiingo.

**Architecture:** A framework-agnostic `ApeWisdomProvider` owns public JSON transport, response validation, bounded pagination, ticker matching, and buzz calculations. The Streamlit page injects a five-minute `st.cache_data` page loader, orchestrates price and social lookups independently, and renders safe Social Buzz states.

**Tech Stack:** Python 3.11+, standard-library `urllib`, immutable dataclasses, Streamlit 1.62, and standard-library `unittest`/`unittest.mock`.

## Global Constraints

- Use only `https://apewisdom.io/api/v1.0/filter/all-stocks` and its `/page/{page}` JSON endpoints; never scrape HTML.
- ApeWisdom requires no API key and must never receive or access `MARKET_DATA_API_KEY`.
- Do not read, print, modify, stage, or commit `.env` or any API key.
- Call the section `Social Buzz`, never `Sentiment`.
- Cache API page responses for five minutes with `max_entries=10` in the Streamlit layer.
- Fetch at most ten pages and stop immediately after a ticker is found.
- Preserve existing Tiingo behavior and keep price and Social Buzz failure paths independent.
- Update existing branch `codex/streamlit-stock-research` and PR #9; do not create a new PR.

---

### Task 1: Framework-agnostic ApeWisdom provider

**Files:**
- Create: `src/private_quant/social/__init__.py`
- Create: `src/private_quant/social/apewisdom.py`
- Create: `tests/test_apewisdom_provider.py`
- Modify: `tests/test_package_imports.py`

**Interfaces:**
- Consumes: `PageGetter = Callable[[int], object]` returning decoded ApeWisdom page JSON.
- Produces: `SocialBuzz`, `ApeWisdomError`, `ApeWisdomRequestError`, `ApeWisdomResponseError`, `fetch_apewisdom_page(page: int) -> object`, and `ApeWisdomProvider.find_ticker(ticker: str) -> SocialBuzz | None`.

- [ ] **Step 1: Write the provider behavior tests**

  Create literal page fixtures such as:

  ```python
  {
      "pages": 2,
      "current_page": 1,
      "results": [
          {
              "rank": 1,
              "ticker": "NVDA",
              "mentions": 317,
              "mentions_24h_ago": 281,
              "upvotes": 4074,
          }
      ],
  }
  ```

  Assert that `find_ticker(" nvda ")` returns normalized `NVDA`, rank `1`, current `317`, previous `281`, change approximately `12.8114`, upvotes `4074`, and trend `Rising`. Add separate tests for later-page early stopping, missing tickers, API-reported page limits, the hard ten-page cap, Falling/Flat, previous mentions equal to zero, and structurally invalid page/matching-row payloads.

- [ ] **Step 2: Run provider tests and verify RED**

  Run: `python -m unittest tests.test_apewisdom_provider -v`

  Expected: import failure because `private_quant.social.apewisdom` does not exist.

- [ ] **Step 3: Implement the immutable model and bounded search**

  Implement:

  ```python
  @dataclass(frozen=True, slots=True)
  class SocialBuzz:
      ticker: str
      reddit_rank: int
      mentions: int
      previous_mentions: int
      mention_change_percent: float | None
      upvotes: int
      trend: str

  class ApeWisdomProvider:
      def __init__(self, *, get_page: PageGetter = fetch_apewisdom_page,
                   max_pages: int = 10) -> None: ...
      def find_ticker(self, ticker: str) -> SocialBuzz | None: ...
  ```

  Validate page one before reading its `pages`, iterate only through `min(reported_pages, max_pages)`, compare ticker strings after `strip().upper()`, parse only the matched row into the result, and calculate change/trend using the approved zero-denominator rule.

- [ ] **Step 4: Write transport tests and verify RED**

  Mock `urlopen` with a context-manager response and assert page 1 uses the base endpoint, page 2 uses `/page/2`, the timeout is finite, valid JSON is returned, and `HTTPError`, `URLError`, `TimeoutError`, and invalid JSON raise `ApeWisdomRequestError` without exposing transport details.

- [ ] **Step 5: Implement the standard-library JSON transport**

  Use `Request` with an `Accept: application/json` header and `urlopen(..., timeout=15.0)`. Reject page numbers below one. Decode UTF-8 JSON and map only the specified transport/decoding exceptions into the fixed provider error.

- [ ] **Step 6: Run targeted and full tests**

  Run: `python -m unittest tests.test_apewisdom_provider tests.test_package_imports -v`

  Run: `python -m unittest discover -s tests -v`

  Expected: all tests pass with the new `private_quant.social` package importable.

### Task 2: Streamlit cache, independent search orchestration, and Social Buzz UI

**Files:**
- Modify: `src/private_quant/app/stock_research.py`
- Modify: `tests/test_stock_research_app.py`

**Interfaces:**
- Consumes: `fetch_apewisdom_page`, `ApeWisdomProvider.find_ticker`, existing `lookup_ticker`, and existing safe price-error mapping.
- Produces: `load_apewisdom_page(page: int)`, `lookup_social_buzz(ticker: str)`, `SearchOutcome`, `perform_search(ticker: str)`, `social_buzz_error_message(error: Exception)`, and `render_social_buzz(ticker: str, buzz: SocialBuzz | None, error: Exception | None = None)`.

- [ ] **Step 1: Write failing cache and orchestration tests**

  Assert that clearing `load_apewisdom_page`, patching `fetch_apewisdom_page`, and calling the same page twice invokes the raw fetch once. Add literal dependency-injection tests proving:

  ```python
  outcome = perform_search(
      "AAPL",
      price_loader=lambda ticker: price_result,
      social_loader=lambda ticker: (_ for _ in ()).throw(ApeWisdomRequestError()),
  )
  assert outcome.price_result is price_result
  assert isinstance(outcome.social_error, ApeWisdomRequestError)
  ```

  Add the inverse case where Tiingo fails but Social Buzz succeeds, and assert blank input invokes neither loader.

- [ ] **Step 2: Run app tests and verify RED**

  Run: `python -m unittest tests.test_stock_research_app -v`

  Expected: imports fail because the new cache/orchestration symbols are missing.

- [ ] **Step 3: Implement the cached loader and independent outcome**

  Add exactly:

  ```python
  @st.cache_data(ttl="5m", max_entries=10, show_spinner=False)
  def load_apewisdom_page(page: int) -> object:
      return fetch_apewisdom_page(page)
  ```

  Inject it into `ApeWisdomProvider`. Define a frozen `SearchOutcome` carrying optional price/social results and errors. Normalize before loading either source, then run price and social loaders in separate `try` blocks so either result survives the other's failure.

- [ ] **Step 4: Write failing presentation tests**

  Test fixed safe Social Buzz error copy, signed one-decimal percentage formatting, `N/A` for no percentage, and exact source copy. Use Streamlit `AppTest.from_string` to call `render_social_buzz` with found/missing/error states and assert the expected subheaders, six metrics, info/warning messages, and caption without provider exception text.

- [ ] **Step 5: Implement responsive native Streamlit rendering**

  Render `st.header("Social Buzz")`, `st.subheader(f"{ticker} Social Buzz")`, and a responsive `st.container(horizontal=True)` containing bordered metrics:

  ```python
  st.metric("Reddit rank", f"#{buzz.reddit_rank}", border=True)
  st.metric("24h mentions", f"{buzz.mentions:,}", border=True)
  st.metric("Previous 24h", f"{buzz.previous_mentions:,}", border=True)
  st.metric("Mention change", formatted_change, border=True)
  st.metric("Upvotes", f"{buzz.upvotes:,}", border=True)
  st.metric("Buzz trend", buzz.trend, border=True)
  ```

  Always render `Source: ApeWisdom — Reddit stock communities`. For missing data use a neutral info message; for provider errors use a fixed warning. Update `main()` to render price result/error and Social Buzz result/error independently, then keep the Fundamentals placeholder.

- [ ] **Step 6: Run app, provider, and full tests**

  Run: `python -m unittest tests.test_stock_research_app tests.test_apewisdom_provider -v`

  Run: `python -m unittest discover -s tests -v`

  Expected: all tests pass and all prior Tiingo tests remain green.

### Task 3: Local and browser verification

**Files:**
- Modify only if verification reveals a tested defect; do not access `.env` directly.

**Interfaces:**
- Consumes: the completed Streamlit application.
- Produces: compile/test/smoke/browser evidence for AAPL and QQQ.

- [ ] **Step 1: Run static and dependency checks**

  Run: `python -m compileall -q src tests`

  Run: `python -m pip check`

  Run: `git diff --check`

- [ ] **Step 2: Start Streamlit without opening configuration files**

  Run the installed Streamlit app headlessly on an available local port. Let the application use its normal configuration path; do not open, print, copy, modify, or stage `.env`.

- [ ] **Step 3: Verify AAPL and QQQ in a real browser**

  For each ticker, submit the existing Search form and confirm the price section still renders latest EOD metrics and the Social Buzz section renders either six ApeWisdom metrics or the approved not-currently-discussed state. Confirm the exact source caption is visible and no credential appears anywhere.

- [ ] **Step 4: Stop the local server and rerun the full suite**

  Stop only the Streamlit process started for this task, then run `python -m unittest discover -s tests -v` and compile checks once more.

### Task 4: Review and update PR #9

**Files:**
- Review all changed files and Git metadata; no additional production file is required.

**Interfaces:**
- Consumes: verified commits on `codex/streamlit-stock-research`.
- Produces: updated PR #9 with Social Buzz summary and test/browser evidence.

- [ ] **Step 1: Perform security and scope review**

  Confirm no `.env` path is staged, no API key value appears in the diff, ApeWisdom code imports neither Streamlit nor Tiingo, only JSON API URLs are present, pagination is capped, and no trading/order code was introduced.

- [ ] **Step 2: Request independent code review**

  Review the committed range against the approved design and this plan. Fix all Critical and Important findings with a failing regression test first, then rerun verification.

- [ ] **Step 3: Push and update the existing PR**

  Push `codex/streamlit-stock-research`, update PR #9's body to mention Social Buzz, the public API/no-key design, caching/pagination cap, full test count, and AAPL/QQQ browser evidence, then verify PR #9 remains open against `main`.
