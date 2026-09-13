"""pysnowball 固定版本的完整数据接口清单；凭据管理不作为模型工具。"""

from copy import deepcopy

UPSTREAM_COMMIT = "e85fe550c5daed4ad1429d1f4e048dab239df921"
SPECS = {}


def string(description, pattern=None, default=None, max_length=64):
    value = {"type": "string", "description": description, "minLength": 1, "maxLength": max_length}
    if pattern:
        value["pattern"] = pattern
    if default is not None:
        value["default"] = default
    return value


def integer(description, default=None, minimum=1, maximum=500):
    value = {"type": "integer", "description": description, "minimum": minimum, "maximum": maximum}
    if default is not None:
        value["default"] = default
    return value


SYMBOL = string("上游证券代码，如 SH600000、SZ000001、00700 或 AAPL；不自动转换", r"^[A-Z0-9][A-Z0-9.-]{0,23}$", max_length=24)
SYMBOLS = string("逗号分隔的证券代码，最多 10 个", r"^[A-Z0-9][A-Z0-9.,-]{0,249}$", max_length=250)
INDEX = string("中证指数代码，例如 000300", r"^[0-9]{6}$")
FUND = string("基金代码，例如 000001", r"^[0-9]{6}$")
CUBE = string("雪球组合代码，例如 ZH000001", r"^ZH[0-9]{6,12}$")
PAGE = integer("页码；仅查询这一页，不自动翻页", 1, maximum=100)


def add(name, title, group, params, example, provider="xueqiu", auth=True, sensitive=False, notes=""):
    SPECS[name] = {
        "name": "snowball_" + name, "function": name, "description": title,
        "group": group, "provider": provider, "requires_token": auth,
        "sensitive": sensitive, "notes": notes,
        "schema": {"type": "object", "additionalProperties": False,
                   "properties": deepcopy(params),
                   "required": [key for key, value in params.items() if "default" not in value]},
        "example": example,
    }


for name, title in (("quotec", "批量行情快照"), ("pankou", "盘口报价"), ("quote_detail", "行情详情")):
    key = "symbols" if name == "quotec" else "symbol"
    add(name, title, "雪球 · 行情", {key: SYMBOLS if name == "quotec" else SYMBOL},
        {key: "SH600000"}, auth=name != "quotec")
add("kline", "K线；上游以请求时刻为截止时间", "雪球 · 行情",
    {"symbol": SYMBOL, "period": dict(string("K线周期", default="day"), enum=["day", "week", "month", "quarter", "year", "60m", "30m", "15m", "5m", "1m"]),
     "count": integer("K线数量", 284, maximum=1000)}, {"symbol": "SH600000", "period": "day", "count": 30})

for name, title in (("cash_flow", "现金流量表"), ("indicator", "财务指标"), ("balance", "资产负债表"),
                    ("income", "利润表"), ("business", "主营业务")):
    add(name, title, "雪球 · 财务",
        {"symbol": SYMBOL, "is_annals": dict(integer("1 仅年报，0 全部报告", 0, 0, 1), enum=[0, 1]),
         "count": integer("报告数量", 10, maximum=100)}, {"symbol": "SH600000", "is_annals": 0, "count": 10})
    if name != "business":
        add(name + "_v2", title + " V2", "雪球 · 财务", {
            "symbol": SYMBOL, "count": integer("报告数量", 10, maximum=100),
            "region": dict(string("市场地区", default="cn"), enum=["cn", "hk", "us"]),
            "type": dict(string("报告周期", default="all"), enum=["all", "Q1", "Q2", "Q3", "Q4"]),
            "is_detail": {"type": "boolean", "description": "是否查询明细", "default": True},
        }, {"symbol": "SH600000", "region": "cn", "type": "all", "count": 5, "is_detail": True})

for name, title in (("report", "机构评级与研报条目"), ("earningforecast", "盈利预测")):
    add(name, title, "雪球 · 研报", {"symbol": SYMBOL}, {"symbol": "SH600000"})
for name, title in (("capital_assort", "资金成交分布"), ("capital_flow", "日内资金流向")):
    add(name, title, "雪球 · 资金", {"symbol": SYMBOL}, {"symbol": "SH600000"})
add("capital_history", "历史资金流向", "雪球 · 资金", {"symbol": SYMBOL, "count": integer("数据条数", 20)}, {"symbol": "SH600000", "count": 20})
for name, title, size in (("margin", "融资融券", 180), ("blocktrans", "大宗交易", 30)):
    add(name, title, "雪球 · 资金", {"symbol": SYMBOL, "page": PAGE, "size": integer("每页条数", size)},
        {"symbol": "SH600000", "page": 1, "size": size})

for name, title in (("skholderchg", "股东持股变动"), ("skholder", "股东资料"), ("main_indicator", "公司主要指标"),
                    ("industry", "行业资料"), ("holders", "股东人数"), ("org_holding_change", "机构持股变动"),
                    ("industry_compare", "行业对比"), ("business_analysis", "经营分析")):
    add(name, title, "雪球 · 公司", {"symbol": SYMBOL}, {"symbol": "SH600000"})
