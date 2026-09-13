"""Pre-market workflow built on the OpenAI tools agent loop."""

from datetime import date, datetime, timezone, timedelta
import json

from private_quant_lab.agents import ReActAgent
from private_quant_lab.agents.market_sentiment import MarketSentimentSession
from private_quant_lab.domain import parse_pre_market_report, pre_market_report_schema
from private_quant_lab.domain.strategy_revision import build_decision_context, compare_strategy, REVISION_INSTRUCTION
from private_quant_lab.tools.market_sentiment import MARKET_TOOL_NAMES


DEFAULT_PRE_MARKET_TASK = (
    "请生成今天的盘前交易计划。先判断市场情绪和宏观风险，再筛选 2 到 4 个行业方向，"
    "下钻候选股票，调用技术面、基本面、新闻情绪和组合风险工具，最后输出结构化盘前报告。"
)


PRE_MARKET_SYSTEM_PROMPT = """你是私人量化系统的盘前指挥官 Agent。

你必须遵守以下原则：
- 使用请求中提供的 OpenAI tools 获取市场、行业、个股、新闻、宏观、风控或搜索信息。
- 工具输出是 mock 数据，只用于验证流程，不构成投资建议。
- 不要使用 Action/Observation 文本协议。
- 风控结论拥有否决权，数据不足时应降低交易强度或进入观察模式。
- 所有触发条件必须写成可计算表达式和给用户看的中文文本。
- 股票评分和 operator_breakdown 只能来自工具或算子 observation，不得自行改写任何数字。
- 数据缺失、工具错误或证据冲突时，不允许给出进攻型交易建议。
- 最终回答必须只输出一个 JSON object，不要 markdown，不要代码块，不要解释性前后缀。
- 最终 JSON 必须符合下面的盘前报告 schema。

盘前报告 schema:
{schema}
"""


