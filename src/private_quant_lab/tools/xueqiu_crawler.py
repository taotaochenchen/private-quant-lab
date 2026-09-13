"""雪球只读采集：先检查访问规则，再解析 HTML；不处理登录、Cookie 或 WAF 挑战。"""

from datetime import datetime, timezone
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser


USER_AGENT = "PrivateQuantResearch/0.1"
MAX_BYTES = 2 * 1024 * 1024
POST_PATH = re.compile(r"/\d+/\d+/?$")


class CrawlError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def validate_url(url, robots=False):
    """限制为雪球首页/帖子页，不访问用户资产、私信或任意外部 URL。"""
    if not isinstance(url, str) or len(url) > 2000 or any(ord(c) < 33 for c in url):
        raise CrawlError("invalid_url")
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname == "xueqiu.com"
                 and parsed.port in (None, 443) and not parsed.username and not parsed.password
                 and not parsed.query)
    except ValueError as exc:
        raise CrawlError("invalid_url") from exc
    path = parsed.path or "/"
    if not valid or not (path == "/" or POST_PATH.fullmatch(path) or (robots and path == "/robots.txt")):
        raise CrawlError("url_not_allowed")
    return urlunsplit(("https", "xueqiu.com", path, "", ""))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 登录跳转和外域跳转不能被当作一次成功的内容抓取。
        raise CrawlError("redirect_requires_review")