add("bonus", "分红配股", "雪球 · 公司", {"symbol": SYMBOL, "page": PAGE, "size": integer("每页条数", 10)}, {"symbol": "SH600000", "page": 1, "size": 10})
add("shareschg", "股本变动（上游映射存疑）", "雪球 · 公司", {"symbol": SYMBOL, "count": integer("条数", 5)}, {"symbol": "SH600000", "count": 5},
    notes="固定版本将 shareschg 指向 business_analysis 路径，返回字段不应当作已验证股本变动；保留原样并提示。")
add("top_holders", "前十大股东", "雪球 · 公司", {"symbol": SYMBOL, "circula": dict(integer("上游 circula 标志", 1, 0, 1), enum=[0, 1])}, {"symbol": "SH600000", "circula": 1})

add("watch_list", "本人自选分组（私人数据）", "雪球 · 自选", {}, {}, sensitive=True)
add("watch_stock", "本人分组内自选股（私人数据）", "雪球 · 自选", {"id": integer("自选分组 ID", minimum=0, maximum=2147483647)}, {"id": 1}, sensitive=True)
for name, title in (("nav_daily", "组合历史净值"), ("rebalancing_current", "组合当前调仓记录"), ("quote_current", "组合当前行情")):
    add(name, title, "雪球 · 组合", {"symbol": CUBE}, {"symbol": "ZH000001"})
add("rebalancing_history", "组合历史调仓记录（只读，不执行调仓）", "雪球 · 组合",
    {"symbol": CUBE, "count": integer("每页条数", 20), "page": PAGE}, {"symbol": "ZH000001", "count": 20, "page": 1})

add("convertible_bond", "可转债列表", "东方财富 · 转债",
    {"page_size": integer("每页条数", maximum=100), "page_count": integer("实际上是 pageNumber 页码，不是自动抓取页数", maximum=100)},
    {"page_size": 20, "page_count": 1}, provider="eastmoney", auth=False)
for name, title in (("index_basic_info", "指数基本资料"), ("index_details_data", "指数详细资料"),
                    ("index_weight_top10", "指数十大权重"), ("index_perf_7", "指数近7日表现"),
                    ("index_perf_30", "指数近30日表现"), ("index_perf_90", "指数近90日表现")):
    add(name, title, "中证指数 · 指数", {"symbols": INDEX}, {"symbols": "000300"}, provider="csindex", auth=False)
for name, title in (("northbound_shareholding_sh", "沪股通持股查询"), ("northbound_shareholding_sz", "深股通持股查询")):
    params = {"txt_date": {"type": ["string", "null"], "description": "YYYY/MM/DD；null 使用当日", "default": None}}
    add(name, title, "港交所 · 持股", params, {"txt_date": None}, provider="hkex", auth=False,
        notes="只读查询；HTTPS 与动态表单校验。数据披露时效取决于上游，不等于实时北向净买入。")

for name, title in (("fund_detail", "基金详情"), ("fund_info", "基金基础信息"), ("fund_derived", "基金衍生指标"),
                    ("fund_asset", "基金资产配置"), ("fund_achievement", "基金业绩"), ("fund_trade_date", "基金交易日信息")):
    add(name, title, "蛋卷 · 基金", {"fund_code": FUND}, {"fund_code": "000001"}, provider="danjuan", auth=False)
add("fund_growth", "基金阶段涨幅", "蛋卷 · 基金", {"fund_code": FUND, "day": string("上游区间标志，例如 ty、1m、1y", r"^[a-z0-9]{1,12}$", "ty")}, {"fund_code": "000001", "day": "ty"}, provider="danjuan", auth=False)
add("fund_nav_history", "基金历史净值", "蛋卷 · 基金", {"fund_code": FUND, "page": PAGE, "size": integer("每页条数", 10)}, {"fund_code": "000001", "page": 1, "size": 10}, provider="danjuan", auth=False)
add("fund_manager", "基金经理", "蛋卷 · 基金", {"fund_code": FUND, "post_status": integer("上游任职状态标志", 1, 0, 10)}, {"fund_code": "000001", "post_status": 1}, provider="danjuan", auth=False)
add("suggest_stock", "证券名称或代码搜索", "雪球 · 搜索", {"keyword": string("搜索词，不接受 Token 或 Cookie", max_length=64)}, {"keyword": "浦发银行"})


def snowball_catalog():
    """返回中文功能说明、完整入参及示例；这组工具只有真实模式，不提供 mock 回退。"""
    result = []
    for spec in SPECS.values():
        value = deepcopy(spec)
        value.update(implementation="pysnowball · real", modes=["real"],
                     upstream_commit=UPSTREAM_COMMIT,
                     output_description="data 保留上游结构；同时返回来源、抓取时间、状态、缺失项和告警。抓取时间不代表数据时间。")
        result.append(value)
    return result
