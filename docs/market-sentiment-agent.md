# 市场情绪 Agent 工具契约

当前阶段：本地 mock / DeepSeek observation 联调。所有输出强制标记 `is_mock=true`，不可视为真实市场观测。

## 职责与权限

workflow 注入市场、截止时间和上游上下文。该节点只允许调用以下九个工具，SP 可在 Dev 面板编辑；修改 SP 不会扩大工具权限。

| 工具 | 必需输入（均含带时区的 as_of） | data 输出 |
| --- | --- | --- |
| get_market_snapshot | market=CN_A、indices | quotes：价格、涨跌幅(%)、成交额(元)、交易状态、source_timestamp |
| get_market_breadth | market=CN_A、lookback_days(1–120) | 涨跌家数、涨跌停数、成交额比、年化波动率(%)、均线上方股票占比 |
| get_macro_snapshot | indicators | 国内宏观及兼容外围指标：值、单位、观察期、发布时间、口径 |
| get_capital_behavior | indicators | 两融余额变化、ETF份额变化、龙虎榜、大宗交易 |
| get_liquidity_environment | indicators | DR007、Shibor、政策利率、国债收益率 |
| get_derivatives_sentiment | indicators | 成交量PCR、持仓量PCR、模拟隐含波动率、IF基差 |
| search_news | query、start_at、limit(1–20) | news：news_id、title、summary、source、published_at、url |
| analyze_news_sentiment | news（直接传检索结果） | items：新闻 ID、情绪[-1,1]、相关性、类别；新闻数量和汇总情绪 |
| compute_market_regime_metrics | advancers、decliners、news_sentiment、turnover_ratio、annualized_volatility_pct | 三项评分、原始输入、formula_version |

统一返回：`data / source / mock / is_mock / as_of / data_version / missing_fields / warnings`。

指标目录见 `src/private_quant_lab/tools/market_indicators.py`。每项携带 `observation_period / published_at / frequency / methodology / unit`。历史固定样例不模拟交易日历，不声称是最新数据；所有发布时间也是 mock，不是真实统计发布日历。

必需指标：宏观 official_pmi、social_financing_yoy、m1_yoy、m2_yoy；资金 margin_balance_change_pct、etf_share_change_pct；流动性 dr007、cn_10y_yield。其余目录指标为补充项。北向净买入样例始终返回缺失，不能用成交总额替代。

月度数据按 published_at 与 as_of 比较，不因观察期属于上月就拒绝。真实数据的修订版本、过期阈值及交易日历仍待接入。

## 调用顺序

1. 获取市场快照、市场宽度、宏观、资金行为、流动性快照；衍生品按需补充。
2. 检索新闻，将完整 news 数组传入情绪分析。
3. 将宽度及情绪结果中的数值传入评分工具。
4. Agent 引用评分、形成市场方向与交易模式，附带证据和缺失标记。

数据工具允许 DeepSeek 模拟符合字段结构的数据；非法字段类型、超出截止时间、新闻 ID 改变时降级本地样例。情绪汇总由逐条情绪在本地计算。

评分工具不调用模型。原型公式 `prototype-v1`：

- 情绪温度 = `(news_sentiment + 1) * 25 + advancers / (advancers + decliners) * 50`。
- 兼容字段 capital_intensity = `turnover_ratio * 50`，只代表成交活跃度代理，不是净流入或完整资金强度。
- 波动风险 = `annualized_volatility_pct * 2`。

结果截断至 0–100，保留两位小数。涨跌家数总和为零时返回缺失。公式用于流程验证，尚未经过投资研究验证。

工作流的市场节点使用独立 `MarketSentimentSession`。该会话强制将 as_of 绑定至任务截止时间、将新闻输入绑定至检索结果，并将评分输入绑定至宽度和情绪工具结果。重新查询宽度或新闻会使相应旧评分失效。单独调用底层工具仍允许自由输入，便于工具单测。

最终结果必须包含 direction、trading_mode、三项评分、summary、非空 forbidden_conditions（expression/text）。方向枚举为 bullish/neutral/bearish，模式枚举为 attack/defense/rotation/observe。

