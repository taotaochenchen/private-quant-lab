"""A股研究指标目录；数值和发布时间均为联调样例，不是真实统计发布记录。"""


def point(value, unit, frequency="daily", period="2026-09-04", published_at="2026-09-04T18:00:00+08:00", methodology="fixture-v1"):
    return dict(value=value, unit=unit, frequency=frequency, observation_period=period,
                published_at=published_at, methodology=methodology, source="local_mock")


INDICATOR_CATALOG = {
    "get_capital_behavior": {
        "margin_balance_change_pct": point(0.4, "percent"),
        "etf_share_change_pct": point(0.2, "percent"),
        "dragon_tiger_net_buy_cny": point(120000000, "CNY"),
        "block_trade_premium_pct": point(-2.1, "percent"),
        # 不以成交总额冒充净流入；公开口径不可用时明确缺失。
        "northbound_net_buy_cny": point(None, "CNY", methodology="not_available_in_public_disclosure"),
    },
    "get_liquidity_environment": {
        "dr007": point(1.65, "percent"),
        "shibor_3m": point(1.8, "percent"),
        "repo_7d_policy_rate": point(1.5, "percent"),
        "cn_10y_yield": point(1.9, "percent"),
    },
    "get_derivatives_sentiment": {
        "etf300_volume_pcr": point(0.85, "ratio", methodology="put_volume/call_volume"),
        "etf300_oi_pcr": point(1.05, "ratio", methodology="put_open_interest/call_open_interest"),
        "etf300_iv_pct": point(21.0, "percent", methodology="mock_30d_constant_maturity"),
        "if_basis_pct": point(-0.3, "percent", methodology="100*(IF2609/CSI300-1)"),
    },
    "get_macro_snapshot": {
        name: point(value, unit, "monthly", "2026-08", "2026-09-01T09:30:00+08:00", methodology)
        for name, value, unit, methodology in (
            ("official_pmi", 50.2, "index", "official_manufacturing_fixture"),
            ("cpi_yoy", 0.5, "percent", "fixture-v1"),
            ("ppi_yoy", -1.5, "percent", "fixture-v1"),
            ("social_financing_yoy", 8.5, "percent", "stock_yoy_fixture"),
            ("m1_yoy", 4.0, "percent", "M1_2025_definition_fixture"),
            ("m2_yoy", 8.0, "percent", "fixture-v1"),
            ("industrial_profit_yoy", 2.0, "percent", "fixture-v1"),
        )
    },
}

# 兼容已有外围指标调用；它们不是国内宏观的必需指标。
INDICATOR_CATALOG["get_macro_snapshot"].update({
    "vix": point(18.5, "points"), "usd_cny": point(7.1, "CNY/USD"),
    "us_10y_yield": point(4.2, "percent"), "sp500_change_pct": point(0.5, "percent"),
})

# 必需指标按分析维度定义；衍生品作为补充信息，缺失不单独阻断。
REQUIRED_INDICATORS = {
    "get_capital_behavior": ("margin_balance_change_pct", "etf_share_change_pct"),
    "get_liquidity_environment": ("dr007", "cn_10y_yield"),
    "get_macro_snapshot": ("official_pmi", "social_financing_yoy", "m1_yoy", "m2_yoy"),
}