PRE_MARKET_AGENT_NODES = [
    {
        "name": "market_sentiment_agent",
        "title": "市场情绪 Agent",
        "tool_names": MARKET_TOOL_NAMES,
        "system_prompt": """你是市场情绪 Agent。

职责：
- 判断今天是否适合承担风险。
- 使用 scheduled_task 的 market、as_of 作为统一市场和数据截止时间。
- 调用 get_market_snapshot、get_market_breadth、get_macro_snapshot 获取数据。
- 国内宏观必需指标：official_pmi、social_financing_yoy、m1_yoy、m2_yoy。
- 调用 get_capital_behavior，必需指标为 margin_balance_change_pct、etf_share_change_pct。
- 调用 get_liquidity_environment，必需指标为 dr007、cn_10y_yield。
- get_derivatives_sentiment 提供 etf300_volume_pcr、etf300_oi_pcr、etf300_iv_pct、if_basis_pct 等补充证据。
- 可并行请求互不依赖的快照；月度宏观按 published_at 判断可用性，不能把 observation_period 当发布时间。
- 输出 assessments，分别说明交易情绪、资金与流动性、宏观环境、外部压力及综合判断；每项包含 summary、evidence_refs（工具名）和 missing_indicators。无外部证据时明确外部压力未评估。
- assessments 的固定键为 trading_sentiment、capital_liquidity、macro_environment、external_pressure、overall。
- 当前 capital_intensity 只是成交活跃度代理分，真实资金行为应单独解释；禁止将成交总额或成交额比描述为净流入。
- 先 search_news，再把返回的 news 原文传入 analyze_news_sentiment。
- 将宽度和新闻工具返回值原样传入 compute_market_regime_metrics，三项分数必须直接引用其输出。
- 样例不是实时行情；区分 source_timestamp 与 as_of，保留 mock 标记及证据来源。
- 关键字段缺失时输出 data_missing=true、观察模式，缺失分数填 null，禁止补造。
- direction 只能为 bullish/neutral/bearish；trading_mode 只能为 attack/defense/rotation/observe。
- 输出 JSON object，包含 direction、trading_mode、sentiment_score、capital_intensity、volatility_risk、summary、forbidden_conditions。
- forbidden_conditions 必须是可计算表达式和中文文本。
- 工具输出是 mock 数据，只用于流程测试，不构成投资建议。""",
        "instruction": "完成市场情绪和宏观风险判断。",
    },
    {
        "name": "industry_research_agent",
        "title": "行业研究 Agent",
        "system_prompt": """你是行业研究 Agent。

职责：
- 基于上游市场情绪结论筛选 2 到 4 个行业方向。
- 必须调用 universe_screen、news_sentiment 或 web_search 等工具补充证据。
- 输出 JSON object，包含 industries 数组。
- 每个行业必须包含 score、confidence、thesis、evidence、counterpoints、invalid_conditions。
- 下游会直接读取你的结论，请保持结构化。""",
        "instruction": "根据市场情绪结论筛选候选行业。",
    },
    {
        "name": "stock_discovery_agent",
        "title": "个股发现 Agent",
        "system_prompt": """你是个股发现 Agent。

职责：
- 只在上游候选行业内部选择个股，不做无约束全市场扫描。
- 必须调用 market_snapshot、technical_indicators、fundamentals 或 news_sentiment。
- 输出 JSON object，包含 stocks 数组。
- 每只股票必须说明行业、初步入选理由和需要关注的风险。""",
        "instruction": "在候选行业内下钻个股并形成候选股票池。",
    },
    {
        "name": "operator_agent",
        "title": "金融算子 Agent",
        "system_prompt": """你是金融算子 Agent。

职责：
- 调用确定性工具获得技术面、基本面、行情和风险数据。
- 输出 JSON object，包含 operator_evaluations 数组。
- 所有数字只能来自工具 observation，不得自行修改或编造。
- 如果数据缺失，必须标记 data_missing，不允许补数字。""",
        "instruction": "对候选股票计算金融算子评分和原始算子值。",
    },
    {
        "name": "risk_agent",
        "title": "风控 Agent",
        "system_prompt": """你是独立风控 Agent。

职责：
- 基于上游市场、行业、个股和算子结果进行独立审核。
- 必须调用 portfolio_risk 工具。
- 风控拥有否决权，可以 passed、reduced、blocked、manual_review 或 pending。
- 数据缺失、模型结构化失败或证据冲突时必须降低风险或阻断交易。
- 输出 JSON object，包含 risk_review。""",
        "instruction": "独立审核所有候选交易，输出风控结论。",
    },
    {
        "name": "trade_plan_agent",
        "title": "交易计划 Agent",
        "system_prompt": """你是交易计划 Agent，也是盘前报告汇总节点。

职责：
- 汇总所有上游 Agent 结论，生成最终 PreMarketReport。
- 风控结论拥有否决权，不得绕过 risk_review。
- 所有触发条件必须包含机器可计算 expression 和中文 text。
- 股票评分和 operator_breakdown 只能来自上游工具或算子结果。
- 最终回答必须只输出一个 JSON object，不要 markdown，不要代码块，不要解释性前后缀。
- 最终 JSON 必须符合下面的 schema。

PreMarketReport schema:
{schema}""",
        "instruction": "汇总上游结论，生成最终结构化 PreMarketReport。",
        "final": True,
    },
]


