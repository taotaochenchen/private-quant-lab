# IBKR Paper Connectivity Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only Streamlit broker-status page that takes one bounded snapshot from a local IBKR TWS Paper session without exposing account IDs or implementing any order action.

**Architecture:** Immutable broker-domain models and a `BrokerProvider` protocol stay independent of IBKR and Streamlit. `IbkrBrokerProvider` orchestrates a one-shot, lazily created official `ibapi` session; a separate app configuration module enforces paper/loopback/7497/client-10 before the session factory is invoked, and a standalone Streamlit page renders only sanitized domain values.

**Tech Stack:** Python 3.11+, standard library threading/decimal/dataclasses, official externally installed IBKR TWS Python API (`ibapi`), python-dotenv, Streamlit 1.48+, unittest, Streamlit AppTest.

## Global Constraints

- Phase 1 is a read-only snapshot only.
- Do not add order submission, preview, cancellation, `reqIds`, what-if, modification, staging, or transmit paths.
- `BROKER_PROVIDER=ibkr` and `BROKER_MODE=paper` are mandatory.
- `BROKER_HOST=127.0.0.1`, `BROKER_PORT=7497`, and `BROKER_CLIENT_ID=10` are mandatory.
- TWS Read-Only API remains enabled.
- Never store, log, return, render, or commit an account ID, credential, secret, or `.env` content.
- Do not add `ibapi` or any unofficial IBKR substitute as a PyPI dependency.
- Open orders are optional under TWS Read-Only API; refusal or omitted completion renders exactly `Open orders unavailable while TWS Read-Only API is enabled.`
- Do not modify or inspect the real `.env`; update only `.env.example` with safe non-secret defaults.

---

### Task 1: Framework-independent broker domain and configuration

**Files:**
- Create: `src/private_quant/broker/base.py`
- Create: `src/private_quant/broker/models.py`
- Create: `src/private_quant/app/broker_config.py`
- Test: `tests/test_broker_contracts.py`
- Test: `tests/test_broker_config.py`
- Modify: `tests/test_package_imports.py`

**Interfaces:**
- Produces: `BrokerProvider.get_read_only_snapshot() -> BrokerSnapshot`.
- Produces: `AccountBalance`, `BrokerPosition`, `BrokerOpenOrder`, `OpenOrdersAvailability`, and `BrokerSnapshot` immutable models.
- Produces: `BrokerConfiguration`, `load_broker_configuration()`, and `build_broker_provider()`.
- Consumes later: `IbkrBrokerProvider(configuration, session_factory=...)` from Task 2.

- [ ] **Step 1: Write failing broker-contract tests**

  Add tests that import the wished-for types, construct a complete snapshot,
  assert immutable tuple-based fields, and assert neither dataclass field names
  nor `repr(snapshot)` contain `account`, `account_id`, or a supplied sentinel
  account value. Define the expected protocol use literally:

  ```python
  class FakeBrokerProvider:
      def get_read_only_snapshot(self) -> BrokerSnapshot:
          return expected_snapshot

  provider: BrokerProvider = FakeBrokerProvider()
  self.assertEqual(provider.get_read_only_snapshot(), expected_snapshot)
  ```

