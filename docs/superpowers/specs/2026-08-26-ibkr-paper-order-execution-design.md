# IBKR Paper Order Execution Design

**Date:** 2026-08-26  
**Status:** Approved for implementation planning  
**Scope:** Phase 2 paper-order workflow with live submission hard-disabled

## Goal

Add a framework-independent, PAPER-only order workflow to the existing IBKR
broker layer. Users can construct and preview US stock and ETF orders in a
local Streamlit ticket. The order execution path is fully covered with mocked
tests, but the production application cannot transmit an order until a future,
explicitly approved change removes the application-level submission lock.

This phase does not add live trading, automatic strategy execution, order
modification, order cancellation, batch execution, or unattended execution.

## Non-negotiable safety boundaries

- The provider is `ibkr` in `paper` mode only.
- The endpoint is exactly `127.0.0.1:7497` with client ID `10`.
- Any other mode, host, port, client ID, or provider is rejected before a
  socket connection.
- TWS Read-Only API remains enabled during this phase.
- The Streamlit Submit button is always disabled in this pull request.
- The production executor is constructed with `submission_enabled=False` and
  rejects submission before connecting to TWS or constructing an IBKR order.
- Tests may explicitly enable submission only with an injected fake session;
  automated tests never require or contact TWS.
- No account ID, credential, `.env` value, API key, raw IBKR error text, or
  advanced rejection payload is stored, logged, returned, or rendered.
- The official IBKR TWS Python API remains a separately installed dependency;
  no unofficial `ibapi` PyPI dependency is added.

## Architecture

Phase 1's `BrokerProvider` remains a read-only snapshot interface. Order
methods are not added to it.

Phase 2 adds a separate `PaperOrderExecutionProvider` protocol with two
operations:

```python
def preview_order(intent: OrderIntent) -> OrderPreview: ...
def submit_order(preview: OrderPreview) -> OrderResult: ...
```

`IbkrPaperOrderExecutor` implements this protocol. It depends on a narrow
internal `IbkrOrderSession` interface so contract lookup, quotes, submission,
and callbacks can be tested without Streamlit or a live TWS connection.

The production session uses only the installed official TWS API. The
Streamlit page depends on the framework-independent protocol and immutable
domain models. Streamlit does not appear in the broker package.

## Immutable domain models

Order models live separately from the Phase 1 account snapshot models.

### OrderIntent

- `symbol: str`
- `side: OrderSide` where values are `BUY` and `SELL`
- `quantity: int`, default `1`
- `order_type: OrderType` where values are `MARKET` and `LIMIT`
- `limit_price: Decimal | None`

### OrderPreview

- `preview_id: str`, a random opaque one-time identifier
- `intent: OrderIntent`, containing the normalized values that were validated
- `estimated_unit_price: Decimal`
- `estimated_notional: Decimal`
- `quote_source: QuoteSource`, either `IBKR_LIVE_ASK`, `IBKR_LIVE_BID`, or
  `USER_LIMIT`
- `created_at: datetime` in UTC
- `expires_at: datetime` in UTC, 60 seconds after creation

### OrderResult

- `preview_id: str`
- `broker_order_id: int`
- `status: OrderStatus`
- `filled_quantity: Decimal`
- `remaining_quantity: Decimal`
- `average_fill_price: Decimal | None`

IBKR order IDs may be returned because the order status workflow requires
them. Account IDs never appear in any order model.

### OrderStatus

Normalized values are:

- `PENDING_SUBMIT`
- `PRE_SUBMITTED`
- `SUBMITTED`
- `FILLED`
- `CANCELLED`
- `REJECTED`
- `INACTIVE`
- `UNKNOWN`

Known IBKR status strings map to these values. A broker rejection callback for
the submitted order maps to `REJECTED`, but its raw text and advanced rejection
JSON are discarded immediately.

## Intent validation

Symbols are stripped and uppercased. They must match a conservative US ticker
syntax: one to ten characters using letters, digits, periods, or hyphens, with
the first character a letter. Blank or malformed values fail before any TWS
connection.

