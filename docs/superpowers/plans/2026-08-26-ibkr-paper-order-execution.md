# IBKR Paper Order Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a framework-independent IBKR PAPER order Preview and execution workflow while keeping every production Submit path hard-disabled until a future explicit approval.

**Architecture:** Preserve the Phase 1 read-only `BrokerProvider`. Add a separate `PaperOrderExecutionProvider`, immutable order models, an IBKR-specific executor, and a narrow official-API session adapter. The Streamlit ticket can Preview orders, but its Submit button and production executor remain locked; mocked sessions exercise the complete submission and status workflow.

**Tech Stack:** Python 3.11+, standard-library `dataclasses`, `Decimal`, `datetime`, `enum`, `secrets`, `threading`, the separately installed official IBKR TWS Python API, Streamlit 1.48+, and `unittest`/Streamlit `AppTest`.

## Global Constraints

- Use only `BROKER_PROVIDER=ibkr`, `BROKER_MODE=paper`, `BROKER_HOST=127.0.0.1`, `BROKER_PORT=7497`, and `BROKER_CLIENT_ID=10`.
- Reject every non-paper, non-loopback, wrong-port, or wrong-client configuration before opening a socket.
- Support US `STK/SMART/USD` stocks and ETFs only, with exactly one resolved contract.
- Support BUY, SELL, MARKET, and LIMIT; quantity defaults to `1` and must be a positive integer.
- MARKET Preview makes a new IBKR snapshot request and requires live market-data type `1`; BUY uses the returned ask and SELL uses the returned bid. Its explicitly named `MARKET_PREVIEW_SAFETY_BUFFER_LIMIT` is USD 950, reserving USD 50 below the separate USD 1,000 Submit hard limit; USD 950 is not the Submit limit.
- MARKET Submit makes another new IBKR live snapshot request and allows at most USD 1,000 estimated notional.
- LIMIT Preview and Submit use the entered limit price and allow at most USD 1,000 notional.
- Reject delayed, frozen, missing, non-positive, NaN, or infinite MARKET quote values; never fall back to Tiingo, cached prices, prior closes, or guesses. The snapshot `tickPrice` callback has no timestamp, so actual bid/ask age is unavailable and not independently verified; do not claim stale-quote detection.
- Require an exact, unexpired, one-time Preview before Submit and consume it before any submission attempt.
- Require exactly one managed account for an enabled submission while retaining only the account count, never an account identifier.
- Keep TWS Read-Only API enabled, the Streamlit Submit button disabled, and the production executor locked with `submission_enabled=False` throughout this pull request.
- Do not connect to TWS or call `placeOrder` during automated or browser verification.
- Add no live trading, automatic strategy execution, cancel, replace, modify, batch, what-if, `reqIds`, or automatic retry path.
- Do not read, print, modify, store, render, or commit `.env`, account IDs, credentials, API keys, raw broker errors, or advanced rejection payloads.
- Do not add an unofficial `ibapi` PyPI dependency.

---

### Task 1: Add immutable order contracts and safe errors

**Files:**
- Create: `src/private_quant/broker/order_models.py`
- Create: `src/private_quant/broker/order_base.py`
- Modify: `src/private_quant/broker/__init__.py`
- Create: `tests/test_order_contracts.py`

**Interfaces:**
- Produces: `OrderSide`, `OrderType`, `QuoteSource`, `OrderStatus`, `OrderIntent`, `OrderPreview`, and `OrderResult`.
- Produces: `PaperOrderExecutionProvider.preview_order(intent) -> OrderPreview` and `submit_order(preview) -> OrderResult`.
- Produces typed errors used by the executor and UI: `OrderConfigurationError`, `InvalidOrderIntentError`, `UnsupportedContractError`, `OrderQuoteUnavailableError`, `OrderNotionalLimitError`, `OrderPreviewRequiredError`, `OrderPreviewExpiredError`, `DuplicateOrderSubmissionError`, `OrderSubmissionDisabledError`, `OrderConnectionError`, and `OrderStatusTimeoutError`.

- [ ] **Step 1: Write failing contract tests**

