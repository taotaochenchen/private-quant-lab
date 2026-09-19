"""Autonomous paper-trading workflow for the v2 MVP."""

import json

from private_quant_lab.domain import (
    AutoTradingRun,
    IntradayAlert,
    OrderExecution,
    OrderInstruction,
    PositionSnapshot,
    ReviewReport,
    RiskEvent,
    empty_auto_trading_run,
    trading_schema,
    utc_now,
)
from private_quant_lab.risk import RiskEngine
from private_quant_lab.workflows.pre_market import DEFAULT_PRE_MARKET_TASK, PreMarketWorkflow


DEFAULT_AUTO_TRADING_TASK = (
    "请运行一次全自动模拟盘流程：先生成盘前报告，再根据风控审核把可执行计划转换为模拟订单，"
    "最后输出订单执行、持仓快照和风控事件。只允许模拟盘，不允许实盘。"
)


class AutoTradingWorkflow:
    """Run pre-market analysis and execute eligible paper orders."""

    def __init__(self, model, tool_environment, max_steps=8):
        self.model = model
        self.tool_environment = tool_environment
        self.max_steps = max_steps

    def run(
        self,
        task=None,
        account_state=None,
        temperature=0,
        max_tokens=3000,
        model_extra_body=None,
        system_prompt=None,
        agent_system_prompts=None,
        on_event=None,
    ):
        if on_event is not None:
            on_event("auto_trade_status", {"status": "running", "message": "盘前分析启动"})

        pre_market = PreMarketWorkflow(self.model, self.tool_environment, max_steps=self.max_steps)
        pre_market_result = pre_market.run(
            task=task or DEFAULT_PRE_MARKET_TASK,
            temperature=temperature,
            max_tokens=max_tokens,
            model_extra_body=model_extra_body,
            system_prompt=system_prompt,
            agent_system_prompts=agent_system_prompts,
            on_event=on_event,
        )

        if on_event is not None:
            on_event("auto_trade_status", {"status": "running", "message": "风控审核与模拟订单生成"})

        run = build_auto_trading_run(
            pre_market_result.report,
            self.tool_environment,
            account_state=account_state,
            on_event=on_event,
        )
        final = json.dumps(run, ensure_ascii=False, sort_keys=True)
        if on_event is not None:
            on_event("auto_trade_result", {"run": run})
        return AutoTradingWorkflowResult(final=final, trace=pre_market_result.trace, report=pre_market_result.report, run=run)


class AutoTradingWorkflowResult:
    def __init__(self, final, trace, report, run):
        self.final = final
        self.trace = trace
        self.report = report
        self.run = run


def build_auto_trading_run(report, tool_environment, account_state=None, on_event=None, market_data=None):
    """Convert a PreMarketReport into simulated order executions via RiskEngine."""

    account_state = account_state or {}
    decision = RiskEngine().review(report, account_state=account_state, market_data=market_data)
    orders = []
    executions = []
    positions = []
    events = list(decision.events)

    if not decision.blocked:
        for index, reviewed in enumerate(decision.reviewed_plans, start=1):
            plan = reviewed.plan
            symbol = str(plan.get("symbol") or "UNKNOWN")
            if reviewed.skip:
                if not _has_skip_event(events, symbol):
                    events.append(_skip_event(index, plan, reviewed.skip_reason or "计划仓位为 0，自动跳过订单。"))
                continue
            quantity = _quantity_from_percent(reviewed.reviewed_position_pct)
            if quantity <= 0:
                events.append(_skip_event(index, plan, "计划仓位为 0，自动跳过订单。"))
                continue
            instruction = OrderInstruction(
                order_id="paper_plan_{0:03d}".format(index),
                symbol=symbol,
                name=str(plan.get("name") or plan.get("symbol") or "UNKNOWN"),
                side=str(plan.get("side")),
                quantity=quantity,
                order_type="market",
                time_in_force="day",
                source_plan_ref="trade_plan[{0}]".format(index - 1),
                trigger_conditions=plan.get("buy_conditions") or [],
                stop_loss_price=reviewed.stop_loss_price,
                take_profit_price=reviewed.take_profit_price,
            )
            orders.append(instruction)
            if on_event is not None:
                on_event("paper_order_started", {"order": instruction.to_dict()})

            tool_result = tool_environment.run(
                "paper_order",
                {
                    "symbol": instruction.symbol,
                    "side": instruction.side,
                    "quantity": instruction.quantity,
                    "order_type": instruction.order_type,
                },
            )
            raw = tool_result.output
            execution = OrderExecution(
                execution_id="exec_{0:03d}".format(index),
                order_id=instruction.order_id,
                symbol=instruction.symbol,
                side=instruction.side,
                quantity=instruction.quantity,
                order_type=instruction.order_type,
                status=str(raw.get("status") or "unknown"),
                submitted_at=utc_now(),
                filled_quantity=instruction.quantity if raw.get("status") == "accepted" else 0,
                avg_price=None,
                raw_result=raw,
            )
            executions.append(execution)
            if execution.status == "accepted":
                positions.append(
                    PositionSnapshot(
                        symbol=instruction.symbol,
                        name=instruction.name,
                        quantity=instruction.quantity if instruction.side == "buy" else -instruction.quantity,
                        market_value=0,
                        weight="{0:g}%".format(reviewed.reviewed_position_pct),
                        unrealized_pnl_pct=0,
                    )
                )
            if on_event is not None:
                on_event("paper_order_finished", {"execution": execution.to_dict()})

    for event in events:
        if on_event is not None:
            on_event("risk_event", {"event": event.to_dict()})

    status = "blocked" if decision.blocked else "completed"
    if executions and any(item.status != "accepted" for item in executions):
        status = "error"
    intraday_alerts = build_intraday_alerts(report, positions, events)
    review_report = build_review_report(report, executions, events, intraday_alerts)
    for alert in intraday_alerts:
        if on_event is not None:
            on_event("intraday_alert", {"alert": alert.to_dict()})
    if on_event is not None:
        on_event("review_report", {"review": review_report.to_dict()})
    summary = _summary(status, orders, executions, events, intraday_alerts, review_report)
    return AutoTradingRun(
        run_mode="paper",
        status=status,
        pre_market_report=report,
        order_instructions=orders,
        executions=executions,
        risk_events=events,
        positions=positions,
        intraday_alerts=intraday_alerts,
        review_report=review_report,
        summary=summary,
    ).to_dict()