- [ ] **Step 2: Run broker-contract tests and verify RED**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.test_broker_contracts -v
  ```

  Expected: import failure because the broker base and model modules do not yet
  exist.

- [ ] **Step 3: Implement the minimal broker domain**

  Define frozen, slotted dataclasses with these signatures:

  ```python
  @dataclass(frozen=True, slots=True)
  class AccountBalance:
      name: str
      value: Decimal
      currency: str

  @dataclass(frozen=True, slots=True)
  class BrokerPosition:
      symbol: str
      security_type: str
      currency: str
      quantity: Decimal
      average_cost: Decimal

  @dataclass(frozen=True, slots=True)
  class BrokerOpenOrder:
      symbol: str
      side: str
      quantity: Decimal
      order_type: str
      limit_price: Decimal | None
      status: str

  class OpenOrdersAvailability(StrEnum):
      AVAILABLE = "available"
      UNAVAILABLE_READ_ONLY = "unavailable_read_only"

  @dataclass(frozen=True, slots=True)
  class BrokerSnapshot:
      connected: bool
      mode: str
      balances: tuple[AccountBalance, ...]
      positions: tuple[BrokerPosition, ...]
      open_orders: tuple[BrokerOpenOrder, ...]
      open_orders_availability: OpenOrdersAvailability

  class BrokerProvider(Protocol):
      def get_read_only_snapshot(self) -> BrokerSnapshot: ...
  ```

  Add broker exception types for safe configuration, official-package,
  connection, and required-data timeout failures. Export only domain-safe names
  from `private_quant.broker`.

- [ ] **Step 4: Run broker-contract tests and verify GREEN**

  Run the command from Step 2 and expect all tests to pass.

- [ ] **Step 5: Write failing configuration tests**

  Use temporary `.env` fixtures and injected process-environment mappings. Test
  the literal valid values and each refusal independently:

  ```text
  BROKER_PROVIDER=ibkr
  BROKER_MODE=paper
  BROKER_HOST=127.0.0.1
  BROKER_PORT=7497
  BROKER_CLIENT_ID=10
  ```

  Assert `BROKER_MODE=live`, host `localhost`, port `7496`, client ID `0`, a
  missing value, and another provider all raise `BrokerConfigurationError`.
  Assert the provider factory is not called after any invalid configuration.
  Assert exception text never contains a supplied sentinel value.

- [ ] **Step 6: Run configuration tests and verify RED**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.test_broker_config -v
  ```

  Expected: import failure because `broker_config.py` does not exist.

- [ ] **Step 7: Implement strict broker configuration**

  Implement:

  ```python
  @dataclass(frozen=True, slots=True)
  class BrokerConfiguration:
      provider_name: str
      mode: str
      host: str
      port: int
      client_id: int

  def load_broker_configuration(
      env_path: str | Path = PROJECT_ROOT / ".env",
      *,
      environment: Mapping[str, str] | None = None,
  ) -> BrokerConfiguration: ...

  def build_broker_provider(
      configuration: BrokerConfiguration,
      *,
      session_factory: IbkrSessionFactory = create_official_ibkr_session,
  ) -> BrokerProvider: ...
  ```

  Load `.env` through `dotenv_values`, overlay only the five broker names from
  `environment`/`os.environ`, normalize provider and mode, parse integers, and
  validate the exact Phase 1 values before importing or constructing the IBKR
  provider. Pass primitive values to `IbkrBrokerProvider` so the broker package
  does not import the app configuration module. Use fixed safe error messages.

- [ ] **Step 8: Run configuration and package-import tests**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.test_broker_contracts tests.test_broker_config tests.test_package_imports -v
  ```

  Expected: all tests pass.

- [ ] **Step 9: Commit Task 1**

  Stage only the files listed in Task 1 and commit:

  ```text
  feat: add read-only broker contracts
  ```

---

### Task 2: Official IBKR one-shot read-only adapter

**Files:**
- Create: `src/private_quant/broker/ibkr.py`
- Test: `tests/test_ibkr_broker.py`

**Interfaces:**
- Consumes: primitive validated connection values and broker-domain models from Task 1.
- Produces: `IbkrSession` protocol, `IbkrSessionFactory`, `IbkrBrokerProvider`, and `create_official_ibkr_session()`.
- Consumes later: `build_broker_provider()` and the Streamlit page.

- [ ] **Step 1: Write failing orchestration tests with a fake session**

  Implement a test-only `FakeIbkrSession` that exposes only:

  ```python
  start(host: str, port: int, client_id: int) -> None
  wait_until_connected(timeout: float) -> bool
  request_account_summary() -> None
  request_positions() -> None
  request_open_orders() -> None
  wait_for_account_summary(timeout: float) -> bool
  wait_for_positions(timeout: float) -> bool
  wait_for_open_orders(timeout: float) -> bool
  balances: tuple[AccountBalance, ...]
  positions: tuple[BrokerPosition, ...]
  open_orders: tuple[BrokerOpenOrder, ...]
  close() -> None
  ```

  Construct the provider with this explicit interface:

  ```python
  IbkrBrokerProvider(
      mode="paper",
      host="127.0.0.1",
      port=7497,
      client_id=10,
      session_factory=fake_factory,
  )
  ```

  Test direct refusal of unsafe mode, host, port, and client ID before the fake
  session factory is called. Test the exact endpoint/client arguments, request order, successful snapshot,
  disconnect in success/failure paths, connection timeout, required account
  summary timeout, required positions timeout, open-order timeout mapping to
  `UNAVAILABLE_READ_ONLY`, and an empty completed open-order result mapping to
  `AVAILABLE`.

- [ ] **Step 2: Run adapter tests and verify RED**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.test_ibkr_broker -v
  ```

  Expected: import failure because `private_quant.broker.ibkr` does not exist.

