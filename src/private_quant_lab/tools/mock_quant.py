"""Mock quant tools for local agent-flow tests.

这个文件是第一版“量化工具箱”的 mock 实现，重点不是数据真实性，
而是让 Agent 的 ReAct 流程可以稳定走完：

1. 模型选择工具，输出 Action / Action Input。
2. 本地 ToolEnvironment 根据工具名执行这里的函数。
3. 函数返回固定结构的 mock observation，或者交给 DeepSeek 模拟 observation。
4. Agent 把 observation 回填给模型，模型继续调用工具或输出 Final。

所有输出里都有 ``mock=True``，提醒上层不要把这些结果当真实行情或交易结果。
"""

from .environment import ToolEnvironment
from .llm_observation import LLMObservationMocker
from .types import QuantTool, ToolSpec


def common_quant_tool_names():
    """返回常见量化工具名称列表。

    输入：无。
    输出：工具名字符串列表，用于展示当前 mock 环境覆盖了哪些能力。
    """

    return [
        "market_snapshot",
        "price_history",
        "technical_indicators",
        "universe_screen",
        "fundamentals",
        "news_sentiment",
        "macro_indicator",
        "portfolio_risk",
        "strategy_backtest",
        "paper_order",
        "web_search",
    ]


def build_mock_quant_environment(observation_model=None):
    """构建一个确定性的 mock 量化工具环境。

    输入：
        observation_model: 可选 ChatModel。传入 DeepSeek/OpenAI-compatible 模型后，
            工具 observation 会由模型按 schema 模拟；不传则使用本地固定 mock。

    输出：ToolEnvironment，里面注册了下面这些 QuantTool。

    ToolSpec 是给 Agent / LLM 看的工具说明：
    - name: 工具名，模型在 Action 中必须原样填写。
    - description: 工具功能描述。
    - input_schema: 工具入参 JSON schema，方便模型组织 Action Input。
    """

    observation_mocker = (
        LLMObservationMocker(observation_model) if observation_model is not None else None
    )

    return ToolEnvironment(
        [
            # 功能：获取单个标的的最新市场快照。
            # 输入：{"symbol": "NVDA"}
            # 输出：symbol, price, change_pct, volume, regime, mock。
            QuantTool(
                ToolSpec(
                    name="market_snapshot",
                    description="Get mocked latest quote, intraday change, volume, and regime tags for a symbol.",
                    input_schema={
                        "type": "object",
                        "properties": {"symbol": {"type": "string"}},
                        "required": ["symbol"],
                    },
                ),
                _market_snapshot,
                observation_mocker,
            ),
            # 功能：获取单个标的的历史 OHLCV K 线片段。
            # 输入：{"symbol": "SPY", "lookback_days": 20}
            # 输出：symbol, lookback_days, bars[day/open/high/low/close/volume], mock。
            QuantTool(
                ToolSpec(
                    name="price_history",
                    description="Get mocked OHLCV bars for a symbol and lookback window.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "lookback_days": {"type": "integer"},
                        },
                        "required": ["symbol"],
                    },
                ),
                _price_history,
                observation_mocker,
            ),
            # 功能：获取趋势、动量、波动率、RSI、均线关系等技术指标。
            # 输入：{"symbol": "QQQ", "indicators": ["rsi", "momentum"]}
            # 输出：symbol, trend, rsi_14, ma_20_vs_60, annualized_volatility, momentum_60d, mock。
            QuantTool(
                ToolSpec(
                    name="technical_indicators",
                    description="Compute mocked trend, momentum, volatility, RSI, and moving-average signals.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "indicators": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["symbol"],
                    },
                ),
                _technical_indicators,
                observation_mocker,
            ),
            # 功能：在股票或 ETF 池中做简单筛选排序。
            # 输入：{"universe": "us_large_cap", "filters": {"min_liquidity": 0.8}, "limit": 5}
            # 输出：universe, matches[symbol/rank/liquidity_score/momentum_score], mock。
            QuantTool(
                ToolSpec(
                    name="universe_screen",
                    description="Screen a mocked stock/ETF universe by liquidity, momentum, volatility, and valuation filters.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "universe": {"type": "string"},
                            "filters": {"type": "object"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["universe"],
                    },
                ),
                _universe_screen,
                observation_mocker,
            ),
            # 功能：获取单个标的的基本面质量、增长、估值、杠杆指标。
            # 输入：{"symbol": "MSFT"}
            # 输出：symbol, revenue_growth_yoy, gross_margin, net_debt_to_ebitda, forward_pe, quality, mock。
            QuantTool(
                ToolSpec(
                    name="fundamentals",
                    description="Get mocked revenue growth, margin, leverage, valuation, and quality metrics.",
                    input_schema={
                        "type": "object",
                        "properties": {"symbol": {"type": "string"}},
                        "required": ["symbol"],
                    },
                ),
                _fundamentals,
                observation_mocker,
            ),
            # 功能：获取标的或主题的新闻情绪和主要催化因素。
            # 输入：{"query": "NVDA", "lookback_days": 7}
            # 输出：query, sentiment, sentiment_score, catalysts, mock。
            QuantTool(
                ToolSpec(
                    name="news_sentiment",
                    description="Get mocked recent news sentiment and notable catalysts for a symbol or topic.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "lookback_days": {"type": "integer"},
                        },
                        "required": ["query"],
                    },
                ),
                _news_sentiment,
                observation_mocker,
            ),
            # 功能：获取利率、CPI、PMI、VIX 等宏观指标上下文。
            # 输入：{"indicator": "vix"}
            # 输出：indicator, value, risk, mock。
            QuantTool(
                ToolSpec(
                    name="macro_indicator",
                    description="Get mocked macro values such as rates, CPI, PMI, USD, or volatility index context.",
                    input_schema={
                        "type": "object",
                        "properties": {"indicator": {"type": "string"}},
                        "required": ["indicator"],
                    },
                ),
                _macro_indicator,
                observation_mocker,
            ),
            # 功能：估算组合层面的风险暴露、波动率、回撤和主要风险来源。
            # 输入：{"positions": [{"symbol": "NVDA", "weight": 0.4}, {"symbol": "SPY", "weight": 0.6}]}
            # 输出：positions, gross_exposure, estimated_volatility, max_drawdown_estimate, top_risk, mock。
            QuantTool(
                ToolSpec(
                    name="portfolio_risk",
                    description="Estimate mocked portfolio exposure, volatility, drawdown, beta, and concentration risk.",
                    input_schema={
                        "type": "object",
                        "properties": {"positions": {"type": "array"}},
                        "required": ["positions"],
                    },
                ),
                _portfolio_risk,
                observation_mocker,
            ),
            # 功能：运行一个 mock 策略回测，返回常见绩效指标。
            # 输入：{"strategy": "momentum", "universe": "us_large_cap", "start": "2020-01-01", "end": "2025-12-31"}
            # 输出：strategy, universe, cagr, sharpe, max_drawdown, turnover, hit_rate, mock。
            QuantTool(
                ToolSpec(
                    name="strategy_backtest",
                    description="Run a mocked strategy backtest with returns, drawdown, Sharpe, turnover, and hit rate.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "strategy": {"type": "string"},
                            "universe": {"type": "string"},
                            "start": {"type": "string"},
                            "end": {"type": "string"},
                        },
                        "required": ["strategy", "universe"],
                    },
                ),
                _strategy_backtest,
                observation_mocker,
            ),
            # 功能：校验并暂存一笔 mock 纸面交易订单，不连接真实券商。
            # 输入：{"symbol": "NVDA", "side": "buy", "quantity": 10, "order_type": "market"}
            # 输出：order_id, symbol, side, quantity, order_type, status, mock。
            QuantTool(
                ToolSpec(
                    name="paper_order",
                    description="Validate and stage a mocked paper-trading order without touching a live broker.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "side": {"type": "string"},
                            "quantity": {"type": "number"},
                            "order_type": {"type": "string"},
                        },
                        "required": ["symbol", "side", "quantity", "order_type"],
                    },
                ),
                _paper_order,
                observation_mocker,
            ),
            # 功能：模拟互联网搜索，用于让 Agent 练习“先搜信息再分析”的流程。
            # 输入：{"query": "NVDA latest earnings AI demand", "limit": 3}
            # 输出：query, results[title/url/snippet/published_at/source], mock。
            QuantTool(
                ToolSpec(
                    name="web_search",
                    description="Search the web for mocked public information, news, filings, or macro context.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["query"],
                    },
                ),
                _web_search,
                observation_mocker,
            ),
        ]
    )


