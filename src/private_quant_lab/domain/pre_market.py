"""Pre-market decision report domain types.

These dataclasses describe the structured output that the pre-market workflow
must eventually produce. They intentionally stay dependency-free so the schema
can be reused by the web debugger, tests, and later workflow nodes.
"""

from dataclasses import asdict, dataclass, field
from datetime import date
import json
import re
from typing import Optional


JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


@dataclass
class EvidenceItem:
    """一条可追溯证据：说明结论来自哪里，以及它支持哪个判断。"""

    evidence_id: str
    type: str
    source: str
    source_timestamp: str
    value: dict
    used_by: list[str]
    influence: str

    def to_dict(self):
        return asdict(self)


@dataclass
class QuantCondition:
    """可监控条件：表达式给机器执行，文本给用户理解。"""

    expression: str
    text: str
    condition_id: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class MarketState:
    """盘前市场状态：回答今天适不适合承担风险。"""

    direction: str
    trading_mode: str
    sentiment_score: Optional[float]
    capital_intensity: Optional[float]
    volatility_risk: Optional[float]
    summary: str
    forbidden_conditions: list[QuantCondition] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class IndustryCandidate:
    """行业候选：用于承接从市场方向到个股池的第一层筛选。"""

    industry: str
    score: int
    confidence: int
    thesis: str
    evidence: list[dict] = field(default_factory=list)
    counterpoints: list[str] = field(default_factory=list)
    invalid_conditions: list[QuantCondition] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class OperatorScores:
    """金融算子原始值：只能由确定性算子产生，模型只能解释不能改写。"""

    roe_ttm: float = 0
    gross_margin: float = 0
    debt_ratio: float = 0
    rs_20d: float = 0
    rs_60d: float = 0
    pe_ttm: float = 0
    pe_percentile_5y: float = 0
    volume_avg_20d: float = 0
    turnover_rate: float = 0
    short_term_gain_20d: float = 0
    margin_balance_change: float = 0

    def to_dict(self):
        return asdict(self)


@dataclass
class StockCandidate:
    """个股候选：承载多因子评分和交易前风险提示。"""

    symbol: str
    name: str
    industry: str
    total_score: int
    quality: int
    momentum: int
    valuation: int
    liquidity: int
    crowding: int
    risk_score: int
    suggested_position: str
    operator_breakdown: OperatorScores
    reason: str
    buy_conditions: list[QuantCondition] = field(default_factory=list)
    stop_loss_conditions: list[QuantCondition] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class RiskReview:
    """风控审核结果：拥有降仓或否决交易建议的权力。"""

    status: str
    reason: str
    hard_limits: dict
    rejections: list[str] = field(default_factory=list)
    manual_confirmations: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class TradePlanItem:
    """一条可执行交易计划：包含触发条件和放弃条件。"""

    symbol: str
    name: str
    side: str
    first_position: str
    max_position: str
    buy_conditions: list[QuantCondition]
    add_conditions: list[QuantCondition] = field(default_factory=list)
    reduce_conditions: list[QuantCondition] = field(default_factory=list)
    stop_loss_conditions: list[QuantCondition] = field(default_factory=list)
    no_trade_conditions: list[QuantCondition] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class PreMarketReport:
    """盘前报告：前端工作台和决策记录层的核心结构。"""

    report_date: str
    headline: str
    market_state: MarketState
    industries: list[IndustryCandidate]
    stocks: list[StockCandidate]
    risk_review: RiskReview
    trade_plan: list[TradePlanItem]
    evidence_chain: list[EvidenceItem] = field(default_factory=list)
    summary: str = ""

    def to_dict(self):
        return asdict(self)


def empty_pre_market_report(report_date=None):
    """Create an empty report skeleton for UI and workflow initialization."""

    value = report_date or date.today().isoformat()
    return PreMarketReport(
        report_date=value,
        headline="等待盘前分析",
        market_state=MarketState(
            direction="unknown",
            trading_mode="observe",
            sentiment_score=0,
            capital_intensity=0,
            volatility_risk=0,
            summary="尚未生成盘前市场状态。",
        ),
        industries=[],
        stocks=[],
        risk_review=RiskReview(
            status="pending",
            reason="尚未完成风控审核。",
            hard_limits={
                "total_position_limit": "0%",
                "single_stock_max": "0%",
                "single_industry_max": "0%",
                "daily_loss_limit": "0R",
            },
        ),
        trade_plan=[],
        evidence_chain=[],
        summary="尚未生成交易计划。",
    )