Quantity must be a positive integer. Boolean values, zero, negative values,
fractional values, NaN, and infinity are rejected. The UI default is `1`.

For LIMIT orders, `limit_price` is required and must be a finite positive
`Decimal`. MARKET orders must not contain a limit price.

The executor resolves a contract through a fresh IBKR contract-details request
using `symbol`, `secType="STK"`, `exchange="SMART"`, and `currency="USD"`.
Exactly one matching contract must be returned. The returned contract must
remain `STK`, `SMART`, and `USD` with a positive IBKR contract identifier.
This is the Phase 2 definition of a supported US stock or ETF. Missing,
ambiguous, or mismatched contracts are rejected with fixed safe guidance.

## Preview and notional validation

### MARKET orders

MARKET orders use a newly initiated snapshot request from the broker execution
layer for the resolved contract. No quote is cached or reused between Preview
and Submit. Tiingo EOD data, cached values, prior closes, delayed data, frozen
data, and guessed values are never fallback sources.

The snapshot request must report IBKR live market-data type `1`. BUY uses the
ask returned by that request and SELL uses its bid. The selected value must be
present, finite, and strictly positive. Missing, zero, negative, NaN,
infinite, delayed, or frozen values block Preview and Submit.

The official `reqMktData(..., snapshot=True, ...)` flow used here delivers the
bid and ask through `tickPrice(reqId, tickType, price, attrib)`. That callback
does not include a quote timestamp or age signal. The adapter therefore proves
that it made a new snapshot request and received market-data type `1`, but it
does **not** independently verify the age of the returned bid or ask. The UI
states this limitation explicitly. Phase 2 makes no claim that stale quotes
can be identified when IBKR labels the response live and provides no age data.

Preview calculates:

```text
estimated_notional = quantity × returned_snapshot_side_price
```

A MARKET Preview is accepted only when estimated notional is at most
USD 950. The code names this threshold
`MARKET_PREVIEW_SAFETY_BUFFER_LIMIT`. It reserves USD 50 below the separate
USD 1,000 `ORDER_SUBMIT_HARD_LIMIT` for market movement; USD 950 is not the
Submit limit. The UI and documentation use these names explicitly so the two
controls cannot be confused. A true market order can still fill above the
estimate and cannot guarantee an absolute final notional.

Immediately before Submit, the executor resolves the contract again, makes a
new IBKR live snapshot request, and recomputes notional. It blocks submission
if the returned value is invalid or exceeds USD 1,000. It does not reuse the
Preview quote, but the new response still has no independently verifiable quote
age.

### LIMIT orders

LIMIT Preview and Submit both calculate:

```text
estimated_notional = quantity × limit_price
```

The result must be at most USD 1,000 at both stages. No market-data request is
needed for LIMIT notional validation, but the contract is resolved again at
Submit.

All notional calculations use `Decimal`; float arithmetic is not used for
safety decisions.

## Preview integrity and duplicate prevention

Each preview is bound to its complete normalized intent and expires after
60 seconds. Editing any ticket value invalidates the currently displayed
preview. Submit requires the exact preview object issued by the same executor,
and the preview must be unexpired and unconsumed.

The executor maintains a set of issued preview IDs and a set of consumed
preview IDs for its lifetime. It marks a preview consumed before invoking the
session submission call. A second call with the same preview is rejected even
when the first call times out or returns a broker error. The same opaque
preview ID is assigned to the IBKR `orderRef` field, providing a broker-visible
idempotency tag without account information.

The Streamlit executor and preview live in `st.session_state`, preventing
normal reruns and double-clicks from creating a new execution context. A full
application restart discards previews, so a prior preview cannot be
resubmitted after restart. This phase does not add a persistent order ledger.

## IBKR submission session

The session connects only to the validated Paper endpoint. It obtains the
initial order ID from the normal `nextValidId` connection callback and does
not call `reqIds`.

Before any enabled submission, the session requires the automatic
`managedAccounts` callback to report exactly one distinct account. It retains
only the integer count and immediately discards callback identifiers. Zero or
multiple accounts block submission with fixed safe guidance. The order does
not set or expose an account field.