```python
class OrderContractTests(unittest.TestCase):
    def test_models_are_immutable_and_have_no_account_fields(self) -> None:
        intent = OrderIntent(
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
        )
        preview = OrderPreview(
            preview_id="preview-1",
            intent=intent,
            estimated_unit_price=Decimal("100"),
            estimated_notional=Decimal("100"),
            quote_source=QuoteSource.IBKR_LIVE_ASK,
            created_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
            expires_at=datetime(2026, 8, 26, 0, 1, tzinfo=timezone.utc),
        )
        with self.assertRaises(FrozenInstanceError):
            preview.preview_id = "changed"
        for model in (OrderIntent, OrderPreview, OrderResult):
            self.assertNotIn("account", {field.name for field in fields(model)})

    def test_status_values_cover_required_ibkr_outcomes(self) -> None:
        self.assertEqual(
            {status.value for status in OrderStatus},
            {
                "pending_submit", "pre_submitted", "submitted", "filled",
                "cancelled", "rejected", "inactive", "unknown",
            },
        )
```

- [ ] **Step 2: Run the contract tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_order_contracts -v
```

Expected: import failure because `order_models` and `order_base` do not exist.

- [ ] **Step 3: Implement the immutable models and protocol**

Use frozen, slotted dataclasses and `StrEnum` values. The public protocol is:

```python
@dataclass(frozen=True, slots=True)
class OrderIntent:
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int = 1
    limit_price: Decimal | None = None

class PaperOrderExecutionProvider(Protocol):
    def preview_order(self, intent: OrderIntent) -> OrderPreview:
        """Validate and issue a short-lived one-time Preview."""

    def submit_order(self, preview: OrderPreview) -> OrderResult:
        """Consume an issued Preview and return a sanitized broker result."""
```

`OrderIntent` defaults `quantity` to `1` and `limit_price` to `None`.
`OrderResult` uses `Decimal` for all quantities and prices and contains no raw
IBKR objects.

- [ ] **Step 4: Run the contract tests and verify GREEN**

Run the Task 1 command again and confirm all contract tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add src/private_quant/broker/order_models.py src/private_quant/broker/order_base.py src/private_quant/broker/__init__.py tests/test_order_contracts.py
git commit -m "feat: add paper order contracts"
```

---

### Task 2: Implement intent validation, contract resolution, quotes, and Preview

**Files:**
- Create: `src/private_quant/broker/ibkr_orders.py`
- Create: `tests/test_ibkr_order_execution.py`

**Interfaces:**
- Consumes: Task 1 models, protocol, and errors.
- Produces internal immutable `ResolvedContract`, `LiveQuote`, and `OrderUpdate` values.
- Produces `IbkrOrderSession` and `IbkrOrderSessionFactory` injection contracts.
- Produces `IbkrPaperOrderExecutor.preview_order()`.

- [ ] **Step 1: Write failing validation and Preview tests**

Create a fake session that records method names but contains no `ibapi` object:

```python
class FakeOrderSession:
    def __init__(self) -> None:
        self.connected = True
        self.managed_account_count = 1
        self.next_order_id = 7001
        self.contracts = (
            ResolvedContract("AAPL", 265598, "STK", "SMART", "USD"),
        )
        self.quote = LiveQuote(
            market_data_type=1,
            bid=Decimal("99"),
            ask=Decimal("100"),
        )
        self.calls: list[str] = []

    def start(self, host: str, port: int, client_id: int) -> None:
        self.calls.append("start")

    def wait_until_connected(self, timeout: float) -> bool:
        self.calls.append("wait_connected")
        return self.connected

    def resolve_contracts(self, symbol: str, timeout: float):
        self.calls.append("resolve_contracts")
        return self.contracts

    def request_live_quote(self, contract, timeout: float):
        self.calls.append("request_live_quote")
        return self.quote

    def close(self) -> None:
        self.calls.append("close")
```

Add separate tests proving:

```python
def test_buy_market_preview_uses_new_live_snapshot_ask_and_default_quantity():
    preview = make_executor(session).preview_order(
        OrderIntent(" aapl ", OrderSide.BUY, OrderType.MARKET)
    )
    assert preview.intent.symbol == "AAPL"
    assert preview.intent.quantity == 1
    assert preview.estimated_unit_price == Decimal("100")
    assert preview.quote_source is QuoteSource.IBKR_LIVE_ASK

def test_sell_market_preview_uses_new_live_snapshot_bid():
    preview = make_executor(session).preview_order(
        OrderIntent("AAPL", OrderSide.SELL, OrderType.MARKET, quantity=2)
    )
    assert preview.estimated_notional == Decimal("198")
    assert preview.quote_source is QuoteSource.IBKR_LIVE_BID

def test_limit_preview_uses_limit_and_skips_market_data():
    preview = make_executor(session).preview_order(
        OrderIntent(
            "AAPL", OrderSide.BUY, OrderType.LIMIT,
            quantity=2, limit_price=Decimal("75"),
        )
    )
    assert preview.estimated_notional == Decimal("150")
    assert "request_live_quote" not in session.calls
```

