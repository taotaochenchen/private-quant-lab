# 雪球网页采集器

## 实测情况与使用前提

本次只读检查中，`https://xueqiu.com/robots.txt` 返回 200，其中说明未经许可不得将雪球内容用于 AI 系统，包括 RAG。通配 robots 规则允许某个路径，并不等于授予本项目 AI 舆情用途许可。首页此次也返回 200，但内容是带 `aliyun_waf` 标记的访问验证页，并非真实帖子。

参考：[站点 robots 声明](https://xueqiu.com/robots.txt)、[声明中指向的用户协议](https://xueqiu.com/about/terms)。协议正文未在本次核验，以上仅说明实际读到的 robots 声明，不作法律结论。

因此默认只检查 robots，返回 `content_permission_required`，不请求帖子，不接入 Agent，也不使用 DeepSeek 模拟抓取结果。取得针对项目用途的许可后，操作者才可声明 `--permission-confirmed`；该参数不验证或授予许可，不解除 robots 禁止，也不绕过 WAF、登录或验证码。

## 运行

```bash
.venv/bin/python -m pip install -e '.[web-crawler]'
.venv/bin/python scripts/crawl_xueqiu.py
```

默认标准输出为 JSON，不写数据库或文件，不发送给模型。退出码 0 表示解析到帖子片段，1 表示访问或内容条件未满足，2 表示参数错误。

仅当确实已取得相应许可时：

```bash
.venv/bin/python scripts/crawl_xueqiu.py --permission-confirmed --limit 10
```

`--url` 仅接受 `https://xueqiu.com/` 或数字用户 ID / 数字帖子 ID 的帖子页路径。不接受凭据、查询参数、非公开 JSON 接口、私信、资产页、外域或自动重定向。采集器不加载浏览器 Cookie、不使用账号密码、不执行页面脚本，不点击或发布内容。

## 输出与能力边界

- 顶层：`status`、`source`、`url`、`fetched_at`、`is_mock=false`、`data_missing`、`posts`。
- 帖子：链接、可读文本、发布时间、修改时间、原始时间文本。
- 数量与时效缺失使用 null，不填 0。“修改于”不当作发布时间，相对时间不擅自转换。
- 暂未验证互动数 DOM，因此 reply_count / like_count / repost_count 为 null。
- 全部标记 `content_scope=html_excerpt`、`full_text_verified=false`、`evidence_ready=false`。获取片段不等于已获得可直接用于研究的完整证据。
- 支持标准 article、部分 timeline 结构和标准 Article JSON-LD。真实帖子页 DOM 尚未验证，不保证当前雪球页面选择器适配成功。
- 单次最多 50 条、响应最多 2 MiB、单条文本最多 10000 字符。正文请求前至少等待 2 秒，检查 Crawl-delay；不递归翻页、滚动加载、自动展开全文或重试限流响应。不要通过并行启动多个进程进行高频采集。

重要状态：`content_permission_required`、`robots_denied`、`robots_unavailable`、`access_challenge`、`login_required`、`access_denied`、`rate_limited`、`render_required`、`network_unavailable`。空页面或验证页不会作为成功舆情结果返回。

`parse_xueqiu_html` 可独立用于有权处理的 HTML。单元测试全部使用虚构文本，未保存真实雪球帖子或个人资料。当前没有抓取到真实帖子，不能宣称已接通雪球数据源。