def _symbol(arguments):
    """从工具入参中读取 symbol，并统一转成大写。"""

    return str(arguments.get("symbol", "SPY")).upper()


def _score(text):
    """把文本转成稳定分数，让 mock 输出对同一输入保持确定性。"""

    return sum(ord(char) for char in str(text).upper())


def _market_snapshot(arguments):
    """市场快照工具实现。

    输入：
        arguments["symbol"]: 标的代码，例如 "NVDA"。

    输出：
        symbol: 标的代码。
        price: mock 最新价格。
        change_pct: mock 日内涨跌幅，小数形式，例如 -0.07 表示 -7%。
        volume: mock 成交量。
        regime: mock 市场状态，risk_on 或 risk_off。
        mock: 固定为 True。
    """

    symbol = _symbol(arguments)
    score = _score(symbol)
    price = round(80 + score % 420 + (score % 17) / 10, 2)
    change_pct = round(((score % 21) - 10) / 100, 4)
    return {
        "symbol": symbol,
        "price": price,
        "change_pct": change_pct,
        "volume": 1_000_000 + score * 137,
        "regime": "risk_on" if change_pct >= 0 else "risk_off",
        "mock": True,
    }


def _price_history(arguments):
    """历史价格工具实现。

    输入：
        arguments["symbol"]: 标的代码。
        arguments["lookback_days"]: 回看天数，可选，默认 20，限制在 1 到 60。

    输出：
        symbol: 标的代码。
        lookback_days: 实际使用的回看天数。
        bars: mock OHLCV 列表，最多返回 8 根，避免 prompt 过长。
        mock: 固定为 True。
    """

    symbol = _symbol(arguments)
    lookback_days = int(arguments.get("lookback_days", 20))
    lookback_days = max(1, min(lookback_days, 60))
    base = 80 + _score(symbol) % 120
    bars = []
    for index in range(min(lookback_days, 8)):
        close = round(base + index * 1.3 + (index % 3) * 0.4, 2)
        bars.append(
            {
                "day": "T-{0}".format(lookback_days - index),
                "open": round(close - 0.8, 2),
                "high": round(close + 1.1, 2),
                "low": round(close - 1.4, 2),
                "close": close,
                "volume": 900_000 + index * 42_000,
            }
        )
    return {"symbol": symbol, "lookback_days": lookback_days, "bars": bars, "mock": True}


