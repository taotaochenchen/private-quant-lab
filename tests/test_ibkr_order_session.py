import ast
from decimal import Decimal
from io import StringIO
import logging
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.broker.base import OfficialIbapiUnavailableError
from private_quant.broker.ibkr_order_session import (
    create_official_ibkr_order_session,
)
from private_quant.broker.ibkr_orders import ResolvedContract
from private_quant.broker.order_models import OrderIntent, OrderSide, OrderType


def resolved(symbol: str = "AAPL") -> ResolvedContract:
    return ResolvedContract(symbol, 265598, "STK", "SMART", "USD")


class OfficialIbkrOrderSessionTests(unittest.TestCase):
    def test_contract_request_is_stk_smart_usd_and_maps_one_result(self) -> None:
        session = create_official_ibkr_order_session()
        requested_contracts: list[object] = []

        def answer_contract(req_id: int, contract: object) -> None:
            requested_contracts.append(contract)
            session.contractDetails(
                req_id,
                SimpleNamespace(
                    contract=SimpleNamespace(
                        symbol="AAPL",
                        conId=265598,
                        secType="STK",
                        exchange="SMART",
                        currency="USD",
                    )
                ),
            )
            session.contractDetailsEnd(req_id)

        with patch.object(
            session, "reqContractDetails", side_effect=answer_contract
        ):
            contracts = session.resolve_contracts("AAPL", timeout=0.01)

        requested = requested_contracts[0]
        self.assertEqual(requested.symbol, "AAPL")
        self.assertEqual(requested.secType, "STK")
        self.assertEqual(requested.exchange, "SMART")
        self.assertEqual(requested.currency, "USD")
        self.assertEqual(contracts, (resolved(),))

    def test_contract_callback_followed_by_request_error_returns_no_contract(self) -> None:
        session = create_official_ibkr_order_session()

        def answer_then_fail(req_id: int, contract: object) -> None:
            del contract
            session.contractDetails(
                req_id,
                SimpleNamespace(
                    contract=SimpleNamespace(
                        symbol="AAPL",
                        conId=265598,
                        secType="STK",
                        exchange="SMART",
                        currency="USD",
                    )
                ),
            )
            session.error(req_id, 0, 200, "raw contract failure")

        with patch.object(
            session, "reqContractDetails", side_effect=answer_then_fail
        ):
            contracts = session.resolve_contracts("AAPL", timeout=0.01)

        self.assertEqual(contracts, ())

    def test_incomplete_contract_timeout_discards_partial_callback(self) -> None:
        session = create_official_ibkr_order_session()

        def answer_without_end(req_id: int, contract: object) -> None:
            del contract
            session.contractDetails(
                req_id,
                SimpleNamespace(
                    contract=SimpleNamespace(
                        symbol="AAPL",
                        conId=265598,
                        secType="STK",
                        exchange="SMART",
                        currency="USD",
                    )
                ),
            )

        with patch.object(
            session, "reqContractDetails", side_effect=answer_without_end
        ):
            contracts = session.resolve_contracts("AAPL", timeout=0)

        self.assertEqual(contracts, ())

    def test_live_snapshot_uses_bid_ask_and_requires_market_data_callback(self) -> None:
        session = create_official_ibkr_order_session()
        requested_contracts: list[object] = []

        def answer_quote(
            req_id: int,
            contract: object,
            generic_ticks: str,
            snapshot: bool,
            regulatory_snapshot: bool,
            options: list[object],
        ) -> None:
            del generic_ticks, snapshot, regulatory_snapshot, options
            requested_contracts.append(contract)
            session.marketDataType(req_id, 1)
            session.tickPrice(req_id, 1, 99.0, object())
            session.tickPrice(req_id, 2, 100.0, object())
            session.tickSnapshotEnd(req_id)

        with (
            patch.object(session, "reqMarketDataType") as market_data_type,
            patch.object(session, "reqMktData", side_effect=answer_quote),
        ):
            quote = session.request_live_quote(resolved(), timeout=0.01)

        market_data_type.assert_called_once_with(1)
        requested = requested_contracts[0]
        self.assertEqual(requested.conId, 265598)
        self.assertEqual(requested.secType, "STK")
        self.assertEqual(requested.exchange, "SMART")
        self.assertEqual(requested.currency, "USD")
        self.assertEqual(quote.market_data_type, 1)
        self.assertEqual(quote.bid, Decimal("99.0"))
        self.assertEqual(quote.ask, Decimal("100.0"))

    def test_partial_live_quote_followed_by_error_returns_no_quote(self) -> None:
        session = create_official_ibkr_order_session()

        def answer_then_fail(
            req_id: int,
            contract: object,
            generic_ticks: str,
            snapshot: bool,
            regulatory_snapshot: bool,
            options: list[object],
        ) -> None:
            del contract, generic_ticks, snapshot, regulatory_snapshot, options
            session.marketDataType(req_id, 1)
            session.tickPrice(req_id, 2, 100.0, object())
            session.error(req_id, 0, 354, "raw market-data failure")

        with (
            patch.object(session, "reqMarketDataType"),
            patch.object(session, "reqMktData", side_effect=answer_then_fail),
        ):
            quote = session.request_live_quote(resolved(), timeout=0.01)

        self.assertIsNone(quote.market_data_type)
        self.assertIsNone(quote.bid)
        self.assertIsNone(quote.ask)

    def test_incomplete_quote_timeout_discards_partial_callbacks(self) -> None:
        session = create_official_ibkr_order_session()

        def answer_without_end(
            req_id: int,
            contract: object,
            generic_ticks: str,
            snapshot: bool,
            regulatory_snapshot: bool,
            options: list[object],
        ) -> None:
            del contract, generic_ticks, snapshot, regulatory_snapshot, options
            session.marketDataType(req_id, 1)
            session.tickPrice(req_id, 2, 100.0, object())

        with (
            patch.object(session, "reqMarketDataType"),
            patch.object(session, "reqMktData", side_effect=answer_without_end),
        ):
            quote = session.request_live_quote(resolved(), timeout=0)

        self.assertIsNone(quote.market_data_type)
        self.assertIsNone(quote.bid)
        self.assertIsNone(quote.ask)

    def test_invalid_quote_numbers_are_sanitized_to_unavailable(self) -> None:
        session = create_official_ibkr_order_session()

        session.marketDataType(9102, 1)
        session.tickPrice(9102, 1, float("nan"), object())
        session.tickPrice(9102, 2, float("inf"), object())
        session.tickSnapshotEnd(9102)

        self.assertIsNone(session.live_quote.bid)
        self.assertIsNone(session.live_quote.ask)

    def test_managed_accounts_retains_only_count(self) -> None:
        first_account = "DU1111111"
        second_account = "DU2222222"
        session = create_official_ibkr_order_session()

        session.managedAccounts(f"{first_account},{second_account}")

        self.assertTrue(session.wait_for_managed_accounts(0.01))
        self.assertEqual(session.managed_account_count, 2)
        retained_state = repr(vars(session))
        self.assertNotIn(first_account, retained_state)
        self.assertNotIn(second_account, retained_state)

    def test_next_valid_id_makes_connection_ready_without_req_ids(self) -> None:
        session = create_official_ibkr_order_session()

        session.nextValidId(7001)

        self.assertTrue(session.wait_until_connected(0.01))
        self.assertEqual(session.next_order_id, 7001)

    def test_market_submit_builds_transmitted_order_without_account_or_limit(self) -> None:
        session = create_official_ibkr_order_session()
        captured: list[tuple[int, object, object]] = []

        def capture(order_id: int, contract: object, order: object) -> None:
            captured.append((order_id, contract, order))

        with patch.object(session, "placeOrder", side_effect=capture):
            session.submit_order(
                7001,
                resolved(),
                OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET),
                "preview-1",
            )

        order_id, contract, order = captured[0]
        self.assertEqual(order_id, 7001)
        self.assertEqual(contract.symbol, "AAPL")
        self.assertEqual(order.action, "BUY")
        self.assertEqual(order.orderType, "MKT")
        self.assertEqual(order.totalQuantity, Decimal("1"))
        self.assertEqual(order.orderRef, "preview-1")
        self.assertTrue(order.transmit)
        self.assertEqual(order.account, "")
        self.assertGreater(float(order.lmtPrice), 1e307)

    def test_limit_sell_submit_maps_entered_limit(self) -> None:
        session = create_official_ibkr_order_session()
        captured: list[object] = []

        with patch.object(
            session,
            "placeOrder",
            side_effect=lambda order_id, contract, order: captured.append(order),
        ):
            session.submit_order(
                7002,
                resolved("QQQ"),
                OrderIntent(
                    "QQQ",
                    OrderSide.SELL,
                    OrderType.LIMIT,
                    quantity=2,
                    limit_price=Decimal("499.25"),
                ),
                "preview-2",
            )

        order = captured[0]
        self.assertEqual(order.action, "SELL")
        self.assertEqual(order.orderType, "LMT")
        self.assertEqual(order.totalQuantity, Decimal("2"))
        self.assertEqual(order.lmtPrice, 499.25)

    def test_order_status_callback_returns_only_sanitized_fields(self) -> None:
        session = create_official_ibkr_order_session()
        with patch.object(session, "placeOrder"):
            session.submit_order(
                7001,
                resolved(),
                OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET),
                "preview-1",
            )

        session.orderStatus(
            7001,
            "Filled",
            Decimal("1"),
            Decimal("0"),
            100.25,
            999999,
            0,
            100.25,
            10,
            "sensitive held detail",
            0.0,
        )
        update = session.wait_for_order_update(7001, 0.01)

        self.assertEqual(update.broker_status, "Filled")
        self.assertEqual(update.filled_quantity, Decimal("1"))
        self.assertEqual(update.remaining_quantity, Decimal("0"))
        self.assertEqual(update.average_fill_price, Decimal("100.25"))
        sanitized = repr(update)
        self.assertNotIn("999999", sanitized)
        self.assertNotIn("sensitive held detail", sanitized)

    def test_open_order_callback_discards_account_and_contract_objects(self) -> None:
        sentinel_account = "DU1234567"
        session = create_official_ibkr_order_session()
        with patch.object(session, "placeOrder"):
            session.submit_order(
                7001,
                resolved(),
                OrderIntent("AAPL", OrderSide.BUY, OrderType.MARKET),
                "preview-1",
            )

        session.openOrder(
            7001,
            SimpleNamespace(symbol="AAPL"),
            SimpleNamespace(
                account=sentinel_account,
                totalQuantity=Decimal("1"),
            ),
            SimpleNamespace(status="Submitted"),
        )

        update = session.wait_for_order_update(7001, 0.01)
        self.assertEqual(update.broker_status, "Submitted")
        self.assertNotIn(sentinel_account, repr(vars(session)))
        self.assertNotIn(sentinel_account, repr(update))

    def test_rejection_and_cancel_errors_discard_raw_payloads(self) -> None:
        sentinel = "DU1234567 raw reject detail"
        cases = ((201, True, "Inactive"), (202, False, "Cancelled"))

        for error_code, rejected, expected_status in cases:
            with self.subTest(error_code=error_code):
                session = create_official_ibkr_order_session()
                with patch.object(session, "placeOrder"):
                    session.submit_order(
                        7001,
                        resolved(),
                        OrderIntent(
                            "AAPL", OrderSide.BUY, OrderType.MARKET
                        ),
                        "preview-1",
                    )
                session.error(7001, 0, error_code, sentinel, sentinel)

                update = session.wait_for_order_update(7001, 0.01)

                self.assertEqual(update.broker_status, expected_status)
                self.assertEqual(update.rejected, rejected)
                self.assertNotIn(sentinel, repr(vars(session)))
                self.assertNotIn(sentinel, repr(update))

    def test_cleanup_cancels_only_an_incomplete_market_snapshot(self) -> None:
        session = create_official_ibkr_order_session()
        session._quote_requested = True

        with (
            patch.object(session, "isConnected", return_value=True),
            patch.object(session, "cancelMktData") as cancel_market_data,
            patch.object(session, "disconnect") as disconnect,
        ):
            session.close()

        cancel_market_data.assert_called_once_with(9102)
        disconnect.assert_called_once_with()

    def test_disables_raw_ibapi_logging(self) -> None:
        sentinel = "DU1234567-sensitive-order-field"
        decoder_logger = logging.getLogger("ibapi.decoder")
        original_state = (
            decoder_logger.level,
            decoder_logger.disabled,
            decoder_logger.propagate,
            list(decoder_logger.handlers),
        )

        def restore() -> None:
            decoder_logger.setLevel(original_state[0])
            decoder_logger.disabled = original_state[1]
            decoder_logger.propagate = original_state[2]
            decoder_logger.handlers[:] = original_state[3]

        self.addCleanup(restore)
        captured = StringIO()
        decoder_logger.handlers[:] = [logging.StreamHandler(captured)]
        decoder_logger.disabled = False
        decoder_logger.propagate = False
        decoder_logger.setLevel(logging.DEBUG)

        create_official_ibkr_order_session()
        decoder_logger.debug("decoded order account: %s", sentinel)

        self.assertNotIn(sentinel, captured.getvalue())

    def test_missing_official_package_has_fixed_setup_guidance(self) -> None:
        def missing_module(name: str):
            raise ModuleNotFoundError(name)

        with self.assertRaises(OfficialIbapiUnavailableError) as raised:
            create_official_ibkr_order_session(module_loader=missing_module)

        self.assertIn("official IBKR TWS API", str(raised.exception))
        self.assertNotIn("pip install ibapi", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)


class IbkrOrderSessionSourceSafetyTests(unittest.TestCase):
    def test_order_adapter_has_only_approved_order_api_surface(self) -> None:
        source_path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "private_quant"
            / "broker"
            / "ibkr_order_session.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        called_methods = [
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]

        self.assertEqual(called_methods.count("placeOrder"), 1)
        self.assertTrue(
            set(called_methods).isdisjoint(
                {
                    "reqIds",
                    "cancelOrder",
                    "reqGlobalCancel",
                    "reqOpenOrders",
                    "reqAllOpenOrders",
                    "reqCompletedOrders",
                }
            )
        )
        assigned_attributes = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        self.assertNotIn("whatIf", assigned_attributes)


if __name__ == "__main__":
    unittest.main()
