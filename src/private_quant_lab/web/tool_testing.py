"""独立工具测试：不启动 Agent，不要求本地 mock 配置模型密钥。"""

from datetime import datetime
import math

from private_quant_lab.tools import build_mock_quant_environment
from private_quant_lab.tools.market_indicators import INDICATOR_CATALOG
from private_quant_lab.tools.market_sentiment import MARKET_TOOL_NAMES
from private_quant_lab.tools.snowball_catalog import snowball_catalog
from private_quant_lab.tools.snowball_adapter import load_snowball_settings, SnowballError


def snowball_config_status():
    """只返回配置摘要；不返回 Cookie，不发起网络请求，不代表认证成功。"""
    try:
        settings = load_snowball_settings()
        return {"status": "ok", "token_configured": bool(settings.get_token()),
                "content_permission_confirmed": settings.content_permission_confirmed,
                "timeout_seconds": settings.timeout_seconds}
    except SnowballError:
        return {"status": "invalid_configuration"}


def validate_arguments(value, schema, path="arguments"):
    kind = schema.get("type")
    checks = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list),
              "string": lambda: isinstance(value, str), "boolean": lambda: isinstance(value, bool),
              "number": lambda: type(value) in (int, float) and math.isfinite(value),
              "integer": lambda: type(value) is int}
    if kind in checks and not checks[kind]():
        raise ValueError(path + " must be " + kind)
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(path + " unsupported value")
    if kind == "object":
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(path + "." + key + " is required")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key not in properties and schema.get("additionalProperties") is False:
                raise ValueError(path + "." + key + " is not allowed")
            if key in properties:
                validate_arguments(item, properties[key], path + "." + key)
    if kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", float("inf")):
            raise ValueError(path + " invalid length")
        for index, item in enumerate(value):
            validate_arguments(item, schema.get("items", {}), path + "[" + str(index) + "]")
    if kind in ("integer", "number"):
        if not schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf):
            raise ValueError(path + " out of range")
    if schema.get("format") == "date-time":
        if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError(path + " requires timezone")


def tool_catalog():
    environment = build_mock_quant_environment()
    def example(schema, key=""):
        if "enum" in schema:
            return schema["enum"][0]
        defaults = {"as_of": "2026-09-05T08:45:00+08:00", "start_at": "2026-09-04T00:00:00+08:00",
                    "symbol": "NVDA", "query": "A股市场政策", "side": "buy", "order_type": "market",
                    "universe": "us_large_cap", "indicator": "vix", "strategy": "momentum",
                    "start": "2020-01-01", "end": "2025-12-31"}
        if key in defaults:
            return defaults[key]
        kind = schema.get("type")
        if kind == "object":
            return {k: example(v, k) for k, v in schema.get("properties", {}).items()}
        if kind == "array":
            return [example(schema["items"])] if "items" in schema else []
        if kind in ("number", "integer"):
            return max(schema.get("minimum", 1), 1)
        return "sample"
    overrides = {
        "get_market_snapshot": {"indices": ["000300.SH", "000905.SH"]},
        "get_market_breadth": {"lookback_days": 20},
        "compute_market_regime_metrics": {"advancers": 3100, "decliners": 1900, "news_sentiment": 0,
            "turnover_ratio": 1.12, "annualized_volatility_pct": 22},
        "portfolio_risk": {"positions": [{"symbol": "NVDA", "weight": 0.1}]},
        "technical_indicators": {"indicators": ["rsi", "momentum"]},
        "paper_order": {"quantity": 10},
    }
    for name, catalog in INDICATOR_CATALOG.items():
        overrides[name] = {"indicators": [key for key, point in catalog.items() if point["value"] is not None]}
    news = environment.run("search_news", {"query": "市场政策", "start_at": "2026-09-04T00:00:00+08:00",
        "as_of": "2026-09-05T08:45:00+08:00", "limit": 2}).output["data"]["news"]
    overrides["analyze_news_sentiment"] = {"news": news}
    result = []
    for tool in environment.tools:
        arguments = example(tool.spec.input_schema)
        arguments.update(overrides.get(tool.spec.name, {}))
        result.append({"name": tool.spec.name, "description": tool.spec.description,
                       "schema": tool.spec.input_schema, "example": arguments,
                       "group": "市场情绪" if tool.spec.name in MARKET_TOOL_NAMES else "通用量化",
                       "implementation": "mock + real" if tool.spec.name == "get_market_snapshot" else "mock",
                       "modes": ["local", "llm", "real"] if tool.spec.name == "get_market_snapshot" else ["local", "llm"]})
    return result + snowball_catalog()
