"""盘中监控引擎：对持仓的触发条件做确定性评估，产出盘中事件。

当前 mock 行情的"现价"由调用方注入（``current_prices``），缺失时用确定性参考价。
止损/止盈阈值取自订单指令（风控/执行层已计算），逐项评估：
- 现价跌破止损 → ``stop_loss`` 事件。
- 现价突破止盈 → ``take_profit`` 事件。
- 否则保持观察 → ``watching`` 事件。
- 存在关键风控事件 → ``block_new_orders`` 事件。

不调用模型、不实际下单；仅产出可审计的盘中监控记录。
"""

from private_quant_lab.domain import IntradayAlert, utc_now
from private_quant_lab.trading.execution import reference_price


class IntradayMonitor:
    def __init__(self, current_prices=None):
        self.current_prices = dict(current_prices or {})

    def evaluate(self, positions, orders=None, risk_events=None):
        """评估持仓触发条件，返回 IntradayAlert 列表。"""
        if not positions:
            return [
                IntradayAlert(
                    alert_id="alert_no_position",
                    condition_ref="no_active_position",
                    symbol="",
                    status="skipped",
                    action="none",
                    triggered_at=utc_now(),
                    actual_value=0,
                    message="无模拟持仓，盘中监控保持观察。",
                )
            ]
        alerts = []
        orders_by_symbol = {order.symbol: order for order in (orders or []) if getattr(order, "symbol", None)}
        for index, position in enumerate(positions, start=1):
            order = orders_by_symbol.get(position.symbol)
            current = self.current_prices.get(position.symbol) or reference_price(position.symbol)
            stop_loss = getattr(order, "stop_loss_price", None) if order else None
            take_profit = getattr(order, "take_profit_price", None) if order else None
            if stop_loss is not None and current <= stop_loss:
                alerts.append(self._alert(
                    index, "stop_loss", position.symbol, "triggered", "stop_loss", current,
                    "{0} 现价 {1} 触发止损 {2}。".format(position.symbol, current, stop_loss)))
            elif take_profit is not None and current >= take_profit:
                alerts.append(self._alert(
                    index, "take_profit", position.symbol, "triggered", "take_profit", current,
                    "{0} 现价 {1} 触发止盈 {2}。".format(position.symbol, current, take_profit)))
            else:
                alerts.append(self._alert(
                    index, "hold", position.symbol, "watching", "hold", current,
                    "{0} 模拟持仓正常，继续保持监控。".format(position.symbol)))
        if any(event.level == "critical" for event in (risk_events or [])):
            alerts.append(IntradayAlert(
                alert_id="alert_risk_hold",
                condition_ref="risk_circuit_breaker",
                symbol="",
                status="triggered",
                action="block_new_orders",
                triggered_at=utc_now(),
                actual_value=1,
                message="检测到关键风控事件，盘中禁止新增模拟订单。",
            ))
        return alerts

    @staticmethod
    def _alert(index, condition_ref, symbol, status, action, actual_value, message):
        return IntradayAlert(
            alert_id="alert_{0:03d}".format(index),
            condition_ref=condition_ref,
            symbol=symbol,
            status=status,
            action=action,
            triggered_at=utc_now(),
            actual_value=actual_value,
            message=message,
        )