市场快照、宽度、检索、情绪及评分链路要求有效结果；资金、流动性、宏观按必需指标检查，补充项缺失不单独阻断。`indicator_coverage` 展示已提供、必需缺失、补充缺失及工具错误。最终分数必须等于评分工具输出。校验不通过时返回 `data_missing=true`、三项分数为 null、观察模式及 validation_errors；工作流最终报告强制风控 blocked 并清空交易计划。原始模型输出保留在 trace，校验后的结论传给下游。

新增 `assessments` 五项结论：trading_sentiment、capital_liquidity、macro_environment、external_pressure、overall。每项含 summary、evidence_refs（本次已调用工具名）、missing_indicators。未取得外围证据时需声明未评估，不得伪造引用。引用存在性由服务端校验，观点是否被引用内容支持仍需要研究质量评估。

新维度目前用于分项解释，尚未加入综合评分权重。评分结果的 score_semantics 明确记录这个边界；不会将任意线性权重作为已验证的金融模型。独立外围工具、估值工具及另类指标属于后续扩展。

当前仅验证条件表达式非空，尚未实现指标白名单与表达式执行器；固定历史 mock 也不具备真实数据时效校验。这些边界需要在真实数据接入前补齐。

## 本地测试

### 工具测试页

启动 `python3 scripts/run_react_web.py --host 127.0.0.1 --port 8891`，打开 `http://127.0.0.1:8891/tools`（工作流首页也有“工具测试”入口）。

选择工具后可查看参数 Schema、载入示例、编辑 JSON 并直接执行。页面展示结果树、原始响应、耗时、来源、缺失/降级状态和本页执行记录；结果可复制或下载。DeepSeek 模式的原始请求和响应在“模型请求”页签查询。

默认本地 Mock，不需要 API key。选择 DeepSeek Observation 才会请求模型，确定性评分工具始终本地执行。`get_market_snapshot` 已支持“真实数据 · 盘前日线”，其余工具仍为 mock。单工具调用不启动 Agent，也不受 MarketSentimentSession 的上游证据绑定约束；参数 Schema 仍在服务端验证。

真实指数模式使用免费 AKShare `stock_zh_index_daily_em`（东方财富日线），无需密钥。安装并运行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[market-data]'
.venv/bin/python scripts/run_react_web.py --host 127.0.0.1 --port 8891
```

支持代码：000001.SH、000300.SH、000905.SH、000016.SH、000852.SH、399001.SZ、399006.SZ、899050.BJ。模式统一排除 as_of 当天日线，在此前60个自然日内取最近两根日线计算涨跌幅；最新日线距截止日前一天超过14天时标记缺失。该14天检查是粗粒度过期保护，不替代交易日历。

结果返回 `is_mock=false`、真实来源、trade_date、fetched_at、逐标的 errors。请求失败、字段缺失和非有限数值不会用 mock 填补。source_timestamp 表示日线交易日收盘时间，不是精确发布时间；历史修订未验证，`point_in_time_verified=false`。只接入单工具测试页，完整 Agent 工作流仍保持 mock。

参考：[AKShare 指数文档](https://akshare.akfamily.xyz/data/index/index.html)。

执行记录仅保留在页面内存，最多30条；刷新后清空。不新增持久化日志存储。

接口：`GET /api/tool_catalog` 获取目录与示例及支持的 modes；`POST /api/tools/execute` 接收 `name / arguments / mode(local|llm|real) / model`，返回原始工具结果、run_id 和 elapsed_ms。

无需 API key：

```bash
python3 -m unittest discover -s tests -p 'test_market_sentiment_tools.py' -v
python3 -m unittest discover -s tests -p 'test_market_sentiment_agent.py' -v
```

覆盖完整新闻到评分链路、时间截止、空新闻、参数越界、工具权限、确定性评分和 observation 降级。

单独运行 Agent（需要配置模型 API，下面的命令会产生真实模型请求）：

```bash
# 模型自主调用工具，工具返回本地固定样例。
python3 scripts/smoke_market_sentiment.py --as-of '2026-09-05T08:45:00+08:00'

# 模型自主调用工具，并让 DeepSeek 模拟 observation。
python3 scripts/smoke_market_sentiment.py --as-of '2026-09-05T08:45:00+08:00' --llm-observation
```

可用 `--sp-file 路径` 测试独立 SP。控制台逐步输出模型和工具事件，最后输出 validated_result；校验未通过时退出码为 1。不会启动其他 Agent，也不会发起交易。
