# IBKR Manual PAPER Submit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable one manually confirmed IBKR PAPER order Submit while requiring a fail-closed local flag, an unchecked-by-default session confirmation, and every existing Preview, endpoint, quote, notional, and privacy control.

**Architecture:** Keep the framework-independent `PaperOrderExecutionProvider` and existing guarded IBKR executor. Extend the sanitized app configuration with one fail-closed boolean and pass it explicitly into the production executor. Add pure Streamlit-layer eligibility and submit helpers, while the executor remains the independent authority for Preview issuance, expiry, duplicate prevention, endpoint validation, re-quote, notional, account scope, and order status mapping.

**Tech Stack:** Python 3.11+, standard-library immutable dataclasses/`datetime`/`Decimal`, separately installed official IBKR TWS Python API, python-dotenv, Streamlit 1.48+, and `unittest` with Streamlit `AppTest`.

## Global Constraints

- Start from latest `origin/main` on `codex/ibkr-paper-manual-submit`.
- Use only `BROKER_PROVIDER=ibkr`, `BROKER_MODE=paper`, `BROKER_HOST=127.0.0.1`, `BROKER_PORT=7497`, and `BROKER_CLIENT_ID=10`.
- Add `IBKR_PAPER_SUBMIT_ENABLED=false` as the fail-closed default.
- Only a trimmed, case-insensitive exact value of `true` enables the local gate.
- Missing, blank, `false`, `1`, `yes`, `on`, malformed, and every other value remain disabled.
- Require the unchecked-by-default, session-only confirmation `I intentionally disabled Read-Only API in TWS PAPER for this session.`
- State that confirmation is operator-provided, not automatic detection of the TWS Read-Only setting.
- Submit requires both gates plus an exact, matching, unexpired, unconsumed Preview.
- Keep the USD 950 MARKET Preview safety buffer and USD 1,000 Submit hard limit.
- MARKET Submit makes a new IBKR snapshot request, requires live market-data type `1`, and uses BUY ask or SELL bid; quote age is unavailable and not independently verified.
- LIMIT Submit uses the entered limit price for notional revalidation.
- Reject delayed, frozen, missing, non-positive, NaN, and infinite MARKET prices.
- Never fall back to Tiingo, cached values, prior closes, or guessed prices.
- Retain exactly-one-account validation without storing, logging, returning, or rendering account IDs.
- Add no live mode, live endpoint, live enable flag, automatic execution, cancel, replace, modify, batch, what-if, `reqIds`, or retry path.
- Do not read, print, modify, or commit the real `.env`, API keys, credentials, account IDs, raw broker errors, or advanced rejection payloads.
- Do not connect to TWS or make any real `placeOrder` call during implementation, automated tests, browser tests, or PR preparation.

---

### Task 1: Add the fail-closed local Submit configuration gate

**Files:**
- Modify: `src/private_quant/app/broker_config.py`
- Modify: `.env.example`
- Modify: `tests/test_broker_config.py`

**Interfaces:**
- Produces: `BrokerConfiguration.paper_submit_enabled: bool = False`
- Produces: `build_paper_order_executor(configuration: BrokerConfiguration, *, session_factory: IbkrOrderSessionFactory = create_official_ibkr_order_session) -> PaperOrderExecutionProvider` passing the parsed boolean as `submission_enabled`
- Preserves: exact PAPER endpoint validation and the read-only `build_broker_provider` behavior

- [ ] **Step 1: Write failing parser and builder tests**

Add literal, table-driven cases to `tests/test_broker_config.py`:

```python
def make_external_preview() -> OrderPreview:
    created_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    return OrderPreview(
        preview_id="external-preview",
        intent=OrderIntent(
            "AAPL", OrderSide.BUY, OrderType.LIMIT,
            limit_price=Decimal("100"),
        ),
        estimated_unit_price=Decimal("100"),
        estimated_notional=Decimal("100"),
        quote_source=QuoteSource.USER_LIMIT,
        created_at=created_at,
        expires_at=created_at + timedelta(seconds=60),
    )


def test_paper_submit_flag_is_fail_closed(self) -> None:
    cases = {
        None: False,
        "": False,
        "   ": False,
        "false": False,
        "1": False,
        "yes": False,
        "on": False,
        "truthy": False,
        "true false": False,
        "true": True,
        " TRUE ": True,
        "TrUe": True,
    }

    for raw_value, expected in cases.items():
        with self.subTest(raw_value=raw_value):
            contents = VALID_CONFIGURATION
            if raw_value is not None:
                contents += f"IBKR_PAPER_SUBMIT_ENABLED={raw_value}\n"
            configuration = load_broker_configuration(
                self.write_env(contents), environment={}
            )
            self.assertIs(configuration.paper_submit_enabled, expected)


def test_process_environment_can_only_enable_with_exact_true(self) -> None:
    configuration = load_broker_configuration(
        self.write_env(
            VALID_CONFIGURATION + "IBKR_PAPER_SUBMIT_ENABLED=false\n"
        ),
        environment={"IBKR_PAPER_SUBMIT_ENABLED": "  TRUE  "},
    )
    self.assertTrue(configuration.paper_submit_enabled)


def test_enabled_builder_reaches_preview_validation_not_disabled_gate(self) -> None:
    configuration = BrokerConfiguration(
        provider_name="ibkr",
        mode="paper",
        host="127.0.0.1",
        port=7497,
        client_id=10,
        paper_submit_enabled=True,
    )
    executor = build_paper_order_executor(
        configuration, session_factory=lambda: object()
    )

    with self.assertRaises(OrderPreviewRequiredError):
        executor.submit_order(make_external_preview())


def test_disabled_builder_still_fails_before_session_creation(self) -> None:
    session_created = False

    def create_session():
        nonlocal session_created
        session_created = True
        return object()

    configuration = BrokerConfiguration(
        provider_name="ibkr",
        mode="paper",
        host="127.0.0.1",
        port=7497,
        client_id=10,
        paper_submit_enabled=False,
    )
    executor = build_paper_order_executor(
        configuration, session_factory=create_session
    )

    with self.assertRaises(OrderSubmissionDisabledError):
        executor.submit_order(make_external_preview())
    self.assertFalse(session_created)
```

Add a regression loop that manually constructs configurations with
`paper_submit_enabled=True` but unsafe provider/mode/host/port/client ID. Each
must raise before the injected session factory is called. This proves no live
endpoint/configuration can submit.

- [ ] **Step 2: Run configuration tests and verify RED**

Run:

```powershell
$env:PYTHONUTF8='1'
python -m unittest tests.test_broker_config -v
```

Expected: failures because `paper_submit_enabled` does not exist and the
production builder still hard-codes `False`.

- [ ] **Step 3: Implement exact fail-closed parsing**

In `broker_config.py`, extend the list of broker environment names and the
immutable configuration:

```python
_PAPER_SUBMIT_NAME = "IBKR_PAPER_SUBMIT_ENABLED"
_BROKER_NAMES = (
    "BROKER_PROVIDER",
    "BROKER_MODE",
    "BROKER_HOST",
    "BROKER_PORT",
    "BROKER_CLIENT_ID",
    _PAPER_SUBMIT_NAME,
)


@dataclass(frozen=True, slots=True)
class BrokerConfiguration:
    provider_name: str
    mode: str
    host: str
    port: int
    client_id: int
    paper_submit_enabled: bool = False
```

Parse without truthy aliases:

```python
paper_submit_enabled = (
    str(values.get(_PAPER_SUBMIT_NAME) or "").strip().lower() == "true"
)
```

Validate the five connection fields independently so either boolean value is
allowed only after exact endpoint validation:

```python
if (
    configuration.provider_name != "ibkr"
    or configuration.mode != "paper"
    or configuration.host != "127.0.0.1"
    or configuration.port != 7497
    or configuration.client_id != 10
):
    raise BrokerConfigurationError(_SAFE_CONFIGURATION_MESSAGE)
```

Pass the parsed boolean explicitly:

```python
return IbkrPaperOrderExecutor(
    mode=configuration.mode,
    host=configuration.host,
    port=configuration.port,
    client_id=configuration.client_id,
    session_factory=session_factory,
    submission_enabled=configuration.paper_submit_enabled,
)
```

Do not read the environment inside `IbkrPaperOrderExecutor`.

- [ ] **Step 4: Add the disabled example setting**