def fetch_text(url, timeout=12):
    """只读单次 GET，不重试、不保存 Cookie；输出状态、内容类型和受限大小正文。"""
    validate_url(url, robots=True)
    request = Request(url, headers={"User-Agent": USER_AGENT,
                                   "Accept": "text/html,text/plain;q=0.9",
                                   "Accept-Encoding": "identity"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise CrawlError("response_too_large")
            if response.headers.get("Content-Encoding", "identity").lower() not in ("identity", ""):
                raise CrawlError("unsupported_content_encoding")
            charset = response.headers.get_content_charset() or "utf-8"
            try:
                text = body.decode(charset)
            except (LookupError, UnicodeDecodeError) as exc:
                raise CrawlError("invalid_text_encoding") from exc
            return response.status, response.headers.get_content_type(), text
    except HTTPError as exc:
        # 不输出响应正文、请求凭据或代理地址。
        return exc.code, "", ""
    except (URLError, TimeoutError, OSError) as exc:
        raise CrawlError("network_unavailable") from exc


def _text(element):
    return " ".join(element.stripped_strings) if element else ""


def _post_url(value, base):
    try:
        url = validate_url(urljoin(base, value))
    except (CrawlError, TypeError):
        return None
    return url if POST_PATH.fullmatch(urlsplit(url).path) else None


def parse_xueqiu_html(html, source_url="https://xueqiu.com/", limit=20):
    """输入有权处理的 HTML；输出帖子片段，不猜测缺失时间、互动数或隐藏全文。

    仅支持服务端 HTML 中的 article/timeline 容器及标准 Article JSON-LD。
    选择器尚未通过当前真实帖子页验证；没有帖子时返回 render_required，不返回假空列表成功。
    """
    source_url = validate_url(source_url)
    if not isinstance(html, str) or len(html.encode("utf-8")) > MAX_BYTES:
        raise CrawlError("invalid_html_or_too_large")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise CrawlError("limit_out_of_range")
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise CrawlError("install_web_crawler_extra") from exc
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one('meta[name^="aliyun_waf"], #challenge-form, iframe[src*="captcha"]'):
        return {"status": "access_challenge", "page_title": "", "posts": []}
    if soup.select_one('input[type="password"]') and not soup.select_one('article, .timeline__item'):
        return {"status": "login_required", "page_title": "", "posts": []}
    title = _text(soup.title)[:300]
    posts, seen = [], set()

    def append(url, body, published=None, modified=None, time_text=None):
        if not url or not body or url in seen or len(posts) >= limit:
            return
        seen.add(url)
        posts.append({"url": url, "text": body[:10000], "published_at": published,
                      "modified_at": modified, "time_text": time_text,
                      "content_scope": "html_excerpt", "full_text_verified": False,
                      "evidence_ready": False,
                      "text_clipped": len(body) > 10000,
                      "reply_count": None, "like_count": None, "repost_count": None})

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            entries = node.get("@graph", [node])
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("@type") not in ("Article", "NewsArticle", "SocialMediaPosting"):
                    continue
                raw_body = entry.get("articleBody")
                if not isinstance(raw_body, str):
                    continue
                append(_post_url(entry.get("url") or source_url, source_url),
                       _text(BeautifulSoup(raw_body, "html.parser")),
                       _absolute_time(entry.get("datePublished")), _absolute_time(entry.get("dateModified")))

    for node in soup.select('article, .timeline__item, [data-status-id]'):
        url = next((url for a in node.select('a[href]')
                    if (url := _post_url(a.get("href"), source_url))), None)
        if url is None and POST_PATH.fullmatch(urlsplit(source_url).path):
            url = source_url
        content = node.select_one('.timeline__content, [itemprop="articleBody"], .article__bd')
        if content is None:
            paragraphs = node.select("p")
            body = "\n".join(_text(p) for p in paragraphs)
        else:
            for element in content.select('script, style, form, input, button, iframe'):
                element.decompose()
            body = _text(content)
        when = node.select_one("time")
        time_text = _text(when) or None
        timestamp = _absolute_time(when.get("datetime")) if when else None
        edited = bool(time_text and "修改" in time_text)
        append(url, body, published=None if edited else timestamp,
               modified=timestamp if edited else None, time_text=time_text)
    return {"status": "ok" if posts else "render_required", "page_title": title, "posts": posts}


def _absolute_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.isoformat() if parsed.tzinfo else None


def crawl_xueqiu(url="https://xueqiu.com/", limit=20, permission_confirmed=False,
                  fetch=fetch_text, sleep=time.sleep):
    """检查 robots 和内容许可后采集一页。不递归、不滚动、不调用非公开 JSON 接口。

    permission_confirmed 仅表示操作者已取得相应许可的声明，并不验证或授予许可；
    该参数不解除 robots 禁止，也不解除登录或 WAF 验证。未授权时仅检查 robots。
    """
    url = validate_url(url)
    if type(limit) is not int or not 1 <= limit <= 50 or type(permission_confirmed) is not bool:
        raise CrawlError("invalid_arguments")
    result = {"source": "xueqiu", "url": url, "is_mock": False, "data_missing": True,
              "fetched_at": datetime.now(timezone.utc).isoformat(), "posts": [],
              "content_permission": "operator_declared" if permission_confirmed else "not_confirmed",
              "policy_url": "https://xueqiu.com/robots.txt"}

    def finish(status):
        result["status"] = status
        return result

    try:
        status, content_type, robots = fetch(result["policy_url"])
        if status != 200 or content_type not in ("text/plain", "text/x-robots-txt"):
            return finish("robots_unavailable")
        rules = RobotFileParser()
        rules.parse(robots.splitlines())
        if not rules.can_fetch(USER_AGENT, url):
            return finish("robots_denied")
        # 本项目用途是 AI 舆情研究，站点许可单独检查，不拿通配 robots 允许当内容授权。
        if not permission_confirmed:
            return finish("content_permission_required")
        delay = rules.crawl_delay(USER_AGENT) or 2
        if delay > 30:
            return finish("crawl_delay_requires_scheduling")
        sleep(max(2, delay))
        status, content_type, html = fetch(url)
        result["http_status"] = status
        if status in (401, 403, 429):
            return finish({401: "login_required", 403: "access_denied", 429: "rate_limited"}[status])
        if status != 200:
            return finish("http_error")
        if content_type not in ("text/html", "application/xhtml+xml"):
            return finish("unexpected_content_type")
        parsed = parse_xueqiu_html(html, url, limit)
        result.update(parsed)
        result["data_missing"] = parsed["status"] != "ok"
        return result
    except CrawlError as exc:
        return finish(exc.code)
