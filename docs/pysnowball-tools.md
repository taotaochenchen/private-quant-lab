# pysnowball 全接口适配

## 范围与版本

已覆盖上游根模块公开导出的 **56 个数据查询函数**，工具名统一为 `snowball_函数名`。与原有 mock 环境分离，只出现在 `/tools` 测试目录，不自动加入 Agent 权限或每日建议工作流。没有下单、修改自选、执行调仓或资金划转操作。

复用 SDK 的 URL 构建和字段解析，不另写一套 56 个接口的客户端。依赖固定到 [e85fe550c5daed4ad1429d1f4e048dab239df921](https://github.com/uname-yang/pysnowball/tree/e85fe550c5daed4ad1429d1f4e048dab239df921)，避免 PyPI 版本号相同而代码不同。接口列表和签名经安装后的真实 SDK 逐项核对。

这不是雪球官方 SDK，也不是热门帖子/评论采集库。上游还包含东方财富、中证指数、港交所和蛋卷数据。来源在返回值中分别标记。

## 完整清单

| 类别 | 接口 |
| --- | --- |
| 行情（4） | `quotec`、`pankou`、`quote_detail`、`kline` |
| 财务（9） | `cash_flow`、`indicator`、`balance`、`income`、`business`、`cash_flow_v2`、`indicator_v2`、`balance_v2`、`income_v2` |
| 研报（2） | `report`、`earningforecast` |
| 资金（5） | `margin`、`blocktrans`、`capital_assort`、`capital_flow`、`capital_history` |
| 公司（11） | `skholderchg`、`skholder`、`main_indicator`、`industry`、`holders`、`bonus`、`org_holding_change`、`industry_compare`、`business_analysis`、`shareschg`、`top_holders` |
| 自选（2） | `watch_list`、`watch_stock` |
| 组合（4） | `nav_daily`、`rebalancing_history`、`rebalancing_current`、`quote_current` |
| 可转债（1） | `convertible_bond` |
| 中证指数（6） | `index_basic_info`、`index_details_data`、`index_weight_top10`、`index_perf_7`、`index_perf_30`、`index_perf_90` |
| 沪深股通持股（2） | `northbound_shareholding_sh`、`northbound_shareholding_sz` |
| 基金（9） | `fund_detail`、`fund_info`、`fund_growth`、`fund_nav_history`、`fund_derived`、`fund_asset`、`fund_manager`、`fund_achievement`、`fund_trade_date` |
| 证券搜索（1） | `suggest_stock` |

每个接口的完整参数、默认值、边界和可修改示例见 `snowball_catalog.py` 或网页 Schema。兼容上游参数名，例如 `quotec` 使用 `symbols`，`watch_stock` 使用 `id`。代码不自动转换市场或证券类型。

另两个凭据函数对应本地 `SnowballSettings.set_token/get_token`：set 不回显、不写磁盘或全局环境；get 只供服务端请求层使用。它们不属于数据查询工具，不开放 HTTP/Agent 入口，不会通过网页返回 Cookie。

## 配置与测试

```bash
.venv/bin/python -m pip install -e '.[snowball]'
.venv/bin/python scripts/smoke_snowball.py --list
.venv/bin/python scripts/smoke_snowball.py --check-config
```

本地 `.env` 或进程环境可配置以下变量，环境变量优先：

```dotenv
XUEQIUTOKEN=
SNOWBALL_TIMEOUT_SECONDS=35
XUEQIU_CONTENT_PERMISSION_CONFIRMED=false
```

`XUEQIUTOKEN` 最小配置为 `"xq_a_token=你的token"`，`xq_a_token` 必填，`u`（用户 ID）可省略；也兼容 `"xq_a_token=你的token; u=你的用户ID"`。仅保留这两个字段。不把真实值写进代码、命令行参数、工具 Arguments、测试样例或聊天。内容使用许可与登录凭据是两回事；许可项只有在确认获得适用于自己用途的许可后才能设为 true，不代表系统替用户获得了许可。

需要 Token 的雪球查询在缺失时返回 `token_required`。上游 `quotec` 本身不带 Token，但仍受数据使用许可及站点访问规则限制。蛋卷查询不附带雪球 Cookie。非雪球来源不会接收到雪球 Cookie。

单独调用一个接口：

```bash
.venv/bin/python scripts/smoke_snowball.py --function quotec --arguments '{"symbols":"SH600000,SZ000001"}'
.venv/bin/python scripts/smoke_snowball.py --function capital_history --arguments '{"symbol":"SH600000","count":20}'
.venv/bin/python scripts/smoke_snowball.py --function index_basic_info --arguments '{"symbols":"000300"}'
```

或在 `/tools` 搜索 `snowball_`，选择接口后执行“真实数据”。这组接口禁用本地 mock 和 DeepSeek observation，不需要模型 Key，不调用模型。自选接口返回私人信息，仅在当前浏览器工具测试记录里展示；刷新或清空记录后不保留，手动下载除外。

## 返回结果

统一返回 `status`、`source`、`function`、`fetched_at`、`data`、`data_missing`、`missing_fields`、`errors` 和 `warnings`。

- `data` 保留上游响应结构，不生成分数，不用 mock 补数据。
- `fetched_at` 是获取时间，不是行情日期或发布时间。顶层 `source_timestamp=null`，原始数据时间仍在 `data` 中。
- `schema_verified=false`、`point_in_time_verified=false`：仅保证调用/JSON/常见上游错误检查，未建立每个接口的字段级质量契约或历史时点保证。
- 已知 Token、Cookie 等敏感值会脱敏；数值不会因格式统一而重算。
- 页面请求失败不记录完整 HTTP 头、错误正文或 Cookie。父子进程通过 stdin 传递必要凭据，不通过命令行参数传递；不继承模型 API Key。

典型失败：`content_permission_required`、`token_required`、`auth_or_access_denied`、`rate_limited`、`timeout`、`network_error`、`redirect_blocked`、`access_challenge`、`invalid_json`、`upstream_error`、`form_changed`、`empty`、`missing_dependency`。

## 请求隔离与已知限制

- 服务进程同时最多运行一个 SDK 查询，其他请求返回 `busy`；同一进程发起间隔至少 2 秒。不是跨进程分布式限流，不应批量启动脚本绕过频率限制。
- 单次 worker 默认 35 秒总超时，可设 5~120 秒；HTTP 连接/读取超时为 5/15 秒。超时终止子进程，不让线程继续悬挂。
- 请求仅允许固定来源域名，关闭自动跳转，保留证书校验；不实现登录、验证码处理、代理轮换或反爬绕过。服务使用明确的研究客户端 User-Agent，没有照搬上游手机 App 身份。
- 上游 `northbound_shareholding_*` 使用 HTTP 地址、硬编码表单状态并关闭证书校验。适配器改用 HTTPS、读取当前隐藏表单字段再发起只读查询。遇到页面变更报错，不关闭 TLS 校验；是否仍公开提供指定日期数据需实测。
- 上游 `shareschg` 的路径实际指向 `business_analysis`。接口可调用并保留返回供排查，但返回 `upstream_mapping_unverified`、`data_missing=true`，不作为已验证股本变动数据。未猜测另一个接口地址。
- `convertible_bond.page_count` 实际映射页码，而非抓取页数；不自动翻页。
- 组合调仓接口只是读取组合记录，绝不会据此复制或执行交易。
- 当前 Python 运行时产生了 urllib3 的 LibreSSL 兼容性警告，未关闭证书验证或全局屏蔽警告。上线前应使用受该依赖支持的 TLS/Python 运行时。

## 验证

测试逐项比对 56 个实际 SDK 函数的签名、默认值和本地目录，并用拦截的网络响应逐个执行真实函数；另覆盖凭据脱敏、参数注入、错误/空响应、超时、并发、域名限制、动态港交所表单及网页真实模式分发。这些是离线契约测试，不是 56 个真实数据源已连通的证明。

目前未配置用户雪球 Token 或内容许可声明，因此没有批量请求用户数据。后续真实联调应逐个来源、逐个接口进行，不直接运行全量抓取。

本次已真实调用一次 `index_basic_info(symbols="000300")`，返回 `status=ok` 和中证指数 JSON。该结果只证明此接口此次可访问，不代表其余 55 个接口均已真实联通。
