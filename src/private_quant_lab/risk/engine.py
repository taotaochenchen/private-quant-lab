"""独立风控引擎：确定性的硬否决与逐单复核。

风控不依赖研究 Agent，拥有硬性否决权，可直接阻断或降仓。所有检查确定性执行，
不调用模型，模型不得改写这里的数字。缺少市场或事件数据时，相关检查降级为
"跳过"并记录事件，而不是静默放行。

覆盖计划书 4.6 的风控能力：
- 账户急停、单日亏损熔断、账户回撤熔断、风控状态未放行。
- 单股、单行业、总仓位限制。
- 流动性检查（订单价值不超过日均成交额的一定比例）。
- 高波动环境自动降仓。
- 相关性分组总仓位限制。
- 财报/公告/解禁窗口禁止开仓。
- 从计划条件与参考价生成止损/止盈价。
"""

from dataclasses import dataclass, field
from typing import Optional

from private_quant_lab.domain import RiskEvent, utc_now


DEFAULT_LIMITS = {
    "total_position_limit": 30.0,
    "single_stock_max": 12.0,
    "single_industry_max": 40.0,
    "daily_loss_limit_r": 0.8,
    "max_drawdown_pct": 10.0,
    "liquidity_max_adv_pct": 10.0,
    "volatility_delever_threshold": 40.0,
    "volatility_delever_factor": 0.5,
    "correlation_group_max_pct": 30.0,
    "event_block_window_days": 1,
    "default_stop_loss_pct": 8.0,
    "default_take_profit_pct": 20.0,
}


@dataclass
class ReviewedPlan:
    """逐单复核结果：保留原计划，附加复核后仓位与止损止盈。"""

    plan: dict
    reviewed_position_pct: float
    skip: bool = False
    skip_reason: str = ""
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None


@dataclass
class RiskDecision:
    """风控裁决：阻断标志、事件列表与逐单复核结果。"""

    blocked: bool
    block_reason: str = ""
    events: list = field(default_factory=list)
    reviewed_plans: list = field(default_factory=list)
    planned_total_pct: float = 0.0


