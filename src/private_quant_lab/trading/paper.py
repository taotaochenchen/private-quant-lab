"""内存模拟账户：委托受理不等于成交，成交通过独立测试事件注入。

仅用于普通沪深主板股票限价单；其他板块、费用、交易时段与行情撮合尚未覆盖。
不连接券商，不向 LLM 提供成交决定权。
"""

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from threading import RLock
from uuid import uuid4


def money(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid money") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("money must be finite and nonnegative")
    return result


class PaperAccount:
    """独立模拟账户；snapshot 为副本，所有状态变更在锁内完成。"""

    def __init__(self, cash, trade_date, positions=None):
        self.cash = money(cash)
        self.frozen_cash = Decimal(0)
        self.trade_date = date.fromisoformat(trade_date)
        self.positions = {}
        for symbol, quantity in (positions or {}).items():
            self._symbol(symbol)
            self._quantity(quantity)
            self.positions[symbol] = {"total": quantity, "available": quantity, "frozen": 0}
        self.orders = {}
        self.client_ids = {}
        self.fill_ids = set()
        self.lock = RLock()

    @staticmethod
    def _symbol(symbol):
        if not isinstance(symbol, str) or not re.fullmatch(r"(?:60[0135]\d{3}\.SH|00[0123]\d{3}\.SZ)", symbol):
            raise ValueError("only ordinary Shanghai/Shenzhen main-board stock codes supported")

    @staticmethod
    def _quantity(quantity):
        if type(quantity) is not int or quantity <= 0:
            raise ValueError("quantity must be a positive integer")

    def submit(self, client_order_id, symbol, side, quantity, limit_price):
        """冻结现金或可卖股数；相同 client_order_id 重试不重复下单。"""
        self._symbol(symbol)
        self._quantity(quantity)
        price = money(limit_price)
        if price <= 0 or price % Decimal("0.01"):
            raise ValueError("limit price must be positive and in 0.01 increments")
        if side not in ("buy", "sell") or not isinstance(client_order_id, str) or not client_order_id.strip():
            raise ValueError("invalid side or client_order_id")
        signature = (symbol, side, quantity, str(price.normalize()))
        with self.lock:
            if client_order_id in self.client_ids:
                order_id, previous = self.client_ids[client_order_id]
                if previous != signature:
                    raise ValueError("client_order_id reused with different order")
                return deepcopy(self.orders[order_id])
            position = self.positions.get(symbol, {"total": 0, "available": 0, "frozen": 0})
            if side == "buy":
                if quantity % 100:
                    raise ValueError("buy quantity must be a multiple of 100")
                if self.cash - self.frozen_cash < price * quantity:
                    raise ValueError("insufficient available cash")
                self.frozen_cash += price * quantity
            else:
                if quantity > position["available"]:
                    raise ValueError("insufficient sellable quantity (including unsettled buys)")
                if quantity % 100 and quantity != position["available"]:
                    raise ValueError("odd-lot sale must clear remaining sellable shares")
                position["available"] -= quantity
                position["frozen"] += quantity
            order_id = "paper-" + uuid4().hex
            order = dict(order_id=order_id, client_order_id=client_order_id, symbol=symbol, side=side,
                         quantity=quantity, limit_price=str(price), filled_quantity=0,
                         status="accepted", mode="paper", trade_date=self.trade_date.isoformat())
            self.orders[order_id] = order
            self.client_ids[client_order_id] = (order_id, signature)
            return deepcopy(order)

    def fill(self, order_id, fill_id, quantity, price):
        """显式注入模拟成交事件；同一成交 ID 不能重复结算。"""
        self._quantity(quantity)
        price = money(price)
        if price <= 0 or price % Decimal("0.01") or not isinstance(fill_id, str) or not fill_id:
            raise ValueError("invalid fill price or id")
        with self.lock:
            if fill_id in self.fill_ids:
                raise ValueError("duplicate fill_id")
            order = self.orders[order_id]
            if order["status"] not in ("accepted", "partially_filled") or quantity > order["quantity"] - order["filled_quantity"]:
                raise ValueError("order not fillable or excessive fill quantity")
            limit = money(order["limit_price"])
            if (order["side"] == "buy" and price > limit) or (order["side"] == "sell" and price < limit):
                raise ValueError("fill violates limit price")
            position = self.positions.setdefault(order["symbol"], {"total": 0, "available": 0, "frozen": 0})
            if order["side"] == "buy":
                self.frozen_cash -= limit * quantity
                self.cash -= price * quantity
                position["total"] += quantity
            else:
                position["total"] -= quantity
                position["frozen"] -= quantity
                self.cash += price * quantity
            order["filled_quantity"] += quantity
            order["status"] = "filled" if order["filled_quantity"] == order["quantity"] else "partially_filled"
            self.fill_ids.add(fill_id)
            return deepcopy(order)

    def cancel(self, order_id):
        """撤销未成交余量，已成交部分保留。"""
        with self.lock:
            order = self.orders[order_id]
            if order["status"] == "cancelled":
                return deepcopy(order)
            if order["status"] not in ("accepted", "partially_filled"):
                raise ValueError("order is not cancellable")
            remaining = order["quantity"] - order["filled_quantity"]
            if order["side"] == "buy":
                self.frozen_cash -= money(order["limit_price"]) * remaining
            else:
                position = self.positions[order["symbol"]]
                position["available"] += remaining
                position["frozen"] -= remaining
            order["status"] = "cancelled"
            return deepcopy(order)

    def settle_to(self, next_trade_date):
        """模拟测试推进交易日；调用方必须提供已验证的下一交易日，不按自然日自动解锁。"""
        next_day = date.fromisoformat(next_trade_date)
        with self.lock:
            if next_day <= self.trade_date:
                raise ValueError("next trade date must increase")
            for order in list(self.orders.values()):
                if order["status"] in ("accepted", "partially_filled"):
                    self.cancel(order["order_id"])
            for position in self.positions.values():
                position["available"] = position["total"]
            self.trade_date = next_day

    def snapshot(self):
        with self.lock:
            return dict(mode="paper", trade_date=self.trade_date.isoformat(), cash=str(self.cash),
                        available_cash=str(self.cash - self.frozen_cash), frozen_cash=str(self.frozen_cash),
                        positions=deepcopy(self.positions), orders=deepcopy(list(self.orders.values())),
                        fees_included=False)