Append only this non-secret line to `.env.example`:

```text
IBKR_PAPER_SUBMIT_ENABLED=false
```

Do not open, read, or alter `.env`.

- [ ] **Step 5: Run configuration and existing executor safety tests**

Run:

```powershell
$env:PYTHONUTF8='1'
python -m unittest tests.test_broker_config tests.test_ibkr_order_execution -v
```

Expected: all pass; unsafe configurations still fail before session creation,
and a disabled production executor still fails before connection.

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- .env.example src/private_quant/app/broker_config.py tests/test_broker_config.py
git commit -m "feat: add fail-closed paper submit flag"
```

---

### Task 2: Add pure Submit eligibility and sanitized result helpers

**Files:**
- Modify: `src/private_quant/app/paper_trading.py`
- Modify: `tests/test_paper_trading_app.py`

**Interfaces:**
- Produces: `preview_is_submittable(preview, intent, *, now, configuration_enabled, operator_confirmed, consumed) -> bool`
- Produces: `submit_paper_order(executor, preview) -> OrderResult`
- Produces: `order_submit_error_message(error) -> str`
- Produces: `render_order_result(result) -> None`
- Produces: `submit_help_text(preview, intent, *, now, configuration_enabled, operator_confirmed, consumed) -> str`
- Produces: immutable app-layer `SubmitAttemptOutcome(consumed, result, error_message)`
- Produces: `attempt_paper_submit(executor, preview, intent, *, now, configuration_enabled, operator_confirmed, consumed) -> SubmitAttemptOutcome`
- Preserves: framework-independent executor and immutable models

- [ ] **Step 1: Write failing pure eligibility tests**

Add literal cases using an aware UTC time and immutable real models:

```python
def make_preview(
    intent: OrderIntent, *, created_at: datetime
) -> OrderPreview:
    return OrderPreview(
        preview_id="preview-1",
        intent=intent,
        estimated_unit_price=Decimal("100"),
        estimated_notional=Decimal("100"),
        quote_source=QuoteSource.IBKR_LIVE_ASK,
        created_at=created_at,
        expires_at=created_at + timedelta(seconds=60),
    )


def test_submit_eligibility_requires_every_gate(self) -> None:
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    intent = OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET, 1)
    preview = make_preview(intent, created_at=now)

    cases = (
        ({"configuration_enabled": False}, False),
        ({"operator_confirmed": False}, False),
        ({"preview": None}, False),
        ({"intent": replace(intent, side=OrderSide.SELL)}, False),
        ({"now": preview.expires_at}, False),
        ({"consumed": True}, False),
        ({}, True),
    )

    defaults = {
        "preview": preview,
        "intent": intent,
        "now": now,
        "configuration_enabled": True,
        "operator_confirmed": True,
        "consumed": False,
    }
    for overrides, expected in cases:
        values = defaults | overrides
        self.assertIs(preview_is_submittable(**values), expected)
```

Also assert a naive `now` fails closed rather than being accepted or causing a
raw exception to reach the UI.

Add table-driven literal assertions for `submit_help_text`: local gate
disabled, operator confirmation missing, Preview missing/changed, Preview
expired, Preview consumed, and Ready. None may include a raw configuration
value.

- [ ] **Step 2: Write failing Submit invocation and sanitized rendering tests**

Use a fake executor implementing the real protocol boundary:

```python
class FakeExecutor:
    def __init__(self, result: OrderResult) -> None:
        self.result = result
        self.calls: list[OrderPreview] = []

    def submit_order(self, preview: OrderPreview) -> OrderResult:
        self.calls.append(preview)
        return self.result


def test_submit_helper_calls_executor_once_and_returns_result(self) -> None:
    created_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    preview = make_preview(
        OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET, 1),
        created_at=created_at,
    )
    expected = OrderResult(
        preview_id=preview.preview_id,
        broker_order_id=7001,
        status=OrderStatus.SUBMITTED,
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("1"),
        average_fill_price=None,
    )
    executor = FakeExecutor(expected)

    actual = submit_paper_order(executor, preview)

    self.assertIs(actual, expected)
    self.assertEqual(executor.calls, [preview])
