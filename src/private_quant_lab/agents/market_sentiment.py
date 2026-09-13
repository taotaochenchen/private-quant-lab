"""市场情绪节点的当次运行边界：校验证据传递和最终输出，不保存日志。"""

from copy import deepcopy
import json

from private_quant_lab.tools.market_sentiment import MARKET_TOOL_NAMES, _time
from private_quant_lab.tools.market_indicators import REQUIRED_INDICATORS, INDICATOR_CATALOG


SCORE_KEYS = ("sentiment_score", "capital_intensity", "volatility_risk")
CORE_TOOLS = ("get_market_snapshot", "get_market_breadth", "search_news", "analyze_news_sentiment", "compute_market_regime_metrics")
ASSESSMENT_KEYS = ("trading_sentiment", "capital_liquidity", "macro_environment", "external_pressure", "overall")


class MarketSentimentSession:
    """每次节点运行独立实例，避免并发任务或重复运行共享证据。"""

    def __init__(self, environment, as_of):
        self.environment = environment.subset(MARKET_TOOL_NAMES)
        _time(as_of)
        self.as_of = as_of
        self.observations = {}
        self.failures = {}

    def openai_tools(self):
        return self.environment.openai_tools()

    def run(self, name, arguments):
        try:
            result = self._run(name, arguments)
        except Exception as exc:
            self.failures[name] = str(exc)
            self.observations.pop(name, None)
            raise
        self.failures.pop(name, None)
        return result

    def _run(self, name, arguments):
        if _time(arguments.get("as_of")) != _time(self.as_of):
            raise ValueError("as_of must match scheduled_task.as_of")
        if name == "analyze_news_sentiment":
            news = self._data("search_news")["news"]
            if arguments.get("news") != news:
                raise ValueError("news must exactly match search_news result")
        if name == "compute_market_regime_metrics":
            breadth = self._data("get_market_breadth")
            sentiment = self._data("analyze_news_sentiment")
            expected = {key: breadth[key] for key in (
                "advancers", "decliners", "turnover_ratio", "annualized_volatility_pct")}
            expected["news_sentiment"] = sentiment["aggregate_sentiment"]
            if any(arguments.get(key) != value for key, value in expected.items()):
                raise ValueError("score inputs must exactly match observed breadth and sentiment")
        result = self.environment.run(name, arguments)
        # 新数据到达后，旧的派生结果不能再代表最新证据。
        invalidations = {
            "search_news": ("analyze_news_sentiment", "compute_market_regime_metrics"),
            "get_market_breadth": ("compute_market_regime_metrics",),
            "analyze_news_sentiment": ("compute_market_regime_metrics",),
        }
        for key in invalidations.get(name, ()):
            self.observations.pop(key, None)
        self.observations[name] = deepcopy(result.output)
        return result

    def _data(self, name):
        observation = self.observations.get(name, {})
        if not observation.get("data") or observation.get("missing_fields"):
            raise ValueError("missing valid observation: " + name)
        return observation["data"]

    def validate_final(self, content):
        """返回已校验结果；数据不全或模型改分时返回观察状态并清空分数。"""
        errors = [name + ": " + error for name, error in self.failures.items() if name != "get_derivatives_sentiment"]
        try:
            value = json.loads(content)
            if not isinstance(value, dict):
                raise ValueError("final must be an object")
        except (ValueError, TypeError):
            value = {}
            errors.append("invalid final JSON")
        for name in CORE_TOOLS:
            try:
                self._data(name)
            except ValueError as exc:
                errors.append(str(exc))
        coverage = {}
        for name, catalog in INDICATOR_CATALOG.items():
            items = self.observations.get(name, {}).get("data", {}).get("indicators", [])
            available = {item["indicator"] for item in items if item.get("value") is not None}
            required = set(REQUIRED_INDICATORS.get(name, ()))
            missing = sorted(required - available)
            coverage[name] = {"required": sorted(required), "available": sorted(available),
                              "missing_required": missing, "missing_optional": sorted(set(catalog) - required - available),
                              "error": self.failures.get(name)}
            if missing:
                errors.append(name + " missing required indicators: " + ", ".join(missing))
        scores = self.observations.get("compute_market_regime_metrics", {}).get("data", {})
        for key in SCORE_KEYS:
            if key not in scores or isinstance(value.get(key), bool) or value.get(key) != scores[key]:
                errors.append("score mismatch: " + key)
        if value.get("direction") not in ("bullish", "neutral", "bearish"):
            errors.append("invalid direction")
        if value.get("trading_mode") not in ("attack", "defense", "rotation", "observe"):
            errors.append("invalid trading_mode")
        if not isinstance(value.get("summary"), str) or not value["summary"].strip():
            errors.append("missing summary")
        assessments = value.get("assessments", {})
        for key in ASSESSMENT_KEYS:
            item = assessments.get(key) if isinstance(assessments, dict) else None
            if not isinstance(item, dict) or not isinstance(item.get("summary"), str) or not item["summary"].strip():
                errors.append("missing assessment: " + key)
                continue
            refs = item.get("evidence_refs")
            if not isinstance(refs, list) or any(not isinstance(ref, str) or ref not in self.observations for ref in refs):
                errors.append("invalid evidence_refs: " + key)
            missing = item.get("missing_indicators")
            if not isinstance(missing, list) or any(not isinstance(indicator, str) for indicator in missing):
                errors.append("invalid missing_indicators: " + key)
            if not refs and not missing:
                errors.append("assessment without evidence or missing indicator: " + key)
        conditions = value.get("forbidden_conditions")
        if not isinstance(conditions, list) or not conditions or any(
            not isinstance(c, dict) or not all(isinstance(c.get(k), str) and c[k].strip()
            for k in ("expression", "text")) for c in conditions):
            errors.append("missing forbidden_conditions expression/text")
        if errors:
            value = {"direction": "neutral", "trading_mode": "observe",
                     "summary": "市场情绪节点校验未通过，暂停生成交易建议。",
                     "forbidden_conditions": [{"expression": "data_missing == true", "text": "关键数据或结论校验未通过"}],
                     "assessments": {key: {"summary": "未通过校验", "evidence_refs": [], "missing_indicators": ["validated_evidence"]} for key in ASSESSMENT_KEYS},
                     **{key: None for key in SCORE_KEYS}}
        value.update(is_mock=True, as_of=self.as_of, data_missing=bool(errors),
                     validation_errors=errors, evidence=deepcopy(self.observations), indicator_coverage=coverage)
        return value
