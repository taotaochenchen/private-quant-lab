# 中信 Mac 只读桌面研究

当前暂停推进此路线，优先使用[每日建议与人工执行](daily-strategy-revision.md)。以下保留为独立研究原型，不接入建议工作流。

## 范围

独立于 Computer Use 服务，使用 PyAutoGUI 截图和坐标点击。当前仅支持主显示器、有人值守的单步研究；不是无人值守同步服务。默认只预览，不移动鼠标。

允许两种转换：`holdings_tab -> holdings_view`（打开持仓），`export_button -> export_dialog`（打开导出窗口）。导出前必须同时识别持仓页参考图。保存对话框由用户操作，随后复用现有 XLS 导入器核对文件。

没有买卖、撤单、资金划转、键盘输入、自动登录、保存确认或覆盖文件的实现。不要把交易按钮标定成只读按钮。名称白名单不是语义识别或安全隔离：模板标错、同样式按钮、窗口遮挡和截图到点击之间的竞态仍可能造成误点，必须人工核对。真实客户端只用于只读测试；交易交互实验使用模拟界面。

## 安装与权限

```bash
.venv/bin/python -m pip install -e '.[desktop-research,broker-import]'
.venv/bin/python scripts/citic_desktop_research.py --help
```

macOS 可能要求运行 Python 的终端获得屏幕录制和辅助功能权限，由用户在系统设置中明确授权。脚本不修改系统权限。先在非敏感窗口检查截图权限；黑屏、空白或错误时停止，不将其解释为成功。

PyAutoGUI 的 FAILSAFE 保持开启：将鼠标移到主屏角落可在下一次检查时中断；终端 Ctrl+C 也可取消。不要在执行时移动窗口或使用鼠标。无法保证对已发生的一次点击回滚。

## 首次标定

固定窗口位置、主显示器、缩放、主题。鼠标坐标为逻辑坐标，脚本将 Retina 截图归一化，拒绝不一致的缩放。多显示器未验证。

使用 `capture 名称 --region X Y W H` 保存小区域模板，默认等待 5 秒供你切换到客户端。以下只是命令格式，不是可直接套用的坐标：

先运行 `.venv/bin/python scripts/citic_desktop_research.py position`，在倒计时内将鼠标移到裁剪区域左上角，得到 X/Y；再对右下角执行一次，坐标差为 W/H。该命令仅读取鼠标位置，不截图、不点击。捕获模板时把鼠标移出按钮，避免悬停样式进入模板。

```text
.venv/bin/python scripts/citic_desktop_research.py capture holdings_tab --region X Y W H
.venv/bin/python scripts/citic_desktop_research.py capture holdings_view --region X Y W H
.venv/bin/python scripts/citic_desktop_research.py capture export_button --region X Y W H
.venv/bin/python scripts/citic_desktop_research.py capture export_dialog --region X Y W H
```

四张模板需你手动切换到对应状态分别截取：

| 名称 | 截取对象 |
| --- | --- |
| holdings_tab | 未选中的“持仓”标签，只包含该标签 |
| holdings_view | 持仓页特有的静态表头组合，不含任何账户数据行 |
| export_button | 持仓页上的“导出”按钮，只包含该按钮 |
| export_dialog | 导出保存对话框的静态标题与标签区域，不含动态文件名 |

裁剪区域至少 8x8，按钮模板中心必须落在按钮内部。不要保存账号、姓名、余额、持仓明细。完整截图仅在内存用于裁剪和匹配；磁盘仅保存小区域 PNG 与坐标 JSON，不上传、不记日志。默认目录 `.local/desktop-research/` 已加入 gitignore，但 gitignore 不是隐私隔离，模板仍须人工检查。已有模板不覆盖，重新标定用全局 `--directory 新目录`。

## 预览和单步执行

```bash
.venv/bin/python scripts/citic_desktop_research.py step holdings_tab
.venv/bin/python scripts/citic_desktop_research.py step export_button
```

预览输出步骤名、坐标和 `status=preview`，不代表已完成操作。客户端目标区域必须无遮挡；终端可放在另一侧。

```bash
.venv/bin/python scripts/citic_desktop_research.py step holdings_tab --execute
.venv/bin/python scripts/citic_desktop_research.py step export_button --execute
```

每次只执行一条命令。输入对应步骤名确认后，5 秒内切回客户端并移开鼠标。再次匹配必须与预览坐标相同，然后只点击一次。后置参考图唯一匹配才返回 `status=verified`；已经处于目标状态则不点击。找不到、多处匹配、分辨率变化或 5 秒内未确认结果都报错，不重试点击。

实现使用彩色精确匹配，只在标定位置周围 24 个逻辑像素搜索；抗锯齿、悬停效果、主题变化都可能使匹配失败，此时应重新核对/标定，不能退化成无检查的坐标点击。保存窗口出现只代表窗口验证通过，不代表文件已导出。

你手动保存后核对：

```bash
.venv/bin/python scripts/import_citic_holdings.py '/实际导出路径/持仓.xls'
```

## 验证状态

单元测试使用虚构参考图和假桌面，覆盖零/多匹配、页面守卫、确认后坐标变化、单次点击及超时不重试，不访问真实客户端。当前未完成 Mac 实机标定和端到端导出，不应视为可无人值守运行。

已在本机虚拟环境安装依赖，并在受限环境外验证 `position --delay 0` 可读取鼠标位置和主屏尺寸。受限执行环境内曾异常退出；这不能证明截图/点击权限已获得，也不能证明是券商客户端故障。尚未在真实客户端截图标定或点击。不要自动授予权限或关闭系统保护来绕过失败。

参考：[PyAutoGUI 截图与坐标定位文档](https://pyautogui.readthedocs.io/en/latest/screenshot.html)。