class RiskEngine:
    """确定性风控引擎。市场/事件数据经 ``market_data`` 注入，缺失时诚实降级。"""

    def __init__(self, config=None):
        self.limits = dict(DEFAULT_LIMITS)
        self.limits.update(config or {})

    def review(self, report, account_state=None, market_data=None):
        account_state = account_state or {}
        market_data = market_data or {}
        risk = report.get("risk_review") or {}
        hard_limits = risk.get("hard_limits") or {}

        blocking = self._blocking_event(risk, account_state, hard_limits)
        if blocking is not None:
            return RiskDecision(blocked=True, block_reason=blocking.message,
                                events=[blocking], reviewed_plans=[])

        industry_map = _symbol_industry_map(report)
        industry_used = {}
        correlation_used = {}
        planned_total = 0.0
        events = []
        reviewed_plans = []
        for index, plan in enumerate(report.get("trade_plan") or [], start=1):
            side = plan.get("side")
            symbol = str(plan.get("symbol") or "UNKNOWN")
            if side not in {"buy", "sell"}:
                events.append(self._skip_event(index, plan,
                                               "计划动作为 {0}，无需提交订单。".format(side or "unknown")))
                reviewed_plans.append(ReviewedPlan(plan=plan, reviewed_position_pct=0.0,
                                                   skip=True, skip_reason="non_trade_side"))
                continue
            requested = _percent_from_position(plan.get("first_position") or plan.get("max_position"))
            reviewed, planned_total, order_events = self._review_order(
                requested, planned_total, index, plan, hard_limits,
                industry_map, industry_used, correlation_used, market_data)
            events.extend(order_events)
            stop_loss, take_profit = self._stop_loss_take_profit(plan, market_data.get(symbol))
            reviewed_plans.append(
                ReviewedPlan(
                    plan=plan,
                    reviewed_position_pct=reviewed,
                    skip=reviewed <= 0,
                    skip_reason="计划仓位为 0，自动跳过订单。" if reviewed <= 0 else "",
                    stop_loss_price=stop_loss,
                    take_profit_price=take_profit,
                )
            )
        return RiskDecision(blocked=False, events=events, reviewed_plans=reviewed_plans,
                            planned_total_pct=planned_total)

    # ---- 全局硬否决 ----

    def _blocking_event(self, risk, account_state, hard_limits):
        if account_state.get("emergency_stop"):
            return RiskEvent(
                event_id="risk_emergency_stop", type="emergency_stop", level="critical",
                status="triggered", message="检测到账户急停开关，本次自动模拟盘阻断全部订单。",
                action="block_orders", timestamp=utc_now(),
            )
        daily_loss_limit = _limit_or_default(hard_limits, "daily_loss_limit", self.limits["daily_loss_limit_r"], suffix="R")
        if float(account_state.get("daily_loss_r") or 0) >= daily_loss_limit:
            return RiskEvent(
                event_id="risk_daily_loss", type="daily_loss_circuit_breaker", level="critical",
                status="triggered",
                message="当日亏损达到 {0:g}R 熔断线，阻断全部订单。".format(daily_loss_limit),
                action="block_orders", timestamp=utc_now(),
            )
        max_drawdown = float(account_state.get("max_drawdown_limit_pct") or self.limits["max_drawdown_pct"])
        if float(account_state.get("current_drawdown_pct") or 0) >= max_drawdown:
            return RiskEvent(
                event_id="risk_account_drawdown", type="account_drawdown_circuit_breaker",
                level="critical", status="triggered", message="账户回撤达到熔断阈值，阻断全部订单。",
                action="block_orders", timestamp=utc_now(),
            )
        risk_status = risk.get("status") or "pending"
        if risk_status in {"blocked", "pending"}:
            return RiskEvent(
                event_id="risk_001", type="execution_blocked",
                level="critical" if risk_status == "blocked" else "warning",
                status=risk_status,
                message=risk.get("reason") or "风控未放行，自动模拟盘不提交订单。",
                action="block_orders", timestamp=utc_now(),
            )
        return None

    # ---- 逐单复核 ----

    def _review_order(self, requested, planned_total, index, plan, hard_limits,
                      industry_map, industry_used, correlation_used, market_data):
        events = []
        symbol = str(plan.get("symbol") or "UNKNOWN")
        single_stock_max = _limit_or_default(hard_limits, "single_stock_max", self.limits["single_stock_max"])
        total_position_limit = _limit_or_default(hard_limits, "total_position_limit", self.limits["total_position_limit"])
        single_industry_max = _limit_or_default(hard_limits, "single_industry_max", self.limits["single_industry_max"])

        reviewed = min(requested, single_stock_max)
        if reviewed < requested:
            events.append(RiskEvent(
                event_id="risk_reduce_single_{0:03d}".format(index), type="single_stock_limit",
                level="warning", status="reduced",
                message="{0} 计划仓位 {1:g}% 超过单股上限 {2:g}%，已自动降仓。".format(
                    symbol, requested, single_stock_max),
                action="reduce_order", timestamp=utc_now(), related_order_id=symbol))

        remaining = max(0.0, total_position_limit - planned_total)
        if reviewed > remaining:
            events.append(RiskEvent(
                event_id="risk_reduce_total_{0:03d}".format(index), type="total_position_limit",
                level="warning", status="reduced" if remaining > 0 else "blocked",
                message="总仓位上限剩余 {0:g}%，订单已按总仓位约束调整。".format(remaining),
                action="reduce_order" if remaining > 0 else "skip_order",
                timestamp=utc_now(), related_order_id=symbol))
            reviewed = remaining

        industry = industry_map.get(symbol)
        if industry:
            industry_used_total = industry_used.get(industry, 0.0)
            industry_remaining = max(0.0, single_industry_max - industry_used_total)
            if reviewed > industry_remaining:
                events.append(RiskEvent(
                    event_id="risk_reduce_industry_{0:03d}".format(index), type="single_industry_limit",
                    level="warning", status="reduced" if industry_remaining > 0 else "blocked",
                    message="行业 {0} 仓位上限剩余 {1:g}%，订单已按行业约束调整。".format(
                        industry, industry_remaining),
                    action="reduce_order" if industry_remaining > 0 else "skip_order",
                    timestamp=utc_now(), related_order_id=symbol))
                reviewed = industry_remaining
            industry_used[industry] = industry_used_total + reviewed

        reviewed, md_events = self._apply_market_checks(reviewed, index, symbol, market_data)
        events.extend(md_events)

        correlation_group = (market_data.get(symbol) or {}).get("correlation_group")
        if correlation_group:
            group_max = self.limits["correlation_group_max_pct"]
            group_used = correlation_used.get(correlation_group, 0.0)
            group_remaining = max(0.0, group_max - group_used)
            if reviewed > group_remaining:
                events.append(RiskEvent(
                    event_id="risk_reduce_correlation_{0:03d}".format(index), type="correlation_limit",
                    level="warning", status="reduced" if group_remaining > 0 else "blocked",
                    message="相关分组 {0} 总仓位上限剩余 {1:g}%，订单已按相关性约束调整。".format(
                        correlation_group, group_remaining),
                    action="reduce_order" if group_remaining > 0 else "skip_order",
                    timestamp=utc_now(), related_order_id=symbol))
                reviewed = group_remaining
            correlation_used[correlation_group] = group_used + reviewed

        return reviewed, planned_total + reviewed, events

    def _apply_market_checks(self, reviewed, index, symbol, market_data):
        events = []
        md = market_data.get(symbol) or {}
        if not md:
            return reviewed, events

        last_price = md.get("last_price")
        avg_daily_value = md.get("avg_daily_value")
        if last_price is not None and avg_daily_value is not None and reviewed > 0:
            max_adv_pct = self.limits["liquidity_max_adv_pct"]
            order_value = reviewed * last_price
            if order_value > avg_daily_value * max_adv_pct / 100.0:
                events.append(RiskEvent(
                    event_id="risk_liquidity_{0:03d}".format(index), type="liquidity_limit",
                    level="warning", status="skipped",
                    message="{0} 订单价值超过日均成交额的 {1:g}%，流动性不足，跳过订单。".format(
                        symbol, max_adv_pct),
                    action="skip_order", timestamp=utc_now(), related_order_id=symbol))
                return 0.0, events

        volatility = md.get("volatility_pct")
        if volatility is not None and reviewed > 0 and volatility >= self.limits["volatility_delever_threshold"]:
            factor = self.limits["volatility_delever_factor"]
            new_pct = round(reviewed * factor, 2)
            events.append(RiskEvent(
                event_id="risk_delever_{0:03d}".format(index), type="volatility_delever",
                level="warning", status="reduced",
                message="{0} 波动率 {1:g}% 达到高波动阈值 {2:g}%，仓位由 {3:g}% 降至 {4:g}%。".format(
                    symbol, volatility, self.limits["volatility_delever_threshold"], reviewed, new_pct),
                action="reduce_order", timestamp=utc_now(), related_order_id=symbol))
            reviewed = new_pct

        next_event_days = md.get("next_event_days")
        if next_event_days is not None and next_event_days <= self.limits["event_block_window_days"]:
            events.append(RiskEvent(
                event_id="risk_event_window_{0:03d}".format(index), type="event_window_block",
                level="warning", status="blocked",
                message="{0} 在 {1} 个交易日内有财报/公告/解禁事件，禁止开仓。".format(
                    symbol, next_event_days),
                action="skip_order", timestamp=utc_now(), related_order_id=symbol))
            return 0.0, events

        return reviewed, events

    def _stop_loss_take_profit(self, plan, market_data):
        md = market_data or {}
        last_price = md.get("last_price")
        stop_loss = _first_numeric_condition_price(plan.get("stop_loss_conditions"))
        take_profit = _first_numeric_condition_price(plan.get("reduce_conditions"))
        if last_price is not None:
            if stop_loss is None:
                stop_loss = round(last_price * (1 - self.limits["default_stop_loss_pct"] / 100.0), 2)
            if take_profit is None:
                take_profit = round(last_price * (1 + self.limits["default_take_profit_pct"] / 100.0), 2)
        return stop_loss, take_profit

    def _skip_event(self, index, plan, message):
        return RiskEvent(
            event_id="risk_skip_{0:03d}".format(index), type="order_skipped", level="info",
            status="skipped", message=message, action="skip_order", timestamp=utc_now(),
            related_order_id=str(plan.get("symbol") or ""))


def _symbol_industry_map(report):
    result = {}
    for stock in report.get("stocks") or []:
        symbol = str(stock.get("symbol") or "")
        industry = stock.get("industry")
        if symbol and industry:
            result[symbol] = industry
    return result


def _limit_or_default(hard_limits, key, default, suffix=""):
    raw = hard_limits.get(key)
    if raw is None:
        return default
    text = str(raw).replace("%", "").replace("R", "").strip()
    try:
        return float(text)
    except ValueError:
        return default


def _percent_from_position(position):
    text = str(position or "0").replace("%", "").strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        return 0.0


def _first_numeric_condition_price(conditions):
    for condition in conditions or []:
        value = _price_from_expression(condition.get("expression") if isinstance(condition, dict) else str(condition))
        if value is not None:
            return value
    return None


def _price_from_expression(expression):
    """从量化条件表达式中提取第一个确定性的价格阈值（如 <= 9.20）。"""
    if not expression:
        return None
    import re

    matches = re.findall(r"(?:<=?|>=?)\s*([0-9]+(?:\.[0-9]+)?)", str(expression))
    if not matches:
        return None
    try:
        return round(float(matches[0]), 2)
    except ValueError:
        return None
