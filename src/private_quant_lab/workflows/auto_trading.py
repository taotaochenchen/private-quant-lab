"""Autonomous paper-trading workflow for the v2 MVP."""

import json
from datetime import date

from private_quant_lab.domain import (
    AutoTradingRun,
    IntradayAlert,
    OrderInstruction,
    ReviewReport,
    RiskEvent,
    empty_auto_trading_run,
    trading_schema,
    utc_now,
)
from private_quant_lab.risk import RiskEngine
from private_quant_lab.trading import IntradayMonitor, PaperExecutionEngine, ReviewEngine
from private_quant_lab.workflows.pre_market import DEFAULT_PRE_MARKET_TASK, PreMarketWorkflow


DEFAULT_AUTO_TRADING_TASK = (
    "请运行一次全自动模拟盘流程：先生成盘前报告，再根据风控审核把可执行计划转换为模拟订单，"
    "最后输出订单执行、持仓快照和风控事件。只允许模拟盘，不允许实盘。"
)

DEFAULT_PAPER_CASH = "1000000"


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
        market_data=None,
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
            account_state=account_state,
            on_event=on_event,
            market_data=market_data,
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


def build_auto_trading_run(report, account_state=None, on_event=None, market_data=None):
    """把盘前报告经风控复核后，用 PaperAccount 落地为真实模拟订单。"""

    account_state = account_state or {}
    decision = RiskEngine().review(report, account_state=account_state, market_data=market_data)
    orders = []
    executions = []
    positions = []
    events = list(decision.events)
    account_snapshot = None

    if not decision.blocked:
        cash = account_state.get("cash") or DEFAULT_PAPER_CASH
        trade_date = account_state.get("trade_date") or report.get("report_date") or date.today().isoformat()
        prices = _prices_from_market_data(market_data)
        engine = PaperExecutionEngine(cash, trade_date, prices=prices)
        name_map = {}
        for index, reviewed in enumerate(decision.reviewed_plans, start=1):
            plan = reviewed.plan
            symbol = str(plan.get("symbol") or "UNKNOWN")
            name_map[symbol] = str(plan.get("name") or plan.get("symbol") or "UNKNOWN")
            if reviewed.skip:
                if not _has_skip_event(events, symbol):
                    events.append(_skip_event(index, plan, reviewed.skip_reason or "计划仓位为 0，自动跳过订单。"))
                continue
            quantity = engine.size(reviewed.reviewed_position_pct, symbol, plan.get("side"))
            if quantity <= 0:
                events.append(_skip_event(index, plan, "可用资金不足或整手约束下无法成交，自动跳过。"))
                continue
            instruction = OrderInstruction(
                order_id="paper_plan_{0:03d}".format(index),
                symbol=symbol,
                name=name_map[symbol],
                side=str(plan.get("side")),
                quantity=quantity,
                order_type="limit",
                time_in_force="day",
                source_plan_ref="trade_plan[{0}]".format(index - 1),
                trigger_conditions=plan.get("buy_conditions") or [],
                stop_loss_price=reviewed.stop_loss_price,
                take_profit_price=reviewed.take_profit_price,
            )
            orders.append(instruction)
            if on_event is not None:
                on_event("paper_order_started", {"order": instruction.to_dict()})
            execution = engine.execute_order(index, instruction, plan)
            executions.append(execution)
            if on_event is not None:
                on_event("paper_order_finished", {"execution": execution.to_dict()})
        positions = engine.positions(name_map=name_map)
        account_snapshot = engine.snapshot()
        if on_event is not None:
            on_event("account_snapshot", {"snapshot": account_snapshot})

    for event in events:
        if on_event is not None:
            on_event("risk_event", {"event": event.to_dict()})

    status = "blocked" if decision.blocked else "completed"
    if executions and any(item.status not in ("filled", "partially_filled") for item in executions):
        status = "error"
    intraday_alerts = build_intraday_alerts(positions, orders=orders, risk_events=events,
                                            current_prices=_prices_from_market_data(market_data))
    review_report = build_review_report(report, executions, events, intraday_alerts,
                                        account_snapshot=account_snapshot)
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


def _prices_from_market_data(market_data):
    result = {}
    for symbol, md in (market_data or {}).items():
        if isinstance(md, dict) and md.get("last_price") is not None:
            result[symbol] = md["last_price"]
    return result


def build_intraday_alerts(positions, orders=None, risk_events=None, current_prices=None):
    """对模拟持仓做盘中触发条件评估（止损/止盈/观察/风控熔断）。"""

    return IntradayMonitor(current_prices).evaluate(positions, orders=orders, risk_events=risk_events)


def build_review_report(report, executions, risk_events, intraday_alerts, account_snapshot=None):
    """对当次模拟盘做收盘复盘。"""

    return ReviewEngine().build(report, executions, risk_events, intraday_alerts,
                                account_snapshot=account_snapshot)


def _summary(status, orders, executions, events, intraday_alerts, review_report):
    if status == "blocked":
        return "风控未放行，本次自动模拟盘未提交订单；已生成盘中监控和收盘复盘记录。"
    return "自动模拟盘完成：生成 {0} 条订单指令，成交 {1} 条，风控事件 {2} 条，盘中事件 {3} 条，复盘状态 {4}。".format(
        len(orders),
        len([item for item in executions if item.status in ("filled", "partially_filled")]),
        len(events),
        len(intraday_alerts),
        review_report.status,
    )


def auto_trading_schema():
    """Public schema helper for the web layer."""

    return trading_schema()