def _technical_indicators(arguments):
    """技术指标工具实现。

    输入：
        arguments["symbol"]: 标的代码。
        arguments["indicators"]: 指标名列表，可选；当前 mock 会返回固定字段集合。

    输出：
        trend: 趋势状态，up 或 sideways。
        rsi_14: mock 14 日 RSI。
        ma_20_vs_60: 20 日均线相对 60 日均线的位置，above 或 below。
        annualized_volatility: mock 年化波动率。
        momentum_60d: mock 60 日动量。
        mock: 固定为 True。
    """

    symbol = _symbol(arguments)
    score = _score(symbol)
    return {
        "symbol": symbol,
        "trend": "up" if score % 2 == 0 else "sideways",
        "rsi_14": 45 + score % 25,
        "ma_20_vs_60": "above" if score % 3 else "below",
        "annualized_volatility": round(0.16 + (score % 14) / 100, 3),
        "momentum_60d": round(((score % 31) - 8) / 100, 4),
        "mock": True,
    }


def _universe_screen(arguments):
    """股票 / ETF 池筛选工具实现。

    输入：
        arguments["universe"]: 股票池或 ETF 池名称，例如 "us_large_cap"。
        arguments["filters"]: 过滤条件，可选；当前 mock 不真实计算过滤条件。
        arguments["limit"]: 返回数量，可选，限制在 1 到 10。

    输出：
        universe: 输入的股票池名称。
        matches: 候选列表，包含 symbol, rank, liquidity_score, momentum_score。
        mock: 固定为 True。
    """

    universe = str(arguments.get("universe", "us_large_cap"))
    limit = max(1, min(int(arguments.get("limit", 5)), 10))
    candidates = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "AVGO", "LLY", "TSM", "SPY"]
    return {
        "universe": universe,
        "matches": [
            {
                "symbol": symbol,
                "rank": index + 1,
                "liquidity_score": round(0.95 - index * 0.03, 2),
                "momentum_score": round(0.88 - index * 0.04, 2),
            }
            for index, symbol in enumerate(candidates[:limit])
        ],
        "mock": True,
    }