class PreMarketWorkflow:
    """Run the scheduled pre-market workflow as chained specialist agents."""

    def __init__(self, model, tool_environment, max_steps=8):
        self.model = model
        self.tool_environment = tool_environment
        self.max_steps = max_steps

    def run(
        self,
        task=None,
        temperature=0,
        max_tokens=1200,
        model_extra_body=None,
        system_prompt=None,
        agent_system_prompts=None,
        on_event=None,
        previous_report=None,
        previous_trade_date=None,
        execution_feedback="",
        manual_advice=False,
        calendar=None,
    ):
        workflow_context = str(task or DEFAULT_PRE_MARKET_TASK).strip()
        if not workflow_context:
            workflow_context = DEFAULT_PRE_MARKET_TASK
        node_results = []
        trace = []
        final_text = ""
        scheduled_at = datetime.now(timezone(timedelta(hours=8)))
        decision_context = None
        if manual_advice:
            decision_context = build_decision_context(previous_report, previous_trade_date,
                                                      scheduled_at.date().isoformat(), execution_feedback,
                                                      calendar=calendar)

        for index, node in enumerate(PRE_MARKET_AGENT_NODES, start=1):
            if on_event is not None:
                on_event(
                    "workflow_node_started",
                    {
                        "node": node["name"],
                        "title": node["title"],
                        "index": index,
                        "total": len(PRE_MARKET_AGENT_NODES),
                    },
                )
            result = self._run_node(
                node=node,
                workflow_context=workflow_context,
                upstream_results=node_results,
                temperature=temperature,
                max_tokens=max_tokens,
                model_extra_body=model_extra_body,
                system_prompt_override=_resolve_node_prompt_override(node, system_prompt, agent_system_prompts),
                on_event=on_event,
                decision_context=decision_context,
                scheduled_at=scheduled_at,
            )
            node_result = {
                "type": "workflow_node",
                "node": node["name"],
                "title": node["title"],
                "content": result.final,
            }
            node_results.append(node_result)
            trace.extend(_tag_node_trace(result.trace, node["name"], node["title"]))
            trace.append(node_result)
            if on_event is not None:
                on_event("workflow_node_finished", node_result)
            if node.get("final"):
                final_text = result.final

        try:
            report = parse_pre_market_report(final_text)
            final = final_text
        except ValueError as exc:
            report = build_report_from_trace(trace, str(exc))
            final = json.dumps(report, ensure_ascii=False, sort_keys=True)
        market_result = json.loads(node_results[0]["content"])
        report["market_state"].update({key: market_result[key] for key in (
            "direction", "trading_mode", "sentiment_score", "capital_intensity",
            "volatility_risk", "summary", "forbidden_conditions")})
        if market_result.get("data_missing"):
            report["risk_review"]["status"] = "blocked"
            report["risk_review"]["reason"] = "市场情绪节点数据或结论校验未通过。"
            report["trade_plan"] = []
            report["headline"] = "市场情绪校验未通过，今日观察。"
        if decision_context is not None:
            if report["report_date"] != decision_context["trade_date"]:
                report["risk_review"]["status"] = "blocked"
                report["risk_review"]["rejections"].append("模型报告日期不符，不能沿用历史建议作为今日建议。")
                report["trade_plan"] = []
            report["risk_review"]["manual_confirmations"].append(
                "仅供研究与人工决策；昨日建议不代表已成交，账户与可卖数量须重新核验。")
            if report["risk_review"]["status"] in ("blocked", "pending"):
                report["trade_plan"] = []
            report["strategy_revision"] = compare_strategy(decision_context, report)
        final = json.dumps(report, ensure_ascii=False, sort_keys=True)
        if on_event is not None:
            on_event("pre_market_report", {"report": report})
        return PreMarketWorkflowResult(final=final, trace=trace, report=report, node_results=node_results)

    def _run_node(
        self,
        node,
        workflow_context,
        upstream_results,
        temperature,
        max_tokens,
        model_extra_body,
        system_prompt_override,
        on_event,
        decision_context=None,
        scheduled_at=None,
    ):
        prompt = system_prompt_override or _node_system_prompt(node)
        if decision_context is not None:
            prompt += "\n\n" + REVISION_INSTRUCTION
        task = _node_user_message(node, workflow_context, upstream_results, decision_context, scheduled_at)
        environment = self.tool_environment.subset(node["tool_names"]) if node.get("tool_names") else self.tool_environment
        if decision_context is not None:
            # 权限在执行层限制，而非仅通过 SP 约定不下单。
            read_only_names = set(MARKET_TOOL_NAMES) | {
                "market_snapshot", "price_history", "technical_indicators", "universe_screen",
                "fundamentals", "news_sentiment", "macro_indicator", "portfolio_risk",
                "strategy_backtest", "web_search",
            }
            environment = environment.subset([tool.spec.name for tool in environment.tools
                                              if tool.spec.name in read_only_names])
        session = None
        if node["name"] == "market_sentiment_agent":
            session = MarketSentimentSession(environment, json.loads(task)["scheduled_task"]["as_of"])
            environment = session
        agent = ReActAgent(self.model, environment, max_steps=self.max_steps)
        result = agent.run(
            task,
            temperature=temperature,
            max_tokens=max_tokens,
            model_extra_body=model_extra_body,
            system_prompt=prompt,
            on_event=_node_event_emitter(on_event, node),
        )
        if session is not None:
            validated = session.validate_final(result.final)
            result.trace.append({"type": "validation", "raw_final": result.final,
                                 "result": validated})
            result.final = json.dumps(validated, ensure_ascii=False, sort_keys=True)
        return result


