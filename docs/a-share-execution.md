# A股买卖执行进度

## 当前实现

`trading.PaperAccount` 是内存模拟账户，与旧 `paper_order` 演示工具独立。支持：

- 主板股票限价委托及正整数股数、0.01元价格步长校验。
- 买入整手约束、现金冻结、可卖股数检查、卖出冻结。
- 委托 accepted、partially_filled、filled、cancelled 状态。
- 显式模拟成交，按成交价结算；受理不直接产生持仓。
- 当日买入不增加可卖数量；测试推进交易日后解锁。
- client_order_id 幂等、成交 ID 去重、部分成交后撤单。

运行 `python3 scripts/smoke_a_share_trading.py`，演示买入、当日卖出被阻止、下一交易日卖出。示例价格仅是测试输入。

未实现：真实券商连接、真实行情撮合、手续费与税费、涨跌幅与价格笼子、停牌与证券权限、交易时段和交易日历校验。`settle_to` 仅用于测试，调用方必须提供已核验的交易日。当前未接入网页或自动交易工作流，避免混同旧 mock 语义。

## 中信 Mac 持仓导入

已验证中信 Mac 导出的是二进制 XLS。使用 `trading.holdings_import.load_citic_holdings(path)` 读取，不修改源文件、不写入日志或数据库。

```bash
.venv/bin/python -m pip install -e '.[broker-import]'
.venv/bin/python scripts/import_citic_holdings.py '/本地路径/持仓.xls'
```

默认只显示条数。加 `--json` 才输出白名单持仓字段：原始证券代码、名称、持仓数量、可用股份、冻结数量、成本价、当前价和市值。账号、股东代码和托管单元不进入结果。金额为十进制字符串，保留前导零代码；同代码多行保留并提示，不混合不同账户记录。

表头隐藏 BOM、文本数字和千分位已处理；必需字段缺失或数量矛盾时报错，不补零。导入结果标记 `execution_ready=false`、`snapshot_at=null`，导入时间不能替代账户快照时间。证券市场和产品类型不通过名称猜测，也不直接导入旧模拟账户。当前仅 CLI/库函数可用，网页与客户端控件读取尚未接通。

## 实盘通道待确定

另有独立的[只读桌面研究原型](citic-desktop-research.md)：默认图像定位预览，显式确认后单次点击持仓或打开导出窗口，不触碰交易与保存确认。尚未完成实机标定，不是自动同步服务。

需要券商名称、交易 API 权限以及可运行的客户端环境，不需要在聊天中提供密码。若选用 miniQMT，按券商支持版本接入 XtQuant：

1. connect/subscribe 连接和订阅账户。
2. query_stock_asset / query_stock_positions 读取资金和可卖股数。
3. query_stock_orders / query_stock_trades 同步委托成交。
4. order_stock / cancel_order_stock 提交和撤单。
5. 根据真实订单及成交回报更新状态；网络超时后先查单，不能盲目重报。

交易账户和通道确定后再实现具体适配器；当前没有向任何实盘账户提交订单。

依据：[迅投交易 API](https://dict.thinktrader.net/nativeApi/xttrader.html)、[迅投权限常见问题](https://dict.thinktrader.net/nativeApi/question_function.html)、[上交所交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)。具体市场和板块规则需逐项接入，不能把主板模拟约束直接用于所有A股证券。
