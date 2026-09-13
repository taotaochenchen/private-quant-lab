"""模拟模型真实使用六个工具，测试完整市场节点协议。"""
import json

from private_quant_lab.models import ChatResponse, ChatToolCall


def market_response(messages):
    task = json.loads(messages[1].content)
    as_of = task["scheduled_task"]["as_of"]
    results = [json.loads(m.content) for m in messages if m.role == "tool"]
    def calls(items):
        return ChatResponse(content="", model="fake", finish_reason="tool_calls", tool_calls=[
            ChatToolCall("market-" + name, name, dict(args, as_of=as_of)) for name, args in items])
    if not results:
        return calls([
            ("get_market_snapshot", {"market": "CN_A", "indices": ["000300.SH"]}),
            ("get_market_breadth", {"market": "CN_A", "lookback_days": 20}),
            ("get_macro_snapshot", {"indicators": ["official_pmi", "social_financing_yoy", "m1_yoy", "m2_yoy"]}),
            ("search_news", {"query": "市场", "start_at": "2026-09-04T00:00:00+08:00", "limit": 2}),
            ("get_capital_behavior", {"indicators": ["margin_balance_change_pct", "etf_share_change_pct"]}),
            ("get_liquidity_environment", {"indicators": ["dr007", "cn_10y_yield"]}),
        ])
    if len(results) == 6:
        return calls([("analyze_news_sentiment", {"news": results[3]["data"]["news"]})])
    if len(results) == 7:
        args = {k: results[1]["data"][k] for k in ("advancers", "decliners", "turnover_ratio", "annualized_volatility_pct")}
        args["news_sentiment"] = results[6]["data"]["aggregate_sentiment"]
        return calls([("compute_market_regime_metrics", args)])
    scores = results[7]["data"]
    final = {k: scores[k] for k in ("sentiment_score", "capital_intensity", "volatility_risk")}
    final.update(direction="neutral", trading_mode="observe", summary="模拟市场样例。",
                 forbidden_conditions=[{"expression": "industry_strength < 70", "text": "行业强度不足"}])
    final["assessments"] = {key: {"summary": "模拟证据判断", "evidence_refs": refs, "missing_indicators": [] if refs else ["external_data"]} for key, refs in {
        "trading_sentiment": ["get_market_breadth"], "capital_liquidity": ["get_capital_behavior", "get_liquidity_environment"],
        "macro_environment": ["get_macro_snapshot"], "external_pressure": [], "overall": ["compute_market_regime_metrics"]}.items()}
    return ChatResponse(content=json.dumps(final), model="fake", finish_reason="stop")
