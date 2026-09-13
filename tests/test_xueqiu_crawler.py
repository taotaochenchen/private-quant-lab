from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.tools.xueqiu_crawler import (
    CrawlError, NoRedirect, crawl_xueqiu, parse_xueqiu_html, validate_url,
)


# 全部为虚构内容，不包含真实用户标识、Cookie 或雪球原文。
HTML = '''<html><head><title>研究测试页</title></head><body>
<aside>PRIVATE_ACCOUNT</aside><main>
<article><a href="/100/200">帖子</a><p>测试行业的观点，尚待核实。</p>
<time datetime="2026-09-13T08:00:00+08:00">1小时前</time></article>
<article><a href="/100/200">重复帖子</a><p>重复内容</p></article>
<article><a href="/101/201">另一帖子</a><p>另一项测试观点。</p>
<time datetime="2026-09-13T09:00:00+08:00">修改于刚刚</time></article>
</main></body></html>'''
ROBOTS = "User-agent: *\nAllow: /\n"


class XueqiuCrawlerTests(unittest.TestCase):
    def fake_fetch(self, page=(200, "text/html", HTML), robots=(200, "text/plain", ROBOTS)):
        self.requests = []
        def fetch(url):
            self.requests.append(url)
            return robots if url.endswith("robots.txt") else page
        return fetch

    def test_permission_gate_only_fetches_policy(self):
        result = crawl_xueqiu(fetch=self.fake_fetch())
        self.assertEqual(result["status"], "content_permission_required")
        self.assertEqual(self.requests, ["https://xueqiu.com/robots.txt"])
        self.assertFalse(result["is_mock"])
        self.assertTrue(result["data_missing"])

    def test_robots_denial_cannot_be_overridden_by_permission(self):
        result = crawl_xueqiu(permission_confirmed=True, fetch=self.fake_fetch(
            robots=(200, "text/plain", "User-agent: *\nDisallow: /")))
        self.assertEqual(result["status"], "robots_denied")
        self.assertEqual(len(self.requests), 1)

    def test_robots_failure_does_not_fetch_content(self):
        for response in ((404, "text/plain", ""), (200, "text/html", "<html>challenge</html>")):
            result = crawl_xueqiu(permission_confirmed=True, fetch=self.fake_fetch(robots=response))
            self.assertEqual(result["status"], "robots_unavailable")
            self.assertEqual(len(self.requests), 1)

    def test_successful_response_and_delay(self):
        waits = []
        result = crawl_xueqiu(permission_confirmed=True, fetch=self.fake_fetch(), sleep=waits.append)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["data_missing"])
        self.assertEqual(waits, [2])
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(len(result["posts"]), 2)

    def test_waf_with_http_200_is_not_a_post(self):
        response = (200, "text/html", '<meta name="aliyun_waf_aa"><script>challenge()</script>')
        result = crawl_xueqiu(permission_confirmed=True, fetch=self.fake_fetch(page=response), sleep=lambda _: None)
        self.assertEqual(result["status"], "access_challenge")
        self.assertEqual(result["posts"], [])
        self.assertTrue(result["data_missing"])

    def test_http_errors_and_unexpected_types(self):
        for code, content_type, expected in ((401, "text/html", "login_required"),
                (403, "text/html", "access_denied"), (429, "text/html", "rate_limited"),
                (500, "text/html", "http_error"), (200, "application/json", "unexpected_content_type")):
            result = crawl_xueqiu(permission_confirmed=True,
                                  fetch=self.fake_fetch(page=(code, content_type, "")), sleep=lambda _: None)
            self.assertEqual(result["status"], expected)
            self.assertEqual(len(self.requests), 2)

    def test_network_error_is_sanitized(self):
        def fail(url):
            raise CrawlError("network_unavailable")
        self.assertEqual(crawl_xueqiu(fetch=fail)["status"], "network_unavailable")

    def test_url_scope_and_redirects(self):
        self.assertEqual(validate_url("https://xueqiu.com/100/200#reply"), "https://xueqiu.com/100/200")
        for url in ("http://xueqiu.com/", "https://xueqiu.com.evil.test/", "https://127.0.0.1/",
                    "https://user:pass@xueqiu.com/", "https://xueqiu.com:444/", "https://xueqiu.com/messages",
                    "https://xueqiu.com/?token=private", "https://xueqiu.com/statuses.json",
                    "https://xueqiu.com/\n", "https://[bad/"):
            with self.subTest(url=url), self.assertRaises(CrawlError):
                validate_url(url)
        with self.assertRaises(CrawlError):
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.org")

    def test_parse_dedup_timestamps_and_privacy(self):
        result = parse_xueqiu_html(HTML)
        first, second = result["posts"]
        self.assertEqual(first["published_at"], "2026-09-13T08:00:00+08:00")
        self.assertIsNone(second["published_at"])
        self.assertEqual(second["modified_at"], "2026-09-13T09:00:00+08:00")
        self.assertIsNone(first["like_count"])
        self.assertFalse(first["full_text_verified"])
        self.assertNotIn("PRIVATE_ACCOUNT", str(result))

    def test_relative_time_is_not_guessed(self):
        result = parse_xueqiu_html('<article><a href="/100/200">帖子</a><p>观点</p><time>5小时前</time></article>')
        self.assertIsNone(result["posts"][0]["published_at"])
        self.assertEqual(result["posts"][0]["time_text"], "5小时前")

    def test_empty_render_shell_and_login(self):
        self.assertEqual(parse_xueqiu_html('<main id="app"></main>')["status"], "render_required")
        self.assertEqual(parse_xueqiu_html('<form><input type="password"></form>')["status"], "login_required")

    def test_limit_and_non_post_links(self):
        self.assertEqual(len(parse_xueqiu_html(HTML, limit=1)["posts"]), 1)
        self.assertEqual(parse_xueqiu_html('<article><a href="/100">作者</a><p>观点</p></article>')["posts"], [])
        for limit in (0, 51, True):
            with self.assertRaises(CrawlError):
                parse_xueqiu_html(HTML, limit=limit)

    def test_json_ld_and_long_text(self):
        import json
        html = '<script type="application/ld+json">' + json.dumps({"@graph": [{
            "@type": "Article", "url": "https://xueqiu.com/100/200", "articleBody": "字" * 10001,
            "datePublished": "2026-09-13T08:00:00+08:00"}]}) + '</script>'
        post = parse_xueqiu_html(html)["posts"][0]
        self.assertEqual(len(post["text"]), 10000)
        self.assertTrue(post["text_clipped"])

    def test_large_crawl_delay_requires_scheduler(self):
        result = crawl_xueqiu(permission_confirmed=True, fetch=self.fake_fetch(
            robots=(200, "text/plain", ROBOTS + "Crawl-delay: 60\n")))
        self.assertEqual(result["status"], "crawl_delay_requires_scheduling")
        self.assertEqual(len(self.requests), 1)


if __name__ == "__main__":
    unittest.main()