def build_pre_market_system_prompt():
    """Build the system prompt with the current report schema embedded."""

    return PRE_MARKET_SYSTEM_PROMPT.format(
        schema=json.dumps(pre_market_report_schema(), ensure_ascii=False, sort_keys=True)
    )


def pre_market_agent_prompts():
    """Return editable default system prompts for each workflow Agent."""

    return [
        {
            "name": node["name"],
            "title": node["title"],
            "system_prompt": _node_system_prompt(node),
            "instruction": node["instruction"],
            "tool_names": list(node.get("tool_names", [])),
        }
        for node in PRE_MARKET_AGENT_NODES
    ]


class PreMarketWorkflowResult:
    def __init__(self, final, trace, report, node_results=None):
        self.final = final
        self.trace = trace
        self.report = report
        self.node_results = node_results or []


def _node_system_prompt(node):
    prompt = node["system_prompt"]
    if "{schema}" in prompt:
        return prompt.format(schema=json.dumps(pre_market_report_schema(), ensure_ascii=False, sort_keys=True))
    return prompt


def _resolve_node_prompt_override(node, legacy_final_prompt=None, agent_system_prompts=None):
    prompts = agent_system_prompts or {}
    if not isinstance(prompts, dict):
        prompts = {}
    value = str(prompts.get(node["name"]) or "").strip()
    if value:
        return value
    if node.get("final") and legacy_final_prompt:
        return legacy_final_prompt
    return None