```

Render literal `FILLED`, `CANCELLED`, `REJECTED`, `INACTIVE`, and `UNKNOWN`
results through `AppTest.from_string`. Assert only normalized status, broker
order ID, filled, remaining, and average fill are shown. Include sentinel raw
error/account strings in the test process and assert they are absent from all
rendered values.

Test every typed Submit error through `order_submit_error_message`; each must
return fixed copy and must not contain the exception's sentinel detail.

Test `attempt_paper_submit` with a real fake protocol implementation:

- expired Preview returns a fixed error, keeps `consumed=False`, and makes zero
  executor calls;
- either false gate returns a fixed error and makes zero executor calls;
- eligible success makes exactly one call and returns `consumed=True` with the
  exact `OrderResult`; and
- eligible executor failure makes exactly one call and returns
  `consumed=True`, `result=None`, and fixed sanitized error text.

- [ ] **Step 3: Run helper tests and verify RED**

Run:

```powershell
$env:PYTHONUTF8='1'
python -m unittest tests.test_paper_trading_app -v
```

Expected: import/name failures for the new helpers.

- [ ] **Step 4: Implement minimal pure helpers**

Implement eligibility without Streamlit state access:

```python
def preview_is_submittable(
    preview: OrderPreview | None,
    intent: OrderIntent,
    *,
    now: datetime,
    configuration_enabled: bool,
    operator_confirmed: bool,
    consumed: bool,
) -> bool:
    if now.tzinfo is None or now.utcoffset() is None:
        return False
    return (
        configuration_enabled
        and operator_confirmed
        and not consumed
        and preview is not None
        and preview.intent == intent
        and now < preview.expires_at
    )


def submit_paper_order(
    executor: PaperOrderExecutionProvider,
    preview: OrderPreview,
) -> OrderResult:
    return executor.submit_order(preview)
```

Add one immutable result for the click boundary:

```python
@dataclass(frozen=True, slots=True)
class SubmitAttemptOutcome:
    consumed: bool
    result: OrderResult | None
    error_message: str | None
```

Implement the guarded call once:

```python
def attempt_paper_submit(
    executor: PaperOrderExecutionProvider,
    preview: OrderPreview | None,
    intent: OrderIntent,
    *,
    now: datetime,
    configuration_enabled: bool,
    operator_confirmed: bool,
    consumed: bool,
) -> SubmitAttemptOutcome:
    if not preview_is_submittable(
        preview,
        intent,
        now=now,
        configuration_enabled=configuration_enabled,
        operator_confirmed=operator_confirmed,
        consumed=consumed,
    ):
        return SubmitAttemptOutcome(
            consumed=consumed,
            result=None,
            error_message=submit_help_text(
                preview,
                intent,
                now=now,
                configuration_enabled=configuration_enabled,
                operator_confirmed=operator_confirmed,
                consumed=consumed,
            ),
        )
    if preview is None:
        return SubmitAttemptOutcome(
            consumed=consumed,
            result=None,
            error_message="Preview this exact ticket before Submit.",
        )
    try:
        result = submit_paper_order(executor, preview)
    except Exception as error:
        return SubmitAttemptOutcome(
            consumed=True,
            result=None,
            error_message=order_submit_error_message(error),
        )
    return SubmitAttemptOutcome(
        consumed=True,
        result=result,
        error_message=None,
    )
```

Map typed errors with fixed messages. Do not interpolate `str(error)`. Include
`OrderSubmissionDisabledError`, `OrderPreviewRequiredError`,
`OrderPreviewExpiredError`, `DuplicateOrderSubmissionError`,
`OrderQuoteUnavailableError`, `OrderNotionalLimitError`,
`OrderConnectionError`, `OrderStatusTimeoutError`,
`OfficialIbapiUnavailableError`, and a generic safe fallback.

Render only sanitized model fields:

```python
def render_order_result(result: OrderResult) -> None:
    st.success("PAPER order response received.")
    with st.container(horizontal=True):
        st.metric("Status", result.status.value.replace("_", " ").title(), border=True)
        st.metric("Broker order ID", str(result.broker_order_id), border=True)
        st.metric("Filled", f"{result.filled_quantity:,}", border=True)
        st.metric("Remaining", f"{result.remaining_quantity:,}", border=True)
        st.metric(
            "Average fill price",
            _format_money(result.average_fill_price)
            if result.average_fill_price is not None
            else "N/A",
            border=True,
        )