Also cover malformed symbols, unsupported/ambiguous contracts, invalid
quantity types and values, MARKET with a limit, LIMIT without a valid limit,
quote market-data types `2`, `3`, and `4`, missing bid/ask, non-positive quote,
`NaN`, infinity, and MARKET Preview notional above USD 950.

- [ ] **Step 2: Run Preview tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_ibkr_order_execution -v
```

Expected: import failure because `ibkr_orders.py` does not exist.

- [ ] **Step 3: Implement strict validation and Preview**

Implement exact constants:

```python
_PAPER_HOST = "127.0.0.1"
_PAPER_PORT = 7497
_PAPER_CLIENT_ID = 10
MARKET_PREVIEW_SAFETY_BUFFER_LIMIT = Decimal("950")
ORDER_SUBMIT_HARD_LIMIT = Decimal("1000")
_PREVIEW_LIFETIME = timedelta(seconds=60)
_DEFAULT_TIMEOUT = 12.0
_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
```

Constructor validation must happen before saving the session factory:

```python
if (
    mode.strip().lower() != "paper"
    or host != _PAPER_HOST
    or port != _PAPER_PORT
    or client_id != _PAPER_CLIENT_ID
):
    raise OrderConfigurationError(_SAFE_CONFIGURATION_MESSAGE)
```

Use a fresh session for every Preview, close it in `finally`, require exactly
one `ResolvedContract`, and validate all decimal values with `is_finite()` and
`value > 0`. MARKET selects `quote.ask` for BUY and `quote.bid` for SELL only
when `market_data_type == 1`. Store the exact issued preview in a private
dictionary protected by a lock.

- [ ] **Step 4: Run Preview tests and verify GREEN**

Run the Task 2 command and then:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_order_contracts tests.test_ibkr_order_execution -v
```

- [ ] **Step 5: Commit Task 2**

```powershell
git add src/private_quant/broker/ibkr_orders.py tests/test_ibkr_order_execution.py
git commit -m "feat: add safe paper order previews"
```

---

### Task 3: Implement locked submission, revalidation, idempotency, and status mapping

**Files:**
- Modify: `src/private_quant/broker/ibkr_orders.py`
- Modify: `tests/test_ibkr_order_execution.py`

**Interfaces:**
- Consumes: `OrderPreview` values issued by the same executor.
- Extends `IbkrOrderSession` with `wait_for_managed_accounts`,
  `submit_order`, and `wait_for_order_update`.
- Produces `IbkrPaperOrderExecutor.submit_order()` and fixed IBKR status mapping.

- [ ] **Step 1: Write failing submission safety tests**

Add fake-session submission methods and focused tests:

```python
def test_production_submission_lock_fails_before_session_creation():
    factory = Mock()
    executor = make_executor(factory=factory, submission_enabled=False)
    with self.assertRaises(OrderSubmissionDisabledError):
        executor.submit_order(make_preview())
    factory.assert_not_called()

def test_submit_requires_preview_issued_by_same_executor():
    with self.assertRaises(OrderPreviewRequiredError):
        enabled_executor.submit_order(make_preview(preview_id="foreign"))

def test_duplicate_submit_is_blocked_before_second_broker_call():
    preview = enabled_executor.preview_order(valid_limit_intent())
    enabled_executor.submit_order(preview)
    with self.assertRaises(DuplicateOrderSubmissionError):
        enabled_executor.submit_order(preview)
    self.assertEqual(session.submit_count, 1)

def test_market_submit_requotes_and_blocks_above_one_thousand():
    preview = enabled_executor.preview_order(valid_market_intent())
    session.quote = LiveQuote(1, Decimal("1001"), Decimal("1001"))
    with self.assertRaises(OrderNotionalLimitError):
        enabled_executor.submit_order(preview)
    self.assertEqual(session.submit_count, 0)
```

Add separate tests for expired preview, changed preview dataclass, LIMIT
revalidation, zero/multiple managed accounts, connection failure, status
timeout, and the required status mappings:

```python
IBKR_STATUS_CASES = {
    "PendingSubmit": OrderStatus.PENDING_SUBMIT,
    "PreSubmitted": OrderStatus.PRE_SUBMITTED,
    "Submitted": OrderStatus.SUBMITTED,
    "Filled": OrderStatus.FILLED,
    "Cancelled": OrderStatus.CANCELLED,
    "ApiCancelled": OrderStatus.CANCELLED,
    "Inactive": OrderStatus.INACTIVE,
    "unrecognized": OrderStatus.UNKNOWN,
}
```

Prove a sanitized broker rejection maps to `REJECTED` and no fake raw error or
account sentinel appears in `OrderResult`, exception text, or exception chains.

- [ ] **Step 2: Run submission tests and verify RED**

Run the Task 2 test command. Expected failures: `submit_order` is missing or
does not enforce the new safety rules.

- [ ] **Step 3: Implement one-time Submit and status mapping**

The method order is fixed:

```python
def submit_order(self, preview: OrderPreview) -> OrderResult:
    if not self._submission_enabled:
        raise OrderSubmissionDisabledError(_SAFE_SUBMISSION_DISABLED_MESSAGE)
    self._consume_exact_unexpired_preview(preview)
    session = self._session_factory()
    try:
        self._connect(session)
        self._require_one_managed_account(session)
        contract = self._resolve_one_contract(session, preview.intent.symbol)
        self._revalidate_submit_notional(session, contract, preview.intent)
        order_id = self._require_next_order_id(session)
        session.submit_order(order_id, contract, preview.intent, preview.preview_id)
        update = session.wait_for_order_update(order_id, self._timeout)
        if update is None:
            raise OrderStatusTimeoutError(_SAFE_STATUS_TIMEOUT_MESSAGE)
        return self._to_result(preview.preview_id, order_id, update)
    finally:
        session.close()
```

`_consume_exact_unexpired_preview` compares the stored frozen dataclass with
the supplied value and adds the ID to `_consumed_preview_ids` while holding one
lock. Consumption occurs before session creation and is never rolled back.

MARKET calls `request_live_quote` again and checks USD 1,000. LIMIT recomputes
from the entered limit without requesting a quote. No method retries a broker
submission automatically.

- [ ] **Step 4: Run submission and full broker tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_ibkr_order_execution tests.test_ibkr_broker tests.test_broker_contracts -v
```

- [ ] **Step 5: Commit Task 3**

```powershell
git add src/private_quant/broker/ibkr_orders.py tests/test_ibkr_order_execution.py
git commit -m "feat: add guarded paper order submission"
```

---

### Task 4: Add the official IBKR order session adapter

**Files:**
- Create: `src/private_quant/broker/ibkr_order_session.py`
- Modify: `src/private_quant/broker/ibkr_orders.py`
- Create: `tests/test_ibkr_order_session.py`

**Interfaces:**
- Consumes: `IbkrOrderSession`, `ResolvedContract`, `LiveQuote`, `OrderUpdate`, and `OrderIntent`.
- Produces `create_official_ibkr_order_session()` as the production session factory.

- [ ] **Step 1: Write failing callback and API-surface tests**

Use patched fake `ibapi.client`, `ibapi.wrapper`, `ibapi.contract`, and
`ibapi.order` modules. Tests must prove:

```python
def test_contract_request_is_stk_smart_usd():
    session.resolve_contracts("AAPL", timeout=0.01)
    requested = session.reqContractDetails.call_args.args[1]
    self.assertEqual(requested.symbol, "AAPL")
    self.assertEqual(requested.secType, "STK")
    self.assertEqual(requested.exchange, "SMART")
    self.assertEqual(requested.currency, "USD")

def test_live_snapshot_uses_only_bid_ask_and_market_data_type_one():
    session.marketDataType(9102, 1)
    session.tickPrice(9102, 1, 99.0, object())
    session.tickPrice(9102, 2, 100.0, object())
    session.tickSnapshotEnd(9102)
    self.assertEqual(session.live_quote.bid, Decimal("99.0"))
    self.assertEqual(session.live_quote.ask, Decimal("100.0"))

def test_managed_accounts_retains_count_not_identifiers():
    sentinel = "DU1234567"
    session.managedAccounts(sentinel)
    self.assertEqual(session.managed_account_count, 1)
    self.assertNotIn(sentinel, repr(vars(session)))
