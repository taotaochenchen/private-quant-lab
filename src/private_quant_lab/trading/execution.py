"""模拟盘执行引擎：把风控复核后的交易计划转换为 PaperAccount 上的真实模拟订单。

职责边界：
- 仓位百分比换算成 A 股整手股数（买入 100 股整数倍）。
- 用参考价生成限价单，并显式注入模拟成交事件。
- 把结果映射回工作流需要的 OrderExecution / PositionSnapshot 结构。

不连接券商、不给模型成交决定权；参考价是确定性 mock，不是真实行情。
"""

from private_quant_lab.domain import OrderExecution, PositionSnapshot, utc_now
from private_quant_lab.trading.paper import PaperAccount


def reference_price(symbol):
    """确定性参考价：与 mock market_snapshot 使用同一公式，便于离线联调。"""
    score = sum(ord(char) for char in str(symbol).upper())
    return round(80 + score % 420 + (score % 17) / 10, 2)


class PaperExecutionEngine:
    """把复核后的计划在 PaperAccount 上落地，产出执行与持仓快照。"""

    def __init__(self, cash, trade_date, prices=None):
        self.total_equity = float(cash)
        self.account = PaperAccount(str(cash), trade_date)
        self.prices = dict(prices or {})

    def price_for(self, symbol):
        value = self.prices.get(symbol)
        if value is not None:
            return float(value)
        return reference_price(symbol)

    def size(self, pct, symbol, side):
        """把仓位百分比换算成整手股数；不可成交时返回 0。"""
        price = self.price_for(symbol)
        if price <= 0:
            return 0
        value = self.total_equity * float(pct) / 100.0
        shares = int(value / price)
        if side == "buy":
            shares = (shares // 100) * 100
        return shares

    def execute_order(self, index, instruction, plan):
        """提交限价单并注入模拟成交，返回 OrderExecution。"""
        symbol = instruction.symbol
        quantity = instruction.quantity
        price = self.price_for(symbol)
        client_id = "client_{0:03d}".format(index)
        fill_id = "fill_{0:03d}".format(index)
        limit_price = "{:.2f}".format(price)
        try:
            order = self.account.submit(client_id, symbol, instruction.side, quantity, limit_price)
        except ValueError as exc:
            return OrderExecution(
                execution_id="exec_{0:03d}".format(index),
                order_id=instruction.order_id,
                symbol=symbol,
                side=instruction.side,
                quantity=quantity,
                order_type=instruction.order_type,
                status="rejected",
                submitted_at=utc_now(),
                filled_quantity=0,
                avg_price=None,
                raw_result={"error": str(exc)},
            )
        try:
            filled = self.account.fill(order["order_id"], fill_id, quantity, limit_price)
        except ValueError:
            filled = order
        return OrderExecution(
            execution_id="exec_{0:03d}".format(index),
            order_id=order["order_id"],
            symbol=symbol,
            side=instruction.side,
            quantity=quantity,
            order_type=instruction.order_type,
            status=filled["status"],
            submitted_at=utc_now(),
            filled_quantity=filled["filled_quantity"],
            avg_price=float(price) if filled["filled_quantity"] else None,
            raw_result={"fill_id": fill_id, "limit_price": limit_price},
        )

    def positions(self, name_map=None):
        """从账户快照推导当前持仓，返回 PositionSnapshot 列表。"""
        name_map = name_map or {}
        result = []
        for symbol, position in self.account.snapshot()["positions"].items():
            if position["total"] <= 0:
                continue
            price = self.price_for(symbol)
            value = position["total"] * price
            weight = round(value / self.total_equity * 100, 2) if self.total_equity > 0 else 0
            result.append(
                PositionSnapshot(
                    symbol=symbol,
                    name=name_map.get(symbol, symbol),
                    quantity=position["total"],
                    market_value=round(value, 2),
                    weight="{0:g}%".format(weight),
                    unrealized_pnl_pct=0,
                )
            )
        return result

    def snapshot(self):
        return self.account.snapshot()