When submission is explicitly enabled in a mocked test, the adapter builds:

- an IBKR `Contract` from the uniquely resolved `STK/SMART/USD` contract;
- an IBKR `Order` with action `BUY` or `SELL`;
- order type `MKT` or `LMT`;
- integer quantity;
- a limit price only for `LMT`;
- `orderRef` set to the opaque preview ID; and
- `transmit=True` for the actual Submit operation.

The production builder never enables this path in Phase 2. Calling Submit in
production fails before connection or order construction.

The session waits a bounded time for an initial `openOrder`, `orderStatus`, or
rejection callback and returns a sanitized `OrderResult`. Callback account
fields, permanent IDs, client IDs, parent IDs, raw errors, and advanced reject
payloads are discarded.

Phase 2 provides no cancel, replace, modify, stage, what-if, or automatic
resubmission method.

## Streamlit Paper Trading page

A new page is added without changing the Phase 1 broker-status page. It shows:

- a prominent `PAPER ONLY` warning;
- a statement that TWS Read-Only API remains enabled;
- Symbol;
- BUY / SELL;
- Quantity, default `1`;
- MARKET / LIMIT;
- Limit price only for LIMIT;
- Preview;
- estimated unit price and notional after a valid Preview;
- quote source and Preview expiry; and
- Submit, visibly disabled for the entire Phase 2 pull request.

The page explains that future Submit activation requires explicit approval and
a separate application change after TWS Read-Only is intentionally disabled.
No automatic action runs on page load or rerun.

Changing ticket fields clears the preview. Validation and provider failures
map to fixed, user-friendly messages. Raw exception details and account data
are never rendered.

## Error model

Typed broker-order exceptions distinguish:

- unsafe configuration;
- invalid intent;
- unsupported or ambiguous contract;
- quote unavailable or invalid;
- notional limit exceeded;
- Preview missing, changed, expired, or already consumed;
- submission disabled;
- broker connection timeout;
- order-status timeout.

Messages crossing into Streamlit are fixed text selected by exception type.
Vendor exception objects are not chained into safe exceptions.
Broker rejection callbacks are returned as a sanitized `OrderResult` with
status `REJECTED`, never as a raw vendor exception.

## Automated testing

All order tests inject fake sessions and clocks. They do not connect to TWS.
Coverage includes:

- valid BUY and valid SELL intents;
- default quantity `1`;
- MARKET using live ask for BUY and live bid for SELL;
- LIMIT using the entered limit price;
- invalid and blank ticker;
- invalid, fractional, zero, and negative quantity;
- missing, invalid, non-positive, NaN, or infinite prices;
- delayed and frozen market data rejected;
- UI copy distinguishes a new snapshot request, live market-data type `1`,
  and unavailable quote-age verification;
- MARKET Preview above USD 950 rejected;
- MARKET Submit re-quote above USD 1,000 rejected;
- LIMIT notional above USD 1,000 rejected at Preview and Submit;
- non-paper or non-loopback configuration rejected before session creation;
- missing, changed, expired, and duplicate Preview rejected;
- order ID and status callback mapping;
- rejected, cancelled, inactive, submitted, and filled states;
- raw account and error details absent from models, errors, and rendered UI;
- production submission lock rejects before connecting or calling
  `placeOrder`;
- zero or multiple managed accounts block an enabled mocked submission without
  retaining account identifiers;
- Submit remains disabled in Streamlit; and
- the complete existing test suite remains green.

Source-level tests also assert that the order adapter exposes no live-mode,
cancel, replace, what-if, automatic execution, or `reqIds` path.

## Verification and delivery

Implementation will:

1. follow test-driven development with a red test before each production
   behavior;
2. run the complete automated suite;
3. run compile and dependency checks;
4. browser-test the local Streamlit ticket while keeping Submit disabled;
5. verify no real `placeOrder` call reached TWS;
6. commit only source, tests, and documentation; and
7. create a new pull request from `codex/ibkr-paper-order-execution` to
   `main`.

No `.env`, API key, credential, account ID, or captured account value is read,
printed, modified, or committed.