```

Implement `submit_help_text` with the same ordered conditions as
`preview_is_submittable`. Return only these fixed strings:

```python
def submit_help_text(
    preview: OrderPreview | None,
    intent: OrderIntent,
    *,
    now: datetime,
    configuration_enabled: bool,
    operator_confirmed: bool,
    consumed: bool,
) -> str:
    if not configuration_enabled:
        return "Local PAPER Submit gate is disabled. Enable it and Preview again."
    if not operator_confirmed:
        return "Confirm that you intentionally disabled TWS Read-Only API."
    if preview is None or preview.intent != intent:
        return "Preview this exact ticket before Submit."
    if now.tzinfo is None or now.utcoffset() is None or now >= preview.expires_at:
        return "This Preview has expired. Preview the ticket again."
    if consumed:
        return "This Preview has already been consumed. Preview again."
    return "Ready for one manual IBKR PAPER Submit."
```

- [ ] **Step 5: Run helper and existing order tests**

Run:

```powershell
$env:PYTHONUTF8='1'
python -m unittest tests.test_paper_trading_app tests.test_ibkr_order_execution tests.test_ibkr_order_session -v
```

Expected: all pass with no TWS connection.

- [ ] **Step 6: Commit Task 2**

```powershell
git add -- src/private_quant/app/paper_trading.py tests/test_paper_trading_app.py
git commit -m "feat: add manual paper submit eligibility"
```

---

### Task 3: Wire both gates into the Streamlit Submit workflow

**Files:**
- Modify: `src/private_quant/app/paper_trading.py`
- Modify: `tests/test_paper_trading_app.py`

**Interfaces:**
- Changes: `load_order_preview(intent: OrderIntent, *, configuration_loader: Callable[[], BrokerConfiguration] = load_broker_configuration, executor_builder: Callable[[BrokerConfiguration], PaperOrderExecutionProvider] = build_paper_order_executor) -> tuple[PaperOrderExecutionProvider, OrderPreview, bool]`
- Consumes: `BrokerConfiguration.paper_submit_enabled`
- Consumes: pure eligibility, submit, error, and render helpers from Task 2
- Produces: manual Submit UI requiring both gates and one valid Preview

- [ ] **Step 1: Write failing Preview-context and initial-state tests**

Extend the injected `load_order_preview` test so the returned tuple contains
the safe gate boolean from the exact configuration passed to the builder.

Use `AppTest.from_file` to assert on a new session:

```python
self.assertFalse(
    app.checkbox(key="paper_order_read_only_confirmation").value
)
self.assertEqual(
    app.checkbox(key="paper_order_read_only_confirmation").label,
    "I intentionally disabled Read-Only API in TWS PAPER for this session.",
)
self.assertTrue(app.button(key="paper_order_submit").disabled)
```

Assert visible copy contains both:

```text
Operator confirmation only — the app does not automatically detect the TWS Read-Only setting.
IBKR_PAPER_SUBMIT_ENABLED must be true before creating a Submit-capable Preview.
```

- [ ] **Step 2: Write failing state-transition tests**

Keep these tests at the app helper boundary with a fake executor and injected
clock so they cannot contact TWS:

- configuration false + confirmation true stays disabled;
- configuration true + confirmation false stays disabled;
- both true + exact Preview enables;
- changed ticket clears Preview/executor/gate/result and resets confirmation;
- expired Preview is rejected on the click-time recheck without calling the
  fake executor;
- consumed Preview cannot call the executor;
- successful Submit calls once, stores the sanitized result, marks consumed,
  and resets confirmation;
- executor failure stores only fixed safe copy, marks consumed, and resets
  confirmation; and
- a second click cannot call the executor again.

Exercise `attempt_paper_submit` rather than asserting on a mock widget. It
accepts state primitives and returns the new consumed/result/error state after
invoking the real protocol method at most once.

- [ ] **Step 3: Run Streamlit tests and verify RED**

Run:

```powershell
$env:PYTHONUTF8='1'
python -m unittest tests.test_paper_trading_app -v
```

Expected: failures because the checkbox, gate state, and Submit workflow are
not wired.

- [ ] **Step 4: Add explicit session-state keys and reset behavior**

Add private keys:

```python
_CONFIGURATION_GATE_STATE_KEY = "_paper_order_submit_configuration_enabled"
_CONSUMED_STATE_KEY = "_paper_order_preview_consumed"
_RESULT_STATE_KEY = "_paper_order_result"
_ERROR_STATE_KEY = "_paper_order_submit_error"
_CONFIRMATION_WIDGET_KEY = "paper_order_read_only_confirmation"
_RESET_CONFIRMATION_STATE_KEY = "_paper_order_reset_confirmation"
```

Initialize the checkbox by passing `value=False`; do not seed it from an
environment value. Build the normalized intent and run the stale-ticket reset
before instantiating the confirmation checkbox. The reset clears all
Preview-related state and assigns `False` to the confirmation key while it is
still safe to mutate.

At the top of `main`, before the checkbox is instantiated, consume a pending
post-Submit reset:

```python
if st.session_state.pop(_RESET_CONFIRMATION_STATE_KEY, False):
    st.session_state[_CONFIRMATION_WIDGET_KEY] = False