def _node_user_message(node, workflow_context, upstream_results, decision_context=None, scheduled_at=None):
    now = scheduled_at or datetime.now(timezone(timedelta(hours=8)))
    return json.dumps(
        {
            "scheduled_task": {
                "name": "daily_pre_market",
                "context": workflow_context,
                "market": "CN_A",
                "trade_date": now.date().isoformat(),
                "as_of": now.isoformat(),
                "session": "pre_market",
            },
            "current_agent": node["name"],
            "instruction": node["instruction"],
            "upstream_results": upstream_results,
            "decision_context": decision_context,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _node_event_emitter(callback, node):
    if callback is None:
        return None

    def emit(event, data):
        payload = dict(data)
        payload.setdefault("node", node["name"])
        payload.setdefault("node_title", node["title"])
        callback(event, payload)

    return emit


def _tag_node_trace(trace, node_name, node_title):
    tagged = []
    for item in trace:
        value = dict(item)
        value.setdefault("node", node_name)
        value.setdefault("node_title", node_title)
        tagged.append(value)
    return tagged


def build_report_from_trace(trace, parse_error=""):
    observations = [item for item in trace if item.get("type") == "tool"]
    snapshots = [item["output"] for item in observations if item.get("name") == "market_snapshot"]
    technicals = [item["output"] for item in observations if item.get("name") == "technical_indicators"]
    fundamentals = [item["output"] for item in observations if item.get("name") == "fundamentals"]
    sentiments = [item["output"] for item in observations if item.get("name") == "news_sentiment"]
    risks = [item["output"] for item in observations if item.get("name") == "portfolio_risk"]
    screens = [item["output"] for item in observations if item.get("name") == "universe_screen"]

    primary_symbol = _first_symbol(snapshots, fundamentals, technicals, screens)
    snapshot = _find_symbol_output(snapshots, primary_symbol)
    technical = _find_symbol_output(technicals, primary_symbol)
    fundamental = _find_symbol_output(fundamentals, primary_symbol)
    portfolio_risk = risks[0] if risks else {}
    sentiment = sentiments[0] if sentiments else {}
    direction = "bearish" if snapshot.get("regime") == "risk_off" else "neutral"
    trading_mode = "observe" if direction == "bearish" or portfolio_risk.get("data_missing") else "rotation"
    risk_status = "reduced" if trading_mode == "observe" else "manual_review"
    industry = str((screens[0] if screens else {}).get("universe") or "AI算力与半导体")

    sentiment_score = _sentiment_to_score(sentiment.get("sentiment_score"))
    capital_intensity = _score_from_fraction((screens[0].get("matches") or [{}])[0].get("liquidity_score")) if screens else 45
    volatility_risk = _volatility_to_score(technical.get("annualized_volatility"), portfolio_risk.get("estimated_volatility"))
    total_score = int(round((capital_intensity + sentiment_score + max(0, 100 - volatility_risk)) / 3))

    buy_conditions = [
        {
            "condition_id": "cond_buy_trend",
            "expression": "{0}.ma_20_vs_60 == 'above'".format(primary_symbol),
            "text": "20日均线位于60日均线上方后再考虑买入",
        },
        {
            "condition_id": "cond_buy_market",
            "expression": "market_state.trading_mode != 'observe'",
            "text": "市场交易模式脱离观察状态",
        },
    ]
    no_trade_conditions = [
        {
            "condition_id": "cond_no_trade_risk_off",
            "expression": "{0}.regime == 'risk_off'".format(primary_symbol),
            "text": "标的或市场快照处于 risk_off 状态",
        }
    ]

    return {
        "report_date": date.today().isoformat(),
        "headline": "{0} 盘前观察：{1}".format(industry, "暂不进攻" if trading_mode == "observe" else "等待确认"),
        "market_state": {
            "direction": direction,
            "trading_mode": trading_mode,
            "sentiment_score": sentiment_score,
            "capital_intensity": capital_intensity,
            "volatility_risk": volatility_risk,
            "summary": "根据已完成工具 observation 自动合成。模型最终 JSON 解析失败，系统降级为确定性报告。",
            "forbidden_conditions": no_trade_conditions,
        },
        "industries": [
            {
                "industry": industry,
                "score": total_score,
                "confidence": 55,
                "thesis": "候选池和情绪工具显示该方向仍有关注度，但风险状态要求先观察。",
                "evidence": _compact_industry_evidence(screens, sentiments, snapshots),
                "counterpoints": ["报告由工具 observation 兜底生成，缺少完整多 Agent 交叉验证。"],
                "invalid_conditions": no_trade_conditions,
            }
        ],
        "stocks": [
            {
                "symbol": primary_symbol,
                "name": primary_symbol,
                "industry": industry,
                "total_score": total_score,
                "quality": 80 if fundamental.get("quality") == "high" else 60,
                "momentum": _momentum_to_score(technical.get("momentum_60d")),
                "valuation": _valuation_to_score(fundamental.get("forward_pe")),
                "liquidity": capital_intensity,
                "crowding": 70 if technical.get("rsi_14", 0) >= 65 else 45,
                "risk_score": volatility_risk,
                "suggested_position": "0%" if trading_mode == "observe" else "5%",
                "operator_breakdown": _operator_breakdown(snapshot, technical, fundamental),
                "reason": "基于行情、技术、基本面和风险 observation 自动合成，未使用模型改写算子数字。",
                "buy_conditions": buy_conditions,
                "stop_loss_conditions": [
                    {
                        "condition_id": "cond_stop_loss",
                        "expression": "{0}.change_pct <= -0.05".format(primary_symbol),
                        "text": "单日跌幅达到或超过5%时止损",
                    }
                ],
            }
        ],
        "risk_review": {
            "status": risk_status,
            "reason": "存在风险状态或模型结构化输出失败，风控默认降低交易强度。",
            "hard_limits": {
                "single_stock_max": "5%",
                "single_industry_max": "10%",
                "daily_loss_limit": "0.8R",
            },
            "rejections": ["结构化输出解析失败：{0}".format(parse_error)] if parse_error else [],
            "manual_confirmations": ["需要人工确认后再执行任何交易。"],
        },
        "trade_plan": [
            {
                "symbol": primary_symbol,
                "name": primary_symbol,
                "side": "avoid" if trading_mode == "observe" else "hold",
                "first_position": "0%",
                "max_position": "5%",
                "buy_conditions": buy_conditions,
                "add_conditions": [],
                "reduce_conditions": [],
                "stop_loss_conditions": [
                    {
                        "condition_id": "cond_stop_loss",
                        "expression": "{0}.change_pct <= -0.05".format(primary_symbol),
                        "text": "单日跌幅达到或超过5%时止损",
                    }
                ],
                "no_trade_conditions": no_trade_conditions,
            }
        ],
        "evidence_chain": _evidence_chain_from_observations(observations),
        "summary": "本报告由工具 observation 兜底生成，用于保证盘前工作台结构化展示不中断。",
    }


def _first_symbol(snapshots, fundamentals, technicals, screens):
    for group in (snapshots, fundamentals, technicals):
        if group and group[0].get("symbol"):
            return str(group[0]["symbol"])
    if screens:
        matches = screens[0].get("matches") or []
        if matches and matches[0].get("symbol"):
            return str(matches[0]["symbol"])
    return "UNKNOWN"


def _find_symbol_output(outputs, symbol):
    for output in outputs:
        if output.get("symbol") == symbol:
            return output
    return outputs[0] if outputs else {}


def _sentiment_to_score(value):
    if value is None:
        return 50
    return max(0, min(100, int(round(50 + float(value) * 100))))


def _score_from_fraction(value):
    if value is None:
        return 50
    return max(0, min(100, int(round(float(value) * 100))))


def _volatility_to_score(*values):
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return 50
    return max(0, min(100, int(round(max(numeric) * 300))))


def _momentum_to_score(value):
    if value is None:
        return 50
    return max(0, min(100, int(round(50 + float(value) * 100))))


def _valuation_to_score(value):
    if value is None:
        return 50
    return max(0, min(100, int(round(100 - min(float(value), 80)))))


def _operator_breakdown(snapshot, technical, fundamental):
    return {
        "roe_ttm": 0,
        "gross_margin": float(fundamental.get("gross_margin") or 0),
        "debt_ratio": float(fundamental.get("net_debt_to_ebitda") or 0),
        "rs_20d": 0,
        "rs_60d": float(technical.get("momentum_60d") or 0),
        "pe_ttm": float(fundamental.get("forward_pe") or 0),
        "pe_percentile_5y": 0,
        "volume_avg_20d": float(snapshot.get("volume") or 0),
        "turnover_rate": 0,
        "short_term_gain_20d": float(snapshot.get("change_pct") or 0),
        "margin_balance_change": 0,
    }


def _compact_industry_evidence(screens, sentiments, snapshots):
    evidence = []
    if screens:
        evidence.append({"type": "universe_screen", "source": "universe_screen", "value": screens[0], "timestamp": ""})
    if sentiments:
        evidence.append({"type": "sentiment", "source": "news_sentiment", "value": sentiments[0], "timestamp": ""})
    if snapshots:
        evidence.append({"type": "market", "source": "market_snapshot", "value": snapshots[0], "timestamp": ""})
    return evidence


def _evidence_chain_from_observations(observations):
    chain = []
    for index, item in enumerate(observations, start=1):
        chain.append(
            {
                "evidence_id": "evt_{0:03d}".format(index),
                "type": str(item.get("name") or "tool"),
                "source": str(item.get("name") or "tool"),
                "source_timestamp": date.today().isoformat(),
                "value": item.get("output") or {},
                "used_by": ["pre_market_workflow"],
                "influence": "用于生成盘前结构化报告。",
            }
        )
    return chain