def _fundamentals(arguments):
    """基本面工具实现。

    输入：
        arguments["symbol"]: 标的代码。

    输出：
        revenue_growth_yoy: mock 同比收入增速。
        gross_margin: mock 毛利率。
        net_debt_to_ebitda: mock 净债务 / EBITDA。
        forward_pe: mock 远期市盈率。
        quality: mock 质量标签，high 或 medium。
        mock: 固定为 True。
    """

    symbol = _symbol(arguments)
    score = _score(symbol)
    return {
        "symbol": symbol,
        "revenue_growth_yoy": round(0.04 + (score % 24) / 100, 3),
        "gross_margin": round(0.38 + (score % 30) / 100, 3),
        "net_debt_to_ebitda": round((score % 18) / 10, 2),
        "forward_pe": round(12 + score % 35, 1),
        "quality": "high" if score % 5 else "medium",
        "mock": True,
    }


def _news_sentiment(arguments):
    """新闻情绪工具实现。

    输入：
        arguments["query"]: 标的、行业或主题关键词。
        arguments["lookback_days"]: 新闻回看天数，可选；当前 mock 不真实按天数过滤。

    输出：
        query: 输入关键词。
        sentiment: mock 情绪标签，positive 或 neutral。
        sentiment_score: mock 情绪分数。
        catalysts: mock 催化因素列表。
        mock: 固定为 True。
    """

    query = str(arguments.get("query", "market"))
    score = _score(query)
    return {
        "query": query,
        "sentiment": "positive" if score % 2 else "neutral",
        "sentiment_score": round(((score % 41) - 10) / 100, 2),
        "catalysts": ["earnings revisions", "sector rotation", "rates sensitivity"],
        "mock": True,
    }


def _macro_indicator(arguments):
    """宏观指标工具实现。

    输入：
        arguments["indicator"]: 宏观指标名称，例如 "rates", "cpi", "pmi", "vix"。

    输出：
        indicator: 输入指标名。
        value: mock 当前宏观状态描述。
        risk: mock 主要风险提示。
        mock: 固定为 True。
    """

    indicator = str(arguments.get("indicator", "rates")).lower()
    fixtures = {
        "rates": {"value": "policy path steady", "risk": "duration headwind easing"},
        "cpi": {"value": "disinflation trend intact", "risk": "services sticky"},
        "pmi": {"value": "manufacturing stabilizing", "risk": "new orders mixed"},
        "vix": {"value": "volatility contained", "risk": "event risk underpriced"},
    }
    return {"indicator": indicator, **fixtures.get(indicator, fixtures["rates"]), "mock": True}


def _portfolio_risk(arguments):
    """组合风险工具实现。

    输入：
        arguments["positions"]: 持仓列表，每个元素可以包含 symbol 和 weight。

    输出：
        positions: 持仓条数。
        gross_exposure: mock 总敞口，按 abs(weight) 求和。
        estimated_volatility: mock 组合年化波动率估计。
        max_drawdown_estimate: mock 最大回撤估计。
        top_risk: mock 主要风险来源。
        mock: 固定为 True。
    """

    positions = arguments.get("positions") or []
    gross = sum(abs(float(position.get("weight", 0))) for position in positions if isinstance(position, dict))
    return {
        "positions": len(positions),
        "gross_exposure": round(gross, 3),
        "estimated_volatility": round(0.11 + min(gross, 2.0) * 0.05, 3),
        "max_drawdown_estimate": round(-0.08 - min(gross, 2.0) * 0.07, 3),
        "top_risk": "concentration" if len(positions) < 5 else "market_beta",
        "mock": True,
    }