```

`load_order_preview` returns:

```python
return (
    executor,
    executor.preview_order(intent),
    configuration.paper_submit_enabled,
)
```

After a successful Preview, store the three values, set consumed false, and
clear previous result/error. If the flag is disabled, Preview still succeeds
but Submit stays disabled.

- [ ] **Step 5: Render both gates and enabled state**

Keep the prominent warning:

```text
PAPER ONLY — manual Submit can transmit an order to your IBKR Paper account. No live trading or automatic execution is available.
```

Add the exact confirmation checkbox and adjacent fixed caption explaining it
is not automatic detection. Display only Enabled/Disabled and
Confirmed/Required gate labels.

Compute eligibility using `datetime.now(timezone.utc)` and the pure helper.
Render the button with:

```python
submit_clicked = st.button(
    "Submit PAPER order",
    disabled=not can_submit,
    icon=":material/send:",
    key="paper_order_submit",
    help=submit_help_text(
        preview,
        intent,
        now=now,
        configuration_enabled=configuration_enabled,
        operator_confirmed=operator_confirmed,
        consumed=consumed,
    ),
)
```

Do not add any Submit call outside the guarded `if submit_clicked` branch.

- [ ] **Step 6: Implement click-time revalidation and one-shot state transition**

On the click-triggered rerun, call `attempt_paper_submit` with a new aware UTC
timestamp. Store only its immutable consumed/result/error fields. Then schedule
the session confirmation reset and rerun:

```python
outcome = attempt_paper_submit(
    executor,
    preview,
    intent,
    now=datetime.now(timezone.utc),
    configuration_enabled=configuration_enabled,
    operator_confirmed=operator_confirmed,
    consumed=consumed,
)
st.session_state[_CONSUMED_STATE_KEY] = outcome.consumed
if outcome.result is not None:
    st.session_state[_RESULT_STATE_KEY] = outcome.result
    st.session_state.pop(_ERROR_STATE_KEY, None)
else:
    st.session_state.pop(_RESULT_STATE_KEY, None)
    st.session_state[_ERROR_STATE_KEY] = outcome.error_message
st.session_state[_RESET_CONFIRMATION_STATE_KEY] = True
st.rerun()
```

Do not assign the checkbox widget key after it has been instantiated in the
same run. The pending-reset flag is the only post-Submit reset mechanism.

Render stored results only through `render_order_result`; render stored errors
only from fixed safe text. Leave the Preview marked consumed so Submit cannot
re-enable without a new Preview.

- [ ] **Step 7: Run UI, configuration, and broker tests**

Run:

```powershell
$env:PYTHONUTF8='1'
python -m unittest tests.test_paper_trading_app tests.test_broker_config tests.test_ibkr_order_execution tests.test_ibkr_order_session -v
```

Expected: all pass, no network/TWS activity, Submit enabled only for the exact
two-gate state.

- [ ] **Step 8: Commit Task 3**

```powershell
git add -- src/private_quant/app/paper_trading.py tests/test_paper_trading_app.py
git commit -m "feat: enable confirmed manual paper submit"
```

---

### Task 4: Document operator setup and verify the PR safely

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-26-ibkr-paper-manual-submit-design.md` only if implementation revealed a factual mismatch
- Modify: `docs/superpowers/plans/2026-08-26-ibkr-paper-manual-submit.md` only if implementation revealed a factual mismatch

