"""市场情绪节点工具：固定样例用于联调，评分算法不调用模型。"""

from copy import deepcopy
from datetime import datetime
import math

from .types import QuantTool, ToolSpec
from .market_indicators import INDICATOR_CATALOG


MARKET_TOOL_NAMES = (
    "get_market_snapshot", "get_market_breadth", "get_macro_snapshot",
    "search_news", "analyze_news_sentiment", "compute_market_regime_metrics",
    "get_capital_behavior", "get_liquidity_environment", "get_derivatives_sentiment",
)
FIXTURE_TIME = "2026-09-04T15:00:00+08:00"


def _time(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return result


def _envelope(arguments, data):
    as_of = arguments["as_of"]
    _time(as_of)
    return {"data": data, "source": "local_mock", "mock": True, "is_mock": True,
            "as_of": as_of, "data_version": "market-fixture-v1",
            "missing_fields": [], "warnings": ["固定历史模拟样例，不代表截止时间的最新行情。"]}


def _available(arguments, data):
    result = _envelope(arguments, data)
    if _time(arguments["as_of"]) < _time(FIXTURE_TIME):
        result["data"] = {}
        result["missing_fields"] = ["data"]
        result["warnings"].append("截止时间早于样例发布时间，无可用数据。")
    return result


def _snapshot(a):
    """输入 market/indices/as_of；输出指数报价、交易状态和独立数据时间。"""
    return _available(a, {"market": "CN_A", "quotes": [
        {"symbol": symbol, "price": 3800.0, "change_pct": 0.6,
         "turnover_cny": 520000000000, "session": "closed",
         "source_timestamp": FIXTURE_TIME} for symbol in a["indices"]]})


def _breadth(a):
    """输入 market/lookback_days/as_of；输出涨跌家数、成交额比和波动率。"""
    return _available(a, {"market": "CN_A", "lookback_days": a["lookback_days"],
        "advancers": 3100, "decliners": 1900, "unchanged": 200,
        "limit_up": 65, "limit_down": 8, "turnover_ratio": 1.12,
        "annualized_volatility_pct": 22.0, "above_ma20_ratio": 0.61,
        "source_timestamp": FIXTURE_TIME})


def _macro(a):
    """输入 indicators/as_of；输出宏观指标值、单位、时间；未知指标记为缺失。"""
    return _indicator_snapshot("get_macro_snapshot", a)


def _indicator_snapshot(name, a):
    """输入指标列表/as_of；按模拟发布时间过滤，逐项返回值、单位、周期和口径。"""
    result = _envelope(a, {"indicators": []})
    for key in a["indicators"]:
        item = deepcopy(INDICATOR_CATALOG[name].get(key))
        if item is None or item["value"] is None or _time(item["published_at"]) > _time(a["as_of"]):
            result["missing_fields"].append(key)
            continue
        result["data"]["indicators"].append(dict(item, indicator=key))
    result["warnings"].append("数值、观察期和发布时间均为模拟；月度指标按发布时间而非观察期准入。")
    return result


def _news(a):
    """输入 query/start_at/as_of/limit；输出带 ID、原文摘要和发布时间的模拟新闻。"""
    if _time(a["start_at"]) > _time(a["as_of"]):
        raise ValueError("start_at must not exceed as_of")
    items = []
    if _time(a["start_at"]) <= _time(FIXTURE_TIME) <= _time(a["as_of"]):
        for i, title in enumerate(("模拟：政策支持产业投资", "模拟：企业提示需求不确定性")):
            items.append({"news_id": "mock-news-{0}".format(i + 1), "title": title,
                          "summary": a["query"] + "，" + title, "source": "fixture",
                          "published_at": FIXTURE_TIME,
                          "url": "https://example.invalid/news/{0}".format(i + 1)})
    return _envelope(a, {"query": a["query"], "news": items[:a["limit"]]})


def _sentiment(a):
    """输入 news 原文列表/as_of；输出逐条 ID 关联的情绪及汇总，不凭空增加新闻。"""
    ids = set()
    items = []
    for news in a["news"]:
        if news["news_id"] in ids:
            raise ValueError("duplicate news_id")
        ids.add(news["news_id"])
        if _time(news["published_at"]) > _time(a["as_of"]):
            raise ValueError("news published after as_of")
        text = news["title"] + news["summary"]
        score = 0.5 if "支持" in text else -0.5 if "不确定" in text else 0.0
        items.append({"news_id": news["news_id"], "sentiment": score,
                      "relevance": 1.0, "event_type": "mock_event"})
    result = _envelope(a, {"items": items, "headline_count": len(items),
        "aggregate_sentiment": sum(item["sentiment"] for item in items) / len(items) if items else None})
    if not items:
        result["missing_fields"] = ["aggregate_sentiment"]
    return result


def _metrics(a):
    """输入涨跌家数、情绪[-1,1]、成交额比、年化波动率(%)；输出0-100分及公式版本。

    v1 仅用于原型联调：情绪分=新闻与上涨占比等权；资金分=成交额比*50；
    风险分=年化波动率*2。此工具永远在本地计算，不交给 DeepSeek 改分。
    """
    total = a["advancers"] + a["decliners"]
    result = _envelope(a, {})
    result["source"] = "local_mock_calculation"
    if total == 0:
        result["missing_fields"] = ["advancers", "decliners"]
        return result
    clip = lambda n: round(max(0, min(100, n)), 2)
    result["data"] = {
        "sentiment_score": clip((a["news_sentiment"] + 1) * 25 + a["advancers"] / total * 50),
        "capital_intensity": clip(a["turnover_ratio"] * 50),
        "volatility_risk": clip(a["annualized_volatility_pct"] * 2),
        "formula_version": "prototype-v1", "inputs": deepcopy(a)}
    result["data"]["score_semantics"] = {
        "capital_intensity": "turnover_activity_proxy_not_net_flow",
        "macro_and_derivatives": "qualitative_assessment_only_not_scored",
    }
    return result


def _validate(value, schema, path="arguments"):
    """验证本模块使用的 JSON Schema 子集，执行前拒绝缺失或越界参数。"""
    kind = schema["type"]
    valid = {"object": isinstance(value, dict), "array": isinstance(value, list),
             "string": isinstance(value, str),
             "integer": isinstance(value, int) and not isinstance(value, bool),
             "number": isinstance(value, (int, float)) and not isinstance(value, bool)}[kind]
    if not valid:
        raise ValueError(path + " must be " + kind)
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(path + " unsupported value")
    if kind == "object":
        if set(schema.get("required", [])) - value.keys() or value.keys() - schema["properties"].keys():
            raise ValueError(path + " missing or unknown fields")
        for key, item in value.items():
            _validate(item, schema["properties"][key], path + "." + key)
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 100):
            raise ValueError(path + " invalid length")
        for item in value:
            _validate(item, schema["items"], path)
    elif kind in ("number", "integer"):
        if not math.isfinite(value) or not schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf):
            raise ValueError(path + " out of range")
    elif not value.strip():
        raise ValueError(path + " must not be empty")