```

Add tests for two comma-separated account values producing count `2` without
retention, `nextValidId` storage without `reqIds`, `placeOrder` field mapping,
`orderRef`, `transmit=True`, MARKET without limit price, LIMIT with limit price,
order status/rejection/cancel/filled mapping, cleanup cancellation of only a
pending market-data request, disabled raw `ibapi` logging, and fixed import
failure guidance.

Add an AST/source test asserting the module contains no calls to `reqIds`,
`cancelOrder`, `reqGlobalCancel`, what-if, replace, or automatic submission
loop and exactly one wrapper around `placeOrder`.

- [ ] **Step 2: Run official-session tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_ibkr_order_session -v
```

Expected: import failure because the official session module does not exist.

- [ ] **Step 3: Implement the lazy official session**

Use request IDs `9101` for contract details and `9102` for market data. Import
the four official modules lazily inside the factory and disable `ibapi` logging
before creating a client.

The adapter request calls are exactly:

```python
self.reqContractDetails(9101, contract)
self.reqMarketDataType(1)
self.reqMktData(9102, contract, "", True, False, [])
self.cancelMktData(9102)
self.placeOrder(order_id, contract, order)
```

Callbacks retain only sanitized values. `managedAccounts` computes a distinct
count in a local expression and discards the callback string. `error` converts
known order error codes `201` and `202` to sanitized rejected/cancelled updates
and discards every text/JSON argument. Cleanup disconnects and joins the reader
thread without logging raw exceptions.

- [ ] **Step 4: Run official adapter and broker suites and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_ibkr_order_session tests.test_ibkr_order_execution tests.test_ibkr_broker -v
```

- [ ] **Step 5: Commit Task 4**

```powershell
git add src/private_quant/broker/ibkr_order_session.py src/private_quant/broker/ibkr_orders.py tests/test_ibkr_order_session.py
git commit -m "feat: add official IBKR paper order adapter"
```

---

### Task 5: Add the locked Streamlit Paper Trading ticket

**Files:**
- Modify: `src/private_quant/app/broker_config.py`
- Create: `src/private_quant/app/paper_trading.py`
- Modify: `src/private_quant/broker/__init__.py`
- Modify: `tests/test_broker_config.py`
- Create: `tests/test_paper_trading_app.py`

**Interfaces:**
- Produces `build_paper_order_executor(configuration) -> PaperOrderExecutionProvider` with `submission_enabled=False` fixed in production.
- Produces UI helpers `make_order_intent`, `preview_error_message`, `intent_signature`, and `render_order_preview`.
- Consumes only public order models, errors, and protocol in the UI.

- [ ] **Step 1: Discover the installed Streamlit reference instructions**

Run:

```powershell
.\.venv\Scripts\python.exe C:\Users\Administrator\.agents\skills\developing-with-streamlit\scripts\discover.py --project-dir "C:\Users\Administrator\OneDrive\文档\ChatGPT\private-quant-lab"
```

Read the returned bundled `SKILL.md` and only its form, session-state, layout,
and testing references before editing the page.

- [ ] **Step 2: Write failing configuration and AppTest tests**

Configuration tests inject a fake executor constructor and assert the exact
paper endpoint plus `submission_enabled=False`. Unsafe configuration must fail
before constructing the executor.

App tests assert:

```python
def test_page_defaults_to_one_and_keeps_submit_disabled():
    app = AppTest.from_file(PAGE_PATH).run(timeout=20)
    self.assertEqual(app.number_input(key="quantity").value, 1)
    self.assertTrue(app.button(key="submit_order").disabled)
    self.assertIn("PAPER", app.warning[0].value)
    self.assertEqual(len(app.exception), 0)

def test_limit_selection_shows_limit_price():
    app = AppTest.from_file(PAGE_PATH).run(timeout=20)
    app.selectbox(key="order_type").select("LIMIT").run(timeout=20)
    self.assertEqual(len(app.number_input(key="limit_price")), 1)

def test_preview_uses_injected_executor_and_renders_notional():
    preview = make_preview(Decimal("100"), Decimal("100"))
    rendered = render_order_preview(preview)
    self.assertEqual(rendered["Estimated notional"], "USD 100.00")
```

Also test BUY/SELL and MARKET/LIMIT intent construction, fixed messages for
each typed order error, no reflected sentinel error/account text, preview
clearing when the intent signature changes, and no submit callback invocation
from the locked page.

- [ ] **Step 3: Run configuration and UI tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_broker_config tests.test_paper_trading_app -v
```

