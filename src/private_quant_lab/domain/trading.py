"""Paper-trading domain types for the autonomous MVP.

These contracts deliberately model a simulated execution layer. They are safe
to use in local tests because no live broker credentials or real orders are
involved.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional


def utc_now():
    """Return an ISO-like timestamp for local run records."""

    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@dataclass
class OrderInstruction:
    """模拟盘订单指令：由交易计划转换而来，作为执行层输入。"""

    order_id: str
    symbol: str
    name: str
    side: str
    quantity: float
    order_type: str
    time_in_force: str
    source_plan_ref: str
    trigger_conditions: list[dict] = field(default_factory=list)
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class OrderExecution:
    """模拟盘执行结果：记录 paper_order 工具返回的订单状态。"""

    execution_id: str
    order_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str
    status: str
    submitted_at: str
    filled_quantity: float
    avg_price: Optional[float]
    raw_result: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class RiskEvent:
    """风控事件：记录阻断、降仓、熔断或人工急停等安全动作。"""

    event_id: str
    type: str
    level: str
    status: str
    message: str
    action: str
    timestamp: str
    related_order_id: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class PositionSnapshot:
    """模拟持仓快照：用于监控台展示当前仓位状态。"""

    symbol: str
    name: str
    quantity: float
    market_value: float
    weight: str
    unrealized_pnl_pct: float

    def to_dict(self):
        return asdict(self)


@dataclass
class IntradayAlert:
    """盘中监控事件：记录触发条件、模拟动作和当时快照。"""

    alert_id: str
    condition_ref: str
    symbol: str
    status: str
    action: str
    triggered_at: str
    actual_value: float
    message: str

    def to_dict(self):
        return asdict(self)


@dataclass
class ReviewReport:
    """收盘复盘摘要：对本次模拟盘 workflow 进行质量评价。"""

    review_id: str
    status: str
    generated_at: str
    industry_alpha: float
    stock_alpha: float
    order_fill_rate: float
    risk_effectiveness: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class AutoTradingRun:
    """全自动模拟盘 run：串联盘前报告、订单、执行、风控和持仓。"""

    run_mode: str
    status: str
    pre_market_report: dict
    order_instructions: list[OrderInstruction]
    executions: list[OrderExecution]
    risk_events: list[RiskEvent]
    positions: list[PositionSnapshot]
    intraday_alerts: list[IntradayAlert]
    review_report: ReviewReport
    summary: str

    def to_dict(self):
        return asdict(self)


def trading_schema():
    """Return JSON schema for the simulated execution layer."""

    condition_schema = {
        "type": "object",
        "properties": {
            "condition_id": {"type": "string"},
            "expression": {"type": "string"},
            "text": {"type": "string"},
        },
    }
    order_instruction_schema = {
        "type": "object",
        "required": [
            "order_id",
            "symbol",
            "name",
            "side",
            "quantity",
            "order_type",
            "time_in_force",
            "source_plan_ref",
            "trigger_conditions",
        ],
        "properties": {
            "order_id": {"type": "string"},
            "symbol": {"type": "string"},
            "name": {"type": "string"},
            "side": {"type": "string", "enum": ["buy", "sell"]},
            "quantity": {"type": "number", "minimum": 0},
            "order_type": {"type": "string", "enum": ["market", "limit"]},
            "time_in_force": {"type": "string"},
            "source_plan_ref": {"type": "string"},
            "trigger_conditions": {"type": "array", "items": condition_schema},
            "stop_loss_price": {"type": ["number", "null"]},
            "take_profit_price": {"type": ["number", "null"]},
        },
    }
    order_execution_schema = {
        "type": "object",
        "required": [
            "execution_id",
            "order_id",
            "symbol",
            "side",
            "quantity",
            "order_type",
            "status",
            "submitted_at",
            "filled_quantity",
            "avg_price",
            "raw_result",
        ],
        "properties": {
            "execution_id": {"type": "string"},
            "order_id": {"type": "string"},
            "symbol": {"type": "string"},
            "side": {"type": "string"},
            "quantity": {"type": "number"},
            "order_type": {"type": "string"},
            "status": {"type": "string"},
            "submitted_at": {"type": "string"},
            "filled_quantity": {"type": "number"},
            "avg_price": {"type": ["number", "null"]},
            "raw_result": {"type": "object"},
        },
    }
    risk_event_schema = {
        "type": "object",
        "required": ["event_id", "type", "level", "status", "message", "action", "timestamp"],
        "properties": {
            "event_id": {"type": "string"},
            "type": {"type": "string"},
            "level": {"type": "string", "enum": ["info", "warning", "critical"]},
            "status": {"type": "string"},
            "message": {"type": "string"},
            "action": {"type": "string"},
            "timestamp": {"type": "string"},
            "related_order_id": {"type": "string"},
        },
    }
    position_schema = {
        "type": "object",
        "required": ["symbol", "name", "quantity", "market_value", "weight", "unrealized_pnl_pct"],
        "properties": {
            "symbol": {"type": "string"},
            "name": {"type": "string"},
            "quantity": {"type": "number"},
            "market_value": {"type": "number"},
            "weight": {"type": "string"},
            "unrealized_pnl_pct": {"type": "number"},
        },
    }
    intraday_alert_schema = {
        "type": "object",
        "required": [
            "alert_id",
            "condition_ref",
            "symbol",
            "status",
            "action",
            "triggered_at",
            "actual_value",
            "message",
        ],
        "properties": {
            "alert_id": {"type": "string"},
            "condition_ref": {"type": "string"},
            "symbol": {"type": "string"},
            "status": {"type": "string", "enum": ["triggered", "skipped", "watching"]},
            "action": {"type": "string"},
            "triggered_at": {"type": "string"},
            "actual_value": {"type": "number"},
            "message": {"type": "string"},
        },
    }
    review_schema = {
        "type": "object",
        "required": [
            "review_id",
            "status",
            "generated_at",
            "industry_alpha",
            "stock_alpha",
            "order_fill_rate",
            "risk_effectiveness",
            "notes",
        ],
        "properties": {
            "review_id": {"type": "string"},
            "status": {"type": "string"},
            "generated_at": {"type": "string"},
            "industry_alpha": {"type": "number"},
            "stock_alpha": {"type": "number"},
            "order_fill_rate": {"type": "number"},
            "risk_effectiveness": {"type": "string"},
            "notes": {"type": "array", "items": {"type": "string"}},
        },
    }
    return {
        "type": "object",
        "required": [
            "run_mode",
            "status",
            "pre_market_report",
            "order_instructions",
            "executions",
            "risk_events",
            "positions",
            "intraday_alerts",
            "review_report",
            "summary",
        ],
        "properties": {
            "run_mode": {"type": "string", "enum": ["paper"]},
            "status": {"type": "string", "enum": ["idle", "running", "completed", "blocked", "error"]},
            "pre_market_report": {"type": "object"},
            "order_instructions": {"type": "array", "items": order_instruction_schema},
            "executions": {"type": "array", "items": order_execution_schema},
            "risk_events": {"type": "array", "items": risk_event_schema},
            "positions": {"type": "array", "items": position_schema},
            "intraday_alerts": {"type": "array", "items": intraday_alert_schema},
            "review_report": review_schema,
            "summary": {"type": "string"},
        },
    }


def empty_auto_trading_run(pre_market_report=None):
    """Create an empty simulated execution run for UI initialization."""

    return AutoTradingRun(
        run_mode="paper",
        status="idle",
        pre_market_report=pre_market_report or {},
        order_instructions=[],
        executions=[],
        risk_events=[],
        positions=[],
        intraday_alerts=[],
        review_report=ReviewReport(
            review_id="",
            status="pending",
            generated_at="",
            industry_alpha=0,
            stock_alpha=0,
            order_fill_rate=0,
            risk_effectiveness="尚未复盘。",
            notes=[],
        ),
        summary="尚未启动自动模拟盘。",
    )