def _strategy_backtest(arguments):
    """策略回测工具实现。

    输入：
        arguments["strategy"]: 策略名称，例如 "momentum"。
        arguments["universe"]: 回测标的池，例如 "us_large_cap"。
        arguments["start"]: 开始日期，可选；当前 mock 不真实使用。
        arguments["end"]: 结束日期，可选；当前 mock 不真实使用。

    输出：
        cagr: mock 年化收益率。
        sharpe: mock 夏普比率。
        max_drawdown: mock 最大回撤。
        turnover: mock 换手率。
        hit_rate: mock 胜率。
        mock: 固定为 True。
    """

    strategy = str(arguments.get("strategy", "momentum"))
    universe = str(arguments.get("universe", "etf"))
    score = _score(strategy + universe)
    return {
        "strategy": strategy,
        "universe": universe,
        "cagr": round(0.06 + (score % 11) / 100, 3),
        "sharpe": round(0.8 + (score % 9) / 10, 2),
        "max_drawdown": round(-0.12 - (score % 12) / 100, 3),
        "turnover": round(0.35 + (score % 8) / 10, 2),
        "hit_rate": round(0.48 + (score % 12) / 100, 2),
        "mock": True,
    }


def _paper_order(arguments):
    """纸面订单工具实现。

    输入：
        arguments["symbol"]: 标的代码。
        arguments["side"]: 方向，buy 或 sell。
        arguments["quantity"]: 数量，必须大于 0 才会 accepted。
        arguments["order_type"]: 订单类型，例如 market 或 limit。

    输出：
        order_id: mock 订单编号。
        status: accepted 或 rejected。
        其他字段回显 symbol, side, quantity, order_type。
        mock: 固定为 True。
    """

    symbol = _symbol(arguments)
    side = str(arguments.get("side", "buy")).lower()
    quantity = float(arguments.get("quantity", 0))
    order_type = str(arguments.get("order_type", "market")).lower()
    status = "accepted" if side in {"buy", "sell"} and quantity > 0 else "rejected"
    return {
        "order_id": "mock-{0}-{1}".format(symbol, int(quantity)),
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "order_type": order_type,
        "status": status,
        "mock": True,
    }


def _web_search(arguments):
    """网页搜索工具实现。

    输入：
        arguments["query"]: 搜索关键词。
        arguments["limit"]: 返回条数，可选，限制在 1 到 5。

    输出：
        query: 搜索关键词。
        results: mock 搜索结果列表，包含 title, url, snippet, published_at, source。
        mock: 固定为 True。

    注意：
        本地模式不会真的联网搜索；DeepSeek observation 模式也只是让模型模拟搜索结果。
        未来接真实搜索 API 时，可以保持同样输出结构替换这里的 handler。
    """

    query = str(arguments.get("query", "market news"))
    limit = max(1, min(int(arguments.get("limit", 3)), 5))
    templates = [
        ("Market update for {0}", "https://example.com/markets/{1}", "Recent market commentary mentions liquidity, rates, and earnings expectations."),
        ("Company catalyst watch: {0}", "https://example.com/news/{1}", "Analysts are watching guidance revisions, demand signals, and margin trends."),
        ("Macro context around {0}", "https://example.com/macro/{1}", "Rates, inflation expectations, and volatility remain important cross-asset inputs."),
        ("Risk monitor: {0}", "https://example.com/risk/{1}", "Positioning and valuation sensitivity are highlighted as near-term risks."),
        ("Research note: {0}", "https://example.com/research/{1}", "The note frames the topic with trend, sentiment, and valuation considerations."),
    ]
    slug = "-".join(query.lower().split())[:60] or "market"
    return {
        "query": query,
        "results": [
            {
                "title": title.format(query),
                "url": url.format(query, slug),
                "snippet": snippet,
                "published_at": "mock-recent",
                "source": "mock_search",
            }
            for title, url, snippet in templates[:limit]
        ],
        "mock": True,
    }