def build_empty_auto_trading_run():
    """Return an empty paper-trading run dict for APIs."""

    return empty_auto_trading_run().to_dict()


def _skip_event(index, plan, message):
    return RiskEvent(
        event_id="risk_skip_{0:03d}".format(index),
        type="order_skipped",
        level="info",
        status="skipped",
        message=message,
        action="skip_order",
        timestamp=utc_now(),
        related_order_id=str(plan.get("symbol") or ""),
    )


def _has_skip_event(events, symbol):
    return any(event.related_order_id == symbol and event.action == "skip_order" for event in events)


def _quantity_from_percent(percent):
    return max(0, round(float(percent) * 10, 2))


def build_intraday_alerts(report, positions, risk_events):
    """Build mocked intraday monitoring alerts from the generated plan."""

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
    trade_plan = {item.get("symbol"): item for item in report.get("trade_plan") or []}
    for index, position in enumerate(positions, start=1):
        plan = trade_plan.get(position.symbol) or {}
        condition = (plan.get("buy_conditions") or [{}])[0]
        alerts.append(
            IntradayAlert(
                alert_id="alert_{0:03d}".format(index),
                condition_ref=condition.get("condition_id") or "entry_condition",
                symbol=position.symbol,
                status="triggered",
                action="hold_after_entry",
                triggered_at=utc_now(),
                actual_value=1.2,
                message="{0} 模拟触发入场后进入持仓监控。".format(position.symbol),
            )
        )
    if any(event.level == "critical" for event in risk_events):
        alerts.append(
            IntradayAlert(
                alert_id="alert_risk_hold",
                condition_ref="risk_circuit_breaker",
                symbol="",
                status="triggered",
                action="block_new_orders",
                triggered_at=utc_now(),
                actual_value=1,
                message="检测到关键风控事件，盘中禁止新增模拟订单。",
            )
        )
    return alerts


def build_review_report(report, executions, risk_events, intraday_alerts):
    """Build a mocked end-of-day review for the simulated workflow."""

    accepted = len([item for item in executions if item.status == "accepted"])
    fill_rate = accepted / len(executions) if executions else 0
    blocked = any(event.level == "critical" or event.action == "block_orders" for event in risk_events)
    notes = [
        "复盘基于 mock 行情和模拟订单生成，不代表真实收益。",
        "最终建议数量：{0}".format(len(report.get("trade_plan") or [])),
        "盘中监控事件：{0}".format(len(intraday_alerts)),
    ]
    if blocked:
        notes.append("风控阻断了订单，优先保护模拟账户。")
    return ReviewReport(
        review_id="review_{0}".format(utc_now().replace(":", "").replace("-", "")),
        status="completed",
        generated_at=utc_now(),
        industry_alpha=0.8 if accepted else 0,
        stock_alpha=1.1 if accepted else 0,
        order_fill_rate=round(fill_rate, 4),
        risk_effectiveness="blocked" if blocked else "normal",
        notes=notes,
    )


def _summary(status, orders, executions, events, intraday_alerts, review_report):
    if status == "blocked":
        return "风控未放行，本次自动模拟盘未提交订单；已生成盘中监控和收盘复盘记录。"
    return "自动模拟盘完成：生成 {0} 条订单指令，接受 {1} 条，风控事件 {2} 条，盘中事件 {3} 条，复盘状态 {4}。".format(
        len(orders),
        len([item for item in executions if item.status == "accepted"]),
        len(events),
        len(intraday_alerts),
        review_report.status,
    )


def auto_trading_schema():
    """Public schema helper for the web layer."""

    return trading_schema()