def pre_market_report_schema():
    """Return the JSON schema expected from a pre-market workflow."""

    condition_schema = {
        "type": "object",
        "required": ["expression", "text"],
        "properties": {
            "condition_id": {"type": "string"},
            "expression": {"type": "string"},
            "text": {"type": "string"},
        },
    }
    operator_breakdown_schema = {
        "type": "object",
        "required": [
            "roe_ttm",
            "gross_margin",
            "debt_ratio",
            "rs_20d",
            "rs_60d",
            "pe_ttm",
            "pe_percentile_5y",
            "volume_avg_20d",
            "turnover_rate",
            "short_term_gain_20d",
            "margin_balance_change",
        ],
        "properties": {
            "roe_ttm": {"type": "number"},
            "gross_margin": {"type": "number"},
            "debt_ratio": {"type": "number"},
            "rs_20d": {"type": "number"},
            "rs_60d": {"type": "number"},
            "pe_ttm": {"type": "number"},
            "pe_percentile_5y": {"type": "number"},
            "volume_avg_20d": {"type": "number"},
            "turnover_rate": {"type": "number"},
            "short_term_gain_20d": {"type": "number"},
            "margin_balance_change": {"type": "number"},
        },
    }

    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "report_date",
            "headline",
            "market_state",
            "industries",
            "stocks",
            "risk_review",
            "trade_plan",
            "evidence_chain",
            "summary",
        ],
        "properties": {
            "report_date": {"type": "string", "description": "YYYY-MM-DD"},
            "headline": {"type": "string"},
            "market_state": {
                "type": "object",
                "required": [
                    "direction",
                    "trading_mode",
                    "sentiment_score",
                    "capital_intensity",
                    "volatility_risk",
                    "summary",
                    "forbidden_conditions",
                ],
                "properties": {
                    "direction": {"type": "string", "enum": ["bullish", "neutral", "bearish", "unknown"]},
                    "trading_mode": {
                        "type": "string",
                        "enum": ["attack", "defense", "rotation", "observe"],
                    },
                    "sentiment_score": {"type": ["number", "null"], "minimum": 0, "maximum": 100},
                    "capital_intensity": {"type": ["number", "null"], "minimum": 0, "maximum": 100},
                    "volatility_risk": {"type": ["number", "null"], "minimum": 0, "maximum": 100},
                    "summary": {"type": "string"},
                    "forbidden_conditions": {"type": "array", "items": condition_schema},
                },
            },
            "industries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "industry",
                        "score",
                        "confidence",
                        "thesis",
                        "evidence",
                        "counterpoints",
                        "invalid_conditions",
                    ],
                    "properties": {
                        "industry": {"type": "string"},
                        "score": {"type": "integer", "minimum": 0, "maximum": 100},
                        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                        "thesis": {"type": "string"},
                        "evidence": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"},
                                    "source": {"type": "string"},
                                    "value": {},
                                    "timestamp": {"type": "string"},
                                },
                            },
                        },
                        "counterpoints": {"type": "array", "items": {"type": "string"}},
                        "invalid_conditions": {"type": "array", "items": condition_schema},
                    },
                },
            },
            "stocks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "symbol",
                        "name",
                        "industry",
                        "total_score",
                        "quality",
                        "momentum",
                        "valuation",
                        "liquidity",
                        "crowding",
                        "risk_score",
                        "suggested_position",
                        "operator_breakdown",
                        "reason",
                    ],
                    "properties": {
                        "symbol": {"type": "string"},
                        "name": {"type": "string"},
                        "industry": {"type": "string"},
                        "total_score": {"type": "integer", "minimum": 0, "maximum": 100},
                        "quality": {"type": "integer", "minimum": 0, "maximum": 100},
                        "momentum": {"type": "integer", "minimum": 0, "maximum": 100},
                        "valuation": {"type": "integer", "minimum": 0, "maximum": 100},
                        "liquidity": {"type": "integer", "minimum": 0, "maximum": 100},
                        "crowding": {"type": "integer", "minimum": 0, "maximum": 100},
                        "risk_score": {"type": "integer", "minimum": 0, "maximum": 100},
                        "suggested_position": {"type": "string"},
                        "operator_breakdown": operator_breakdown_schema,
                        "reason": {"type": "string"},
                        "buy_conditions": {"type": "array", "items": condition_schema},
                        "stop_loss_conditions": {"type": "array", "items": condition_schema},
                    },
                },
            },
            "risk_review": {
                "type": "object",
                "required": [
                    "status",
                    "reason",
                    "hard_limits",
                    "rejections",
                    "manual_confirmations",
                ],
                "properties": {
                    "status": {"type": "string", "enum": ["passed", "reduced", "blocked", "manual_review", "pending"]},
                    "reason": {"type": "string"},
                    "hard_limits": {
                        "type": "object",
                        "required": ["single_stock_max", "single_industry_max", "daily_loss_limit"],
                        "properties": {
                            "total_position_limit": {"type": "string"},
                            "single_stock_max": {"type": "string"},
                            "single_industry_max": {"type": "string"},
                            "daily_loss_limit": {"type": "string"},
                        },
                    },
                    "rejections": {"type": "array", "items": {"type": "string"}},
                    "manual_confirmations": {"type": "array", "items": {"type": "string"}},
                },
            },
            "trade_plan": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["symbol", "name", "side", "first_position", "max_position", "buy_conditions"],
                    "properties": {
                        "symbol": {"type": "string"},
                        "name": {"type": "string"},
                        "side": {"type": "string", "enum": ["buy", "sell", "hold", "avoid"]},
                        "first_position": {"type": "string"},
                        "max_position": {"type": "string"},
                        "buy_conditions": {"type": "array", "items": condition_schema},
                        "add_conditions": {"type": "array", "items": condition_schema},
                        "reduce_conditions": {"type": "array", "items": condition_schema},
                        "stop_loss_conditions": {"type": "array", "items": condition_schema},
                        "no_trade_conditions": {"type": "array", "items": condition_schema},
                    },
                },
            },
            "evidence_chain": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "evidence_id",
                        "type",
                        "source",
                        "source_timestamp",
                        "value",
                        "used_by",
                        "influence",
                    ],
                    "properties": {
                        "evidence_id": {"type": "string"},
                        "type": {"type": "string"},
                        "source": {"type": "string"},
                        "source_timestamp": {"type": "string"},
                        "value": {},
                        "used_by": {"type": "array", "items": {"type": "string"}},
                        "influence": {"type": "string"},
                    },
                },
            },
            "summary": {"type": "string"},
            "strategy_revision": {"type": "object", "description": "服务端确定性生成的跨交易日建议对比，模型不填写。"},
        },
    }


