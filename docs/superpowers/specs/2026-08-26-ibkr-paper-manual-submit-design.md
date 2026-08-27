# IBKR Manual PAPER Submit Design

**Date:** 2026-08-26  
**Status:** Approved for implementation planning  
**Scope:** Manual PAPER order Submit with two explicit local safety gates

## Goal

Enable a human operator to submit one manually constructed IBKR PAPER order
from the existing Streamlit Paper Trading page. Submission remains impossible
unless both a fail-closed local configuration gate and a session-only operator
confirmation are active. All Phase 2 order validation and one-time Preview
controls remain in force.

This change does not add live trading, automatic strategy execution, batch
orders, cancellation, replacement, modification, unattended execution, or a
live endpoint path.

## Non-negotiable boundaries

- Broker provider must be `ibkr`.
- Broker mode must be exactly `paper`.
- Host must be exactly `127.0.0.1`.
- Port must be exactly `7497`.
- Client ID must be exactly `10`.
- Maximum Submit estimated notional remains USD 1,000.
- MARKET Preview retains the named USD 950 safety buffer.
- Submit requires the exact Preview issued by the same executor.
- The Preview must match the current ticket, remain unexpired, and be
  unconsumed.
- MARKET Submit makes a new IBKR snapshot request, requires IBKR live
  market-data type `1`, and revalidates notional using BUY ask or SELL bid.
- The snapshot callback has no quote timestamp, so quote age remains
  unavailable and is not independently verified.
- LIMIT Submit revalidates notional from the entered limit price.
- Delayed, frozen, missing, non-positive, NaN, and infinite MARKET prices
  remain blocked.
- Tiingo, cached quotes, prior closes, and guessed prices are never fallbacks.
- Exactly one managed account must be observed before Submit, while the
  implementation retains only the count and never an account identifier.
- No account ID, credential, API key, `.env` content, raw IBKR error, or
  advanced rejection payload is logged, returned, stored, or rendered.
- The official IBKR TWS Python API remains separately installed. No
  unofficial PyPI substitute is added.
- Automated and browser verification must not contact TWS or call a real
  `placeOrder`.

## Two independent Submit gates

### Gate 1: fail-closed local configuration

Add this non-secret setting to `.env.example` and local setup documentation:

```text
IBKR_PAPER_SUBMIT_ENABLED=false
```

`BrokerConfiguration` gains `paper_submit_enabled: bool = False`. The loader
reads the setting from the same dotenv/environment precedence used for the
other broker settings.

Parsing is deliberately fail-closed. Only this normalization may enable it:

```python
str(raw_value or "").strip().lower() == "true"
```

Consequences:

- missing is disabled;
- blank is disabled;
- `false` is disabled;
- `1`, `yes`, and `on` are disabled;
- malformed or unexpected values are disabled; and
- trimmed, case-insensitive exact `true` is enabled.

The application never reflects the raw value. It displays only a safe
Enabled/Disabled status. Changing this setting requires a new Preview because
the Preview and its executor are created together from one configuration
snapshot.

`build_paper_order_executor(configuration)` passes
`configuration.paper_submit_enabled` to
`IbkrPaperOrderExecutor(submission_enabled=...)`. The executor keeps its
existing internal guard, so configuration-disabled Submit fails before any
session or order construction even if a caller bypasses Streamlit.

### Gate 2: session-only operator confirmation

The Streamlit page adds an unchecked checkbox with this exact label:

> I intentionally disabled Read-Only API in TWS PAPER for this session.

The confirmation is stored only in `st.session_state` through its widget key.
It has no persistent default and is therefore false on app restart and every
new browser session. It is also reset after every Submit attempt.

The UI states explicitly that this checkbox is operator confirmation, not
automatic detection. The official API does not provide a reliable pre-submit
signal for the current TWS Read-Only setting. If the operator's statement is
wrong and TWS remains Read-Only, TWS may reject the order; the app shows only a
sanitized result or fixed error message.

No environment value can satisfy the operator confirmation, and the checkbox
cannot override a disabled configuration gate.

## Configuration validation

The existing five endpoint settings keep their exact validation. Adding the
Submit flag must not weaken or complicate that comparison. The connection
settings are validated independently from the boolean gate.

A configuration with `paper_submit_enabled=True` but any unsafe provider,
mode, host, port, or client ID fails before session creation. There is no
`BROKER_MODE=live`, live port, remote host, or live-submit flag branch.

The Phase 1 read-only broker snapshot provider continues to use the same
`BrokerConfiguration`; it ignores `paper_submit_enabled` and remains
read-only.

## Preview context and UI state

The page keeps these per-session values:

- executor that issued the Preview;
- exact immutable `OrderPreview`;
- configuration gate state captured when that executor was built;
- whether the Preview has been consumed;
- sanitized `OrderResult` or fixed safe error text from the last attempt; and
- operator confirmation checkbox state.

Preview remains available whether the configuration gate is enabled or
disabled. `load_order_preview` returns the executor, Preview, and safe boolean
gate state. No raw configuration mapping crosses into rendering.

Editing Symbol, Side, Quantity, Order type, or Limit price invalidates the
displayed Preview and clears its executor, gate state, consumed state, prior
result, and confirmation.

## Submit eligibility

A pure app-layer eligibility function receives:

- Preview;
- current `OrderIntent`;
- current timezone-aware UTC time;
- configuration gate boolean;
- operator confirmation boolean; and
- consumed boolean.

It returns true only when:

```text
configuration gate enabled
AND operator confirmation checked
AND Preview exists
AND Preview intent exactly equals current normalized intent
AND current UTC time is before Preview expiry
AND Preview is not consumed
```

The Streamlit Submit button is disabled otherwise. Because time can advance
while a rendered page is idle, the click handler repeats the eligibility check
on the click-triggered rerun immediately before invoking the executor. A
Preview that expired while the button was visible cannot reach
`submit_order`.

The executor independently rechecks exact issuance, equality, expiry, and
one-time consumption. UI eligibility is therefore a usability and
defense-in-depth gate, not the sole safety control.

## Submit flow

When the enabled Submit button is clicked:

1. Rebuild the current normalized intent from ticket values.
2. Re-evaluate both gates, exact match, expiry, and consumed state.
3. Mark the page's Preview consumed before calling the executor.
4. Call `executor.submit_order(preview)` exactly once.
5. The executor consumes the issued Preview before starting a session.
6. It connects only to `127.0.0.1:7497` as client ID `10` in PAPER mode.
7. It requires exactly one managed account without retaining its identifier.
8. It resolves exactly one `STK/SMART/USD` contract again.
9. MARKET makes a new live type-1 snapshot request and rechecks the USD 1,000
   hard limit. LIMIT recomputes using the entered limit price.
10. It obtains the existing `nextValidId` and submits exactly one order.
11. It maps the first broker callback to a sanitized `OrderResult`.
12. The page stores only the sanitized result or fixed safe error message,
    resets the operator checkbox, and leaves the Preview consumed.

Any post-consumption timeout or failure requires a completely new Preview.
There is no retry, automatic resubmission, cancellation, replacement, or
status-polling loop.

## Streamlit presentation

The page keeps a prominent `PAPER ONLY` warning and explains that enabling
manual PAPER Submit can transmit an order to the Paper account.

It displays two independent gate indicators:

- Local Submit gate: Enabled or Disabled;
- Operator confirmation: Confirmed or Required.

When the local flag is disabled, the page gives fixed guidance to set
`IBKR_PAPER_SUBMIT_ENABLED=true` locally and create a new Preview. It never
shows the raw environment value or `.env` contents.

The Submit button label remains `Submit PAPER order`. Its disabled help text
explains which safe condition is missing without revealing configuration
details. The checkbox copy states that confirmation is manual and not detected
from TWS.

After a Submit attempt, the page may show only:

- normalized order status;
- broker order ID;
- filled quantity;
- remaining quantity; and
- average fill price or `N/A`.

Account identifiers, permanent IDs, client IDs from callbacks, raw order
objects, raw broker errors, and advanced rejection JSON never appear.

## Error handling

Existing typed order errors remain. Streamlit maps them to fixed copy:

- configuration gate disabled;
- operator confirmation missing;
- Preview missing, changed, expired, or consumed;
- unsupported contract;
- live snapshot price unavailable or invalid;
- notional limit exceeded;
- official API unavailable;
- connection or account-scope failure;
- initial order-status timeout; and
- sanitized rejected/cancelled/inactive/unknown results.

No exception message from IBKR or a configuration value is interpolated into
the UI. A rejected broker callback becomes `OrderStatus.REJECTED` without raw
rejection text.

## Automated testing

All tests inject fake sessions, clocks, executors, and configuration mappings.
No test contacts TWS.

Configuration regression coverage includes:

- missing flag defaults false;
- blank, `false`, `1`, `yes`, `on`, malformed, and unexpected values stay
  false;
- trimmed/case-insensitive exact `true` becomes true;
- process environment overrides dotenv safely;
- production builder passes true only from the parsed boolean;
- unsafe provider, mode, host, port, or client ID cannot construct a
  submit-capable executor; and
- raw values never appear in errors or representations.

UI and workflow coverage includes:

- checkbox starts unchecked in a new session;
- page says confirmation is operator-provided, not detected;
- Submit disabled with either gate false;
- Submit disabled without a Preview;
- Submit disabled for changed, expired, or consumed Preview;
- click-time expiry recheck prevents an executor call;
- both gates plus an exact current Preview enable Submit;
- one click invokes the injected executor once;
- confirmation resets and Preview becomes consumed after success or failure;
- normalized filled, cancelled, rejected, and other results render without
  account or raw error details; and
- no Streamlit path adds live configuration, automation, cancel, replace, or
  batch behavior.

Existing executor tests continue to prove:

- exact PAPER endpoint enforcement;
- Preview equality, expiry, and duplicate prevention;
- MARKET new-snapshot revalidation and USD 1,000 hard limit;
- LIMIT notional revalidation;
- delayed/frozen/invalid quote rejection;
- safe order status mapping; and
- account identifiers and raw payloads are discarded.

## Documentation and delivery

Update `.env.example` with the disabled default and README with operator setup
and warnings. Never edit or inspect the real `.env`.

Implementation starts from latest `origin/main` on
`codex/ibkr-paper-manual-submit`. It runs the complete test suite, compilation,
dependency checks, source safety checks, and a local browser test using mocked
or non-submitting UI state. It creates a new PR targeting `main` and stops
without making any real TWS connection or `placeOrder` call.
