# IBKR Paper Connectivity Phase 1 Design

Date: 2026-08-26

## Goal

Add a local, read-only broker-status workflow that connects the Private Quant
Lab Streamlit application to an already-running IBKR Trader Workstation paper
session. Phase 1 proves connectivity and retrieves account summary values,
positions, and open orders when TWS exposes them. It cannot create, preview,
stage, modify, cancel, or transmit an order.

## Non-negotiable safety constraints

- `BROKER_MODE` must normalize to exactly `paper`; every other value is
  rejected before an IBKR socket is opened.
- The host must be `127.0.0.1`, the port must be `7497`, and the client ID must
  be `10`.
- TWS Read-Only API stays enabled for all Phase 1 development and validation.
- The broker abstraction contains no order-submission, preview, cancellation,
  what-if, transmit, or order-ID request operation.
- The IBKR adapter never calls `placeOrder`, `reqIds`, an order preview or
  what-if path, a cancellation method, or a modification method.
- Account IDs can appear in IBKR callbacks, but the adapter discards them at
  the callback boundary. They are never stored, logged, returned, rendered,
  included in an exception, or committed.
- The real `.env` is not opened, printed, modified, or committed by the
  implementation workflow. Only `.env.example` receives safe configuration
  names and non-secret paper defaults.
- The official IBKR TWS Python API installed from IBKR's download is an
  external prerequisite. The project does not add an `ibapi` or other IBKR
  package from PyPI.

## Paper-mode validation boundary

IBKR documents that a TWS API socket connection does not identify whether the
logged-in TWS session is live or paper. Phase 1 therefore validates the safety
inputs it can prove:

- provider is `ibkr`;
- configured mode is `paper`;
- host is loopback `127.0.0.1`;
- port is the TWS paper default `7497`;
- client ID is the dedicated value `10`;
- the operator has confirmed TWS is visibly logged into Paper Trading with
  Read-Only API enabled.

The application does not inspect or infer mode from an account-ID prefix.
Streamlit labels the result `PAPER — configuration enforced` rather than
claiming the socket protocol independently proved the TWS login type.

## Architecture

### Framework-independent broker domain

`private_quant.broker.base` defines a `BrokerProvider` protocol with one
operation:

```python
def get_read_only_snapshot(self) -> BrokerSnapshot
```

`private_quant.broker.models` defines immutable domain values for:

- connection state and paper-mode validation;
- account balances (`BuyingPower` and `TotalCashValue`, including currency);
- positions (symbol, security type, currency, quantity, average cost);
- open orders (symbol, side, quantity, order type, optional limit price,
  status);
- open-order availability (`available`, `unavailable`, `timeout`, or
  `unavailable_read_only` when there is positive evidence of that cause);
- the complete `BrokerSnapshot`.

None of these values has an account-ID or credential field.

### IBKR adapter

`private_quant.broker.ibkr` implements `IbkrBrokerProvider` using the official
`ibapi` `EClient` and `EWrapper` APIs. Its constructor accepts only primitive
connection settings (`mode`, `host`, `port`, and `client_id`), so the broker
package never imports the Streamlit/app configuration layer. The public
provider depends on a small session interface so unit tests can inject a fake
session without TWS.

The production session is created lazily. This keeps package imports and the
rest of the test suite usable on machines where the separately installed
official API is absent, while producing fixed setup guidance if a user tries
to connect without it.

Each refresh uses a one-shot session:

1. Connect to `127.0.0.1:7497` as client ID `10`.
2. Start the official message loop on a daemon thread.
3. Wait for the normal connection handshake. The `nextValidId` callback may be
   received as part of that handshake, but its value is immediately discarded
   and `reqIds` is never called.
4. Request account summary tags `BuyingPower` and `TotalCashValue`.
5. Request positions.
6. Request all currently visible open orders through the read-only
   `reqAllOpenOrders` API.
7. Wait for the corresponding end callbacks with bounded timeouts.
8. Cancel only the account-summary and positions subscriptions, disconnect,
   and join the reader thread.

The adapter converts callback values to broker-domain models. It does not
return raw `ibapi` objects.