def parse_pre_market_report(content):
    """Parse and validate a model-produced PreMarketReport JSON object."""

    text = str(content or "").strip()
    match = JSON_BLOCK_RE.search(text)
    if match:
        text = match.group(1).strip()
    if not text:
        raise ValueError("pre-market report content must not be empty")
    report = _load_json_object(text)
    if not isinstance(report, dict):
        raise ValueError("pre-market report must be a JSON object")
    _validate_schema_value(report, pre_market_report_schema(), "report")
    return report


def _load_json_object(text):
    try:
        return json.loads(text)
    except ValueError:
        start = text.find("{")
        if start > 0:
            try:
                value, _end = json.JSONDecoder().raw_decode(text[start:])
                return value
            except ValueError:
                pass
    raise ValueError("pre-market report must be valid JSON")


def _validate_schema_value(value, schema, path):
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            raise ValueError("{0} must be an object".format(path))
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError("{0}.{1} is required".format(path, key))
        properties = schema.get("properties", {})
        for key, child in properties.items():
            if key in value and child:
                _validate_schema_value(value[key], child, "{0}.{1}".format(path, key))
        return
    if expected_type == "array":
        if not isinstance(value, list):
            raise ValueError("{0} must be an array".format(path))
        item_schema = schema.get("items") or {}
        for index, item in enumerate(value):
            if item_schema:
                _validate_schema_value(item, item_schema, "{0}[{1}]".format(path, index))
        return
    if expected_type == "string":
        if not isinstance(value, str):
            raise ValueError("{0} must be a string".format(path))
        return
    if expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("{0} must be an integer".format(path))
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise ValueError("{0} must be >= {1}".format(path, minimum))
        if maximum is not None and value > maximum:
            raise ValueError("{0} must be <= {1}".format(path, maximum))
        return
    if expected_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("{0} must be a number".format(path))