Expected: missing builder/page failures.

- [ ] **Step 4: Implement the production lock and Streamlit page**

The production builder is explicit:

```python
return IbkrPaperOrderExecutor(
    mode=configuration.mode,
    host=configuration.host,
    port=configuration.port,
    client_id=configuration.client_id,
    session_factory=create_official_ibkr_order_session,
    submission_enabled=False,
)
```

Store the executor, intent signature, and current preview in
`st.session_state`. Preview is the only enabled action. Submit is rendered as:

```python
st.button(
    "Submit",
    key="submit_order",
    type="primary",
    disabled=True,
    help="Disabled while TWS Read-Only API remains enabled.",
)
```

Do not call `submit_order` anywhere in the Streamlit module in this phase.
Display a visible PAPER warning and a true-market-order slippage warning.

- [ ] **Step 5: Run UI, broker, and full tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_broker_config tests.test_paper_trading_app tests.test_ibkr_order_execution -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

- [ ] **Step 6: Commit Task 5**

```powershell
git add src/private_quant/app/broker_config.py src/private_quant/app/paper_trading.py src/private_quant/broker/__init__.py tests/test_broker_config.py tests/test_paper_trading_app.py
git commit -m "feat: add locked paper trading ticket"
```

---

### Task 6: Document, browser-test, verify, and create the pull request

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-26-ibkr-paper-order-execution-design.md`
- Modify: `docs/superpowers/plans/2026-08-26-ibkr-paper-order-execution.md`

**Interfaces:**
- Documents how to launch the page without changing `.env` or Read-Only API.
- Produces the final verification record and pull request.

- [ ] **Step 1: Update documentation**

Document that Phase 2 makes a new IBKR snapshot request and accepts only live
market-data type `1`, while the callback provides no timestamp and quote age
is not independently verified. MARKET Preview is capped at USD 950, all
Submit revalidation is capped at USD 1,000, and Submit is intentionally
locked. State clearly that users must not disable TWS Read-Only for this phase.

Windows launch command:

```powershell
Set-Location "C:\path\to\private-quant-lab"
.\.venv\Scripts\Activate.ps1
python -m streamlit run src/private_quant/app/paper_trading.py
```

- [ ] **Step 2: Run fresh complete verification**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

Run source checks proving the Streamlit page never calls `submit_order`, the
production builder contains only `submission_enabled=False`, and order source
contains no cancel, replace, what-if, `reqIds`, automatic retry, or live-mode
path.

- [ ] **Step 3: Browser-test without Preview or Submit transmission**

Start Streamlit on an unused localhost port. Verify in the browser:

- title and PAPER warning render;
- default quantity is `1`;
- BUY/SELL and MARKET/LIMIT controls work;
- LIMIT price appears only for LIMIT;
- Submit remains disabled before and after ticket edits;
- the Read-Only explanation is visible;
- there are no browser exceptions; and
- no Preview click or TWS order call is made during this verification.

- [ ] **Step 4: Perform final code review**

Review the complete diff against every Global Constraint. Resolve all Critical
or Important findings with a failing regression test first, then rerun the
complete verification commands.

- [ ] **Step 5: Commit documentation and verification updates**

```powershell
git add README.md docs/superpowers/specs/2026-08-26-ibkr-paper-order-execution-design.md docs/superpowers/plans/2026-08-26-ibkr-paper-order-execution.md
git commit -m "docs: explain locked paper order workflow"
```

- [ ] **Step 6: Push and create a PR targeting main**

```powershell
git push -u origin codex/ibkr-paper-order-execution
$prBody = @'
## Summary
- Add a separate PAPER-only order Preview and execution abstraction.
- Keep production Submit hard-disabled while TWS Read-Only remains enabled.
- Validate new IBKR live snapshot responses and USD 950/1,000 MARKET safeguards; document that quote age is unavailable.
- Add mocked order submission, duplicate prevention, and status tests.

## Safety verification
- No real TWS placeOrder call was made.
- No live-mode, automatic execution, cancel, replace, what-if, or reqIds path exists.
- No account ID, credential, .env value, or secret was captured or committed.
'@
gh pr create --base main --head codex/ibkr-paper-order-execution --title "Add locked IBKR paper order workflow" --body $prBody
```

The PR body must state that no real TWS `placeOrder` call was made, TWS
Read-Only remained enabled, the production Submit path is locked, and no
account ID, credential, `.env` value, or secret was captured or committed.