- [ ] **Step 3: Implement minimal provider orchestration**

  `IbkrBrokerProvider` must repeat the exact Phase 1 safety validation without
  importing `private_quant.app`. `get_read_only_snapshot()` must create one
  session, start it with the validated values, wait for the handshake, make only the
  three approved read requests, require account-summary and position completion,
  tolerate omitted open-order completion, and call `close()` in `finally`.
  It returns `connected=True`, `mode="paper"`, tuples from the session, and the
  correct open-order availability.

- [ ] **Step 4: Run adapter tests and verify GREEN**

  Run the command from Step 2 and expect all orchestration tests to pass.

- [ ] **Step 5: Write failing official-session callback tests**

  Create the official session without opening a socket and call its callbacks
  with `SimpleNamespace` contract/order/order-state objects. Supply sentinel
  account IDs to `accountSummary`, `position`, and `openOrder`; assert mapped
  domain values contain only the approved fields and that the sentinel is
  absent from `repr(session.balances)`, `repr(session.positions)`, and
  `repr(session.open_orders)`. Verify end callbacks release their matching
  waits. Verify an import failure becomes `OfficialIbapiUnavailableError` with
  fixed official-install guidance.

- [ ] **Step 6: Implement the lazy official `ibapi` session**

  `create_official_ibkr_session()` lazily imports `EClient` and `EWrapper` and
  defines a private combined client. Its callbacks:

  - set a connection event on `nextValidId` and discard the ID;
  - ignore the account argument in `accountSummary` and accept only
    `BuyingPower`/`TotalCashValue`;
  - ignore the account argument in `position`;
  - ignore IBKR order ID and `order.account` in `openOrder`;
  - set completion events in `accountSummaryEnd`, `positionEnd`, and
    `openOrderEnd`;
  - never print or retain raw error text.

  The session's approved request methods call only:

  ```python
  reqAccountSummary(9001, "All", "BuyingPower,TotalCashValue")
  reqPositions()
  reqAllOpenOrders()
  ```

  Cleanup may cancel the two data subscriptions and disconnect; it does not
  call an order cancellation API.

- [ ] **Step 7: Run all IBKR and broker tests**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.test_broker_contracts tests.test_broker_config tests.test_ibkr_broker -v
  ```

  Expected: all tests pass without TWS.

- [ ] **Step 8: Commit Task 2**

  Stage only the adapter and its tests and commit:

  ```text
  feat: add read-only IBKR paper adapter
  ```

---

### Task 3: Streamlit broker-status page and safe setup documentation

**Files:**
- Create: `src/private_quant/app/broker_status.py`
- Test: `tests/test_broker_status_app.py`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Consumes: `load_broker_configuration()`, `build_broker_provider()`, and `BrokerSnapshot`.
- Produces: `load_broker_snapshot()`, `broker_error_message()`, `render_broker_snapshot()`, and the standalone Streamlit entry point.

- [ ] **Step 1: Write failing Streamlit helper and rendering tests**

  Test `load_broker_snapshot()` with injected configuration/provider factories.
  Test fixed safe messages for configuration, official-package, connection,
  and timeout errors without reflecting sentinel details. Use AppTest to render
  a successful snapshot and assert visible text for `Connected`,
  `PAPER — configuration enforced`, buying power, cash, positions, and open
  orders. Add separate tests for empty positions/orders and
  `UNAVAILABLE_READ_ONLY`, asserting the approved message exactly. Assert no
  sentinel account ID appears anywhere in rendered markdown, text, metrics,
  dataframes, warnings, errors, or exceptions.

- [ ] **Step 2: Run Streamlit tests and verify RED**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.test_broker_status_app -v
  ```

  Expected: import failure because `broker_status.py` does not exist.