def build_market_sentiment_tools(observation_mocker=None):
    """返回标准 OpenAI function 工具；数据 observation 可模拟，评分保持确定性。"""
    string = {"type": "string"}
    timestamp = {"type": "string", "format": "date-time"}
    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
    def strings():
        return {"type": "array", "items": string, "minItems": 1, "maxItems": 20}
    definitions = [
        ("get_market_snapshot", "市场指数模拟快照，输出 quotes 及 source_timestamp，涨跌幅单位百分数。", _snapshot,
         {"market": {"type": "string", "enum": ["CN_A"]}, "indices": strings()}),
        ("get_market_breadth", "市场宽度模拟数据，输出涨跌家数、成交额比和年化波动率百分数。", _breadth,
         {"market": {"type": "string", "enum": ["CN_A"]}, "lookback_days": {"type": "integer", "minimum": 1, "maximum": 120}}),
        ("get_macro_snapshot", "国内宏观模拟快照，支持 official_pmi/cpi_yoy/ppi_yoy/social_financing_yoy/m1_yoy/m2_yoy/industrial_profit_yoy；带观察期和发布时间。旧外围指标仍兼容。", _macro,
         {"indicators": strings()}),
        ("search_news", "按主题和时间范围生成模拟新闻，输出 news 含 ID、标题、摘要、链接、发布时间。", _news,
         {"query": string, "start_at": timestamp, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}),
        ("analyze_news_sentiment", "分析输入新闻正文，输出逐条情绪[-1,1]和汇总情绪；news 取自 search_news。", _sentiment,
         {"news": {"type": "array", "maxItems": 20, "items": obj({"news_id": string, "title": string, "summary": string,
             "source": string, "published_at": timestamp, "url": string})}}),
        ("compute_market_regime_metrics", "本地确定性原型评分，输入必须原样取自工具结果，输出三项0-100分及公式版本和原始输入。", _metrics,
         {"advancers": {"type": "integer", "minimum": 0}, "decliners": {"type": "integer", "minimum": 0},
          "news_sentiment": {"type": "number", "minimum": -1, "maximum": 1},
          "turnover_ratio": {"type": "number", "minimum": 0}, "annualized_volatility_pct": {"type": "number", "minimum": 0}}),
    ]
    for tool_name in ("get_capital_behavior", "get_liquidity_environment", "get_derivatives_sentiment"):
        description = "模拟指标快照，输出指标值、单位、观察期、发布时间和口径；支持：" + "/".join(INDICATOR_CATALOG[tool_name])
        definitions.append((tool_name, description, lambda a, name=tool_name: _indicator_snapshot(name, a), {"indicators": strings()}))
    tools = []
    for name, description, handler, properties in definitions:
        schema = obj(dict(properties, as_of=timestamp))
        spec = ToolSpec(name, description, schema)
        def run(a, handler=handler, schema=schema, spec=spec):
            _validate(a, schema)
            local = handler(a)
            if observation_mocker is None or spec.name == "compute_market_regime_metrics" or local["missing_fields"]:
                return local
            # 模型可模拟数据，但不能改变字段类型、新闻关联或越过截止时间。
            simulated = observation_mocker.simulate(spec, a, local)
            if not _valid_observation(simulated.get("data"), local["data"], a):
                local["warnings"].append("模型改变了数据契约，已使用本地样例。")
                local["observation_source"] = "local_fallback"
            else:
                local["data"] = simulated["data"]
                if spec.name == "analyze_news_sentiment":
                    items = local["data"]["items"]
                    local["data"]["headline_count"] = len(items)
                    local["data"]["aggregate_sentiment"] = sum(item["sentiment"] for item in items) / len(items)
                local["source"] = "deepseek_mock" if simulated.get("observation_source") == "deepseek" else "local_mock"
                local["observation_source"] = simulated.get("observation_source", "local_fallback")
            if simulated.get("observation_error"):
                local["observation_error"] = simulated["observation_error"]
            return local
        tools.append(QuantTool(spec, run))
    return tools


def _valid_observation(data, template, arguments):
    def check(value, sample, key=""):
        if isinstance(sample, dict):
            return isinstance(value, dict) and sample.keys() == value.keys() and all(
                check(value[k], v, k) for k, v in sample.items())
        if isinstance(sample, list):
            return isinstance(value, list) and len(value) == len(sample) and all(
                check(v, s) for v, s in zip(value, sample))
        if isinstance(sample, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                return False
            if isinstance(sample, int) and (not isinstance(value, int) or value < 0):
                return False
            if key in ("sentiment", "aggregate_sentiment"):
                return -1 <= value <= 1
            if key in ("relevance", "above_ma20_ratio"):
                return 0 <= value <= 1
            return value >= 0 if key in ("turnover_ratio", "annualized_volatility_pct", "price") else True
        if key in ("source_timestamp", "published_at"):
            try:
                return _time(value) <= _time(arguments["as_of"]) and (
                    "start_at" not in arguments or _time(value) >= _time(arguments["start_at"]))
            except (ValueError, TypeError):
                return False
        if key in ("news_id", "market", "symbol", "indicator", "unit", "query", "source", "url", "title", "summary", "frequency", "observation_period", "methodology"):
            return value == sample
        return isinstance(value, type(sample))
    return check(data, template)