Because the account-summary request uses the `All` group, the adapter compares
ephemeral keyed fingerprints of callback account values. It retains no account
ID. If more than one distinct account is observed, it clears collected
balances and fails the required snapshot with fixed safe guidance rather than
aggregating or choosing an account. The temporary fingerprint key and digest
are cleared after completion, immediately on multi-account detection, and on
session cleanup; cleanup also discards partial balances and ignores late
account-summary callbacks.

### Open orders under TWS Read-Only API

TWS versions differ in how Read-Only API affects order information. The
adapter attempts the normal read-only open-order request.

- If `openOrderEnd` arrives, the result is available. An empty list means
  `No open orders`.
- If the completion callback times out, the snapshot marks open orders as
  `timeout`. Other callback/property failures use `unavailable`.
- The official API does not provide a reliable Read-Only-specific result for
  this request, so Phase 1 does not infer that cause. `unavailable_read_only`
  is reserved for future positive evidence.
- Neutral Streamlit guidance says:

  `Open orders unavailable in the current TWS session. Read-Only API may be the cause.`

- If positive Read-Only evidence becomes available, Streamlit may render:

  `Open orders unavailable while TWS Read-Only API is enabled.`

Phase 1 never asks the operator to disable Read-Only API.

### Configuration

`private_quant.app.broker_config` reads these names from the repository-root
`.env`, with process-environment values taking precedence so local verification
does not require editing the real file:

```text
BROKER_PROVIDER=ibkr
BROKER_MODE=paper
BROKER_HOST=127.0.0.1
BROKER_PORT=7497
BROKER_CLIENT_ID=10
```

Parsing and validation happen before provider construction. The provider
repeats the exact paper/loopback/7497/client-10 checks as a defense-in-depth
guard for callers that bypass the app configuration builder. Public errors use
fixed messages and never echo raw values.

### Streamlit page

`private_quant.app.broker_status` is a standalone local Streamlit page. It
renders immediately with a prominent read-only safety notice and a
`Connect / Refresh` button. A click creates a one-shot provider snapshot and
shows:

- connection status;
- `PAPER — configuration enforced`;
- buying power and total cash by currency;
- positions in a table without account IDs;
- open orders in a table without account IDs or IBKR order IDs, or a cause-safe
  unavailable/timeout message.

The page contains no trading form, ticker/order input, action buttons, or order
methods. Exceptions are mapped to fixed connection/setup/timeout messages; raw
IBKR callback text is not rendered.

## Error handling

- Invalid or missing broker configuration: refuse before opening a socket and
  show safe setup guidance.
- Official `ibapi` unavailable: show instructions to install IBKR's official
  TWS API package; do not suggest a PyPI substitute.
- TWS offline, socket refused, duplicate client ID, or handshake timeout: show
  a fixed connection message without callback details.
- Account summary or positions timeout: fail the snapshot because the required
  read-only proof is incomplete.
- More than one account-summary identity: clear balances and fail the snapshot
  without retaining or exposing either account ID.
- Open-order refusal or timeout after the other reads succeed: keep the
  snapshot and mark only open orders unavailable without claiming Read-Only as
  the cause.
- Always disconnect and stop the reader loop in `finally` cleanup.

## Testing

Automated tests use fake sessions and Streamlit AppTest; they do not require a
running TWS session or any account data. Coverage includes:

- broker-domain models do not expose account identifiers;
- valid configuration normalization;
- refusal of non-paper mode, non-loopback host, wrong port, wrong client ID,
  and unsupported provider before a session is created;
- successful mapping of buying power, cash, positions, and open orders;
- empty positions and empty open orders;
- neutral open-order unavailable and timeout states while required data remains
  usable;
- multiple account-summary callbacks fail safely without retaining identifiers;
- connection and required-data failures;
- Streamlit success, empty, unavailable, and safe-error states;
- package import behavior with the external official API boundary.

After mocked tests pass, run the complete existing suite, compile checks,
dependency checks, and a source safety scan confirming forbidden order paths
are absent. Then launch Streamlit with safe process-environment configuration,
connect once to the operator's running TWS Paper session, verify the required
read-only sections without capturing account IDs, and browser-test the page.

## Delivery

Work is committed on `codex/ibkr-paper-connectivity`, pushed to the GitHub
repository, and submitted as a new pull request targeting `main`. The PR records
mocked-test results, live read-only verification scope, browser evidence, the
external official API prerequisite, and confirmation that no order path or
account identifier was added.