- [ ] **Step 3: Implement the standalone page**

  Render the title `Private Quant Lab — Paper Broker`, a prominent
  `Read-only monitoring only. No order actions are available.` notice, and one
  primary `Connect / Refresh` button. On click, take one provider snapshot and
  render responsive connection/mode/balance metrics plus positions and open
  orders tables. Tables include only approved domain fields. Do not cache or
  persist the socket session across reruns.

- [ ] **Step 4: Run Streamlit tests and verify GREEN**

  Run the command from Step 2 and expect all tests to pass.

- [ ] **Step 5: Update safe configuration and README**

  Replace the obsolete broker account/key placeholders in `.env.example` with:

  ```text
  BROKER_PROVIDER=ibkr
  BROKER_MODE=paper
  BROKER_HOST=127.0.0.1
  BROKER_PORT=7497
  BROKER_CLIENT_ID=10
  ```

  Document that the official `ibapi` must be installed from IBKR's TWS API
  download into the active environment, that TWS Paper and Read-Only API must
  be active, and the exact page command:

  ```powershell
  python -m streamlit run src/private_quant/app/broker_status.py
  ```

  State explicitly that Phase 1 has no order capability.

- [ ] **Step 6: Run the complete mocked suite**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest discover -s tests -v
  .\.venv\Scripts\python.exe -m compileall -q src tests
  .\.venv\Scripts\python.exe -m pip check
  git diff --check
  ```

  Expected: zero test failures, successful compilation, no broken requirements,
  and no whitespace errors.

- [ ] **Step 7: Commit Task 3**

  Stage only the page, tests, `.env.example`, and README and commit:

  ```text
  feat: add IBKR paper broker status page
  ```

---

### Task 4: Safety review, live read-only verification, browser test, and PR

**Files:**
- Review all committed Phase 1 files; no new production file is required.

**Interfaces:**
- Consumes: the completed broker provider and Streamlit page.
- Produces: verified branch and a new pull request targeting `main`.

- [ ] **Step 1: Perform source and Git safety scans**

  Search only tracked source/tests/docs—not the real `.env`—for forbidden
  production calls (`placeOrder`, `reqIds`, what-if, order cancellation,
  transmit), account-ID fields, logging/printing, credentials, and secrets.
  Confirm `.env` is untracked/ignored through Git metadata without opening it.
  Inspect the committed diff against `origin/main`.

- [ ] **Step 2: Run fresh full verification**

  Re-run the complete unittest suite, compileall, pip check, and diff check from
  Task 3 after all edits and commits. Record the exact passing test count.

- [ ] **Step 3: Verify the live TWS Paper snapshot without account output**

  Launch Streamlit with the five safe `BROKER_*` values supplied as process
  environment overrides. Do not open or modify `.env`. Use the page to connect
  once to `127.0.0.1:7497` as client `10` and verify only these boolean/section
  outcomes:

  - connected;
  - mode shown as paper/configuration-enforced;
  - buying power/cash section populated;
  - positions section completed, including a legitimate empty state;
  - open orders completed or displays the approved Read-Only unavailable state.

  Do not capture or report account IDs or exact account balances in tool output,
  commentary, screenshots, commits, or the PR.

- [ ] **Step 4: Browser-test the Streamlit page**

  In the local browser, click `Connect / Refresh`, verify the required headings
  and safe statuses, inspect the browser console for errors, then close the test
  tab and stop Streamlit. Do not take a screenshot containing account values.

- [ ] **Step 5: Push and create the pull request**

  Push `codex/ibkr-paper-connectivity` and create a new PR targeting `main`.
  The PR summary must state the official external API prerequisite, strict paper
  guards, exact mocked/full test results, sanitized live/browser verification,
  open-order Read-Only behavior, and the absence of every order action path.