**Interfaces:**
- Documents: fail-closed flag, two gates, manual-only scope, quote-age limitation, and Windows launch flow
- Produces: verified branch and PR targeting `main`

- [ ] **Step 1: Update README without touching `.env`**

Document:

- `.env.example` defaults `IBKR_PAPER_SUBMIT_ENABLED=false`;
- only exact normalized `true` enables the local gate;
- the operator must intentionally disable TWS Read-Only API and check the
  session-only confirmation;
- the app cannot automatically detect the Read-Only setting;
- changing the flag requires a new Preview;
- Submit transmits only to the exact PAPER endpoint;
- MARKET uses a new IBKR live type-1 snapshot but cannot verify bid/ask age;
- USD 950 Preview buffer and USD 1,000 Submit hard limit remain distinct;
- no live, automatic, cancel, replace, or batch functionality exists; and
- users must keep the flag false except during an intentional manual Paper
  session.

Use the existing guarded `.env` copy command. Do not add instructions that
overwrite `.env`.

- [ ] **Step 2: Run a source safety audit**

Run AST-based existing tests and inspect only tracked source:

```powershell
$env:PYTHONUTF8='1'
python -m unittest tests.test_ibkr_order_session.IbkrOrderSessionSourceSafetyTests tests.test_ibkr_broker.IbkrSourceSafetyTests tests.test_paper_trading_app -v
git diff --check
git ls-files .env
```

Expected: source safety tests pass, diff check passes, and `.env` is not
tracked. Confirm the app has one guarded `submit_order` invocation and the
official adapter still has exactly one `placeOrder` construction path with no
cancel/replace/what-if/`reqIds` additions.

- [ ] **Step 3: Run the complete fresh verification**

Run:

```powershell
$env:PYTHONUTF8='1'
python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m pip check
git diff --check
git status --short
```

Expected: zero test failures, compile succeeds, no broken requirements, clean
diff, and only intended tracked files changed.

- [ ] **Step 4: Browser-test without Preview or Submit**

Start the page on an unused localhost port:

```powershell
python -m streamlit run src/private_quant/app/paper_trading.py --server.headless true --server.port 8513 --browser.gatherUsageStats false
```

In the browser verify:

- prominent PAPER ONLY warning;
- operator checkbox unchecked;
- copy says operator confirmation is not automatic detection;
- Submit disabled;
- quantity defaults to `1`;
- MARKET/LIMIT controls render;
- USD 950 and USD 1,000 limits remain distinct; and
- no browser console error.

Do not click Preview or Submit. This prevents any TWS connection during browser
verification.

- [ ] **Step 5: Request independent code review**

Review the branch diff from `origin/main` for:

- fail-closed parsing;
- both gates required;
- click-time expiry and consumed checks;
- fixed sanitized UI/error output;
- unsafe endpoint rejection;
- no account/raw payload leak;
- no live/automation/cancel/replace/batch path; and
- no real TWS/order activity in tests.

Fix every Critical or Important finding, rerun affected tests, and repeat
review until no such findings remain.

- [ ] **Step 6: Commit documentation**

```powershell
git add -- README.md docs/superpowers/specs/2026-08-26-ibkr-paper-manual-submit-design.md docs/superpowers/plans/2026-08-26-ibkr-paper-manual-submit.md
git commit -m "docs: explain manual paper submit controls"
```

- [ ] **Step 7: Rerun the full suite on the committed tree**

Run the Step 3 commands again after the final commit. Do not rely on an earlier
run.

- [ ] **Step 8: Push and create the PR**

```powershell
git push -u origin codex/ibkr-paper-manual-submit
gh pr create --base main --head codex/ibkr-paper-manual-submit
```

The PR description must state:

- both gates and fail-closed parsing;
- exact PAPER endpoint;
- manual-only behavior;
- Preview and hard-limit controls;
- quote-age limitation;
- complete mocked test count;
- browser test did not click Preview or Submit; and
- no real TWS connection or `placeOrder` call was made.

Stop after the PR is open. Do not conduct a live Paper order test.
