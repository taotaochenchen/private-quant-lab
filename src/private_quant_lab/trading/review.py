"""收盘复盘引擎：基于当次模拟盘的执行与账户快照生成复盘报告。

复盘指标与边界：
- ``order_fill_rate``：成交/提交订单数，来自真实模拟成交。
- ``risk_effectiveness``：根据风控事件判定 blocked / normal / error。
- ``industry_alpha`` / ``stock_alpha``：需要真实行情基准，mock 环境置 0 并注明未计算。
- 胜率、盈亏比、最大回撤：需要跨日成交历史，单次运行不计算，注明未计算。
"""

from private_quant_lab.domain import ReviewReport, utc_now


class ReviewEngine:
    def build(self, report, executions, risk_events, intraday_alerts, account_snapshot=None):
        filled = [item for item in executions if item.status in ("filled", "partially_filled")]
        rejected = [item for item in executions if item.status == "rejected"]
        fill_rate = len(filled) / len(executions) if executions else 0
        blocked = any(event.level == "critical" or event.action == "block_orders" for event in risk_events)
        if blocked:
            risk_effectiveness = "blocked"
        elif rejected:
            risk_effectiveness = "error"
        else:
            risk_effectiveness = "normal"

        notes = [
            "复盘基于 mock 行情和模拟订单生成，不代表真实收益。",
            "最终建议数量：{0}".format(len(report.get("trade_plan") or [])),
            "盘中监控事件：{0}".format(len(intraday_alerts)),
            "行业/个股 alpha 与胜率、盈亏比、最大回撤需真实行情与跨日历史，本次不计算。",
        ]
        if executions:
            notes.insert(2, "订单成交率：{0:.1%}（{1}/{2}）".format(fill_rate, len(filled), len(executions)))
        if account_snapshot:
            cash = account_snapshot.get("cash")
            held = [symbol for symbol, position in (account_snapshot.get("positions") or {}).items()
                    if position.get("total", 0) > 0]
            notes.append("账户现金 {0}，持仓 {1} 只{2}。".format(
                cash, len(held), "（{0}）".format(", ".join(held)) if held else ""))
        if blocked:
            notes.append("风控阻断了订单，优先保护模拟账户。")
        if rejected:
            notes.append("有 {0} 笔订单被拒绝，请检查标的代码或资金。".format(len(rejected)))
        return ReviewReport(
            review_id="review_{0}".format(utc_now().replace(":", "").replace("-", "")),
            status="completed",
            generated_at=utc_now(),
            industry_alpha=0,
            stock_alpha=0,
            order_fill_rate=round(fill_rate, 4),
            risk_effectiveness=risk_effectiveness,
            notes=notes,
        )
