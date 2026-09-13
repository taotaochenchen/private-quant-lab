"""隔离运行上游 SDK；仅替换其请求帮助函数，不修改全局 requests 或主服务凭据。"""

from datetime import datetime
import json
import os
import sys
import time
from urllib.parse import quote, urlsplit, urlunsplit
from contextlib import redirect_stdout, redirect_stderr

from .snowball_adapter import SnowballError, validate_snowball_arguments

MAX_RESPONSE = 4 * 1024 * 1024
HOSTS = {"stock.xueqiu.com", "xueqiu.com", "datacenter-web.eastmoney.com",
         "www.csindex.com.cn", "www.hkexnews.hk", "danjuanapp.com"}


class SafeTransport:
    def __init__(self, token="", session=None, sleep=time.sleep):
        if session is None:
            import requests
            session = requests.Session()
        self.session, self.token, self.sleep = session, token, sleep
        self.last_request = None
        self.last_error = None

    def request(self, url, method="GET", data=None, authenticated=False):
        parsed = urlsplit(url)
        if parsed.scheme == "http" and parsed.hostname == "www.hkexnews.hk":
            url = urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))
            parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise SnowballError("endpoint_not_allowed")
        if authenticated and parsed.hostname not in ("xueqiu.com", "stock.xueqiu.com"):
            raise SnowballError("endpoint_not_allowed")
        if self.last_request is not None:
            self.sleep(max(0, 2 - (time.monotonic() - self.last_request)))
        headers = {"User-Agent": "PrivateQuantResearch/0.1", "Accept": "application/json,text/html;q=0.8"}
        if authenticated:
            if not self.token:
                raise SnowballError("auth_or_access_denied")
            headers["Cookie"] = self.token
        self.last_request = time.monotonic()
        try:
            with self.session.request(method, url, headers=headers, data=data, timeout=(5, 15),
                                      verify=True, allow_redirects=False, stream=True) as response:
                code = response.status_code
                if code in (401, 403):
                    raise SnowballError("auth_or_access_denied")
                if code == 429:
                    raise SnowballError("rate_limited")
                if 300 <= code < 400:
                    raise SnowballError("redirect_blocked")
                if code != 200:
                    raise SnowballError("http_error")
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_RESPONSE:
                        raise SnowballError("response_too_large")
                    chunks.append(chunk)
                body = b"".join(chunks)
                if b"aliyun_waf" in body or b'id="challenge-form"' in body:
                    raise SnowballError("access_challenge")
                return body
        except SnowballError as exc:
            self.last_error = exc
            raise
        except Exception as exc:
            status = "timeout" if "timeout" in type(exc).__name__.lower() else "network_error"
            self.last_error = SnowballError(status)
            raise self.last_error from exc

    def json(self, url, authenticated=False):
        body = self.request(url, authenticated=authenticated)
        try:
            value = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeDecodeError) as exc:
            raise SnowballError("invalid_json") from exc
        if not isinstance(value, (dict, list)):
            raise SnowballError("unexpected_response")
        if isinstance(value, dict):
            if "error_code" in value and value["error_code"] not in (0, "0", None):
                raise SnowballError("upstream_error")
            if value.get("success") is False:
                raise SnowballError("upstream_error")
            if "code" in value and value["code"] not in (0, "0", 200, "200", None):
                raise SnowballError("upstream_error")
        return value

    def hkex(self, url, txt_date=None):
        """HTTPS 获取当前 ASP.NET 隐藏字段，再提交只读持股查询，不复用上游硬编码状态。"""
        from bs4 import BeautifulSoup
        page = BeautifulSoup(self.request(url), "html.parser")
        fields = {element["name"]: element.get("value", "") for element in page.select('input[type="hidden"][name]')}
        if not fields.get("__VIEWSTATE") or not fields.get("__EVENTVALIDATION"):
            raise SnowballError("form_changed")
        today = datetime.now()
        fields.update(today=today.strftime("%Y%m%d"), sortBy="stockcode", sortDirection="asc",
                      alertMsg="", txtShareholdingDate=txt_date or today.strftime("%Y/%m/%d"), btnSearch="Search")
        return self.request(url, method="POST", data=fields)


def invoke_sdk(function, arguments, transport, sdk=None):
    """使用上游的 URL 构建及字段解析，依赖版本固定；不暴露任意 getattr 入口。"""
    values = validate_snowball_arguments(function, arguments)
    if sdk is None:
        import pysnowball as sdk
    from pysnowball import utls
    if not callable(getattr(sdk, function, None)):
        raise SnowballError("unsupported_sdk")
    def hkex(url, txt_date=None):
        try:
            return transport.hkex(url, txt_date)
        except SnowballError as exc:
            transport.last_error = exc
            raise

    hooks = {
        "fetch": lambda url, host=None: transport.json(url, authenticated=True),
        "fetch_without_token": lambda url, host=None: transport.json(url),
        "fetch_eastmoney": lambda url: transport.json(url),
        "fetch_csindex": lambda url: transport.json(url),
        "fetch_danjuan_fund": lambda url: transport.json(url),
        "fetch_hkc": hkex,
    }
    previous = {name: getattr(utls, name) for name in hooks}
    try:
        for name, handler in hooks.items():
            setattr(utls, name, handler)
        if function == "suggest_stock":
            values["keyword"] = quote(values["keyword"], safe="")
        data = getattr(sdk, function)(**values)
        if transport.last_error is not None:
            raise transport.last_error
        if data is None:
            raise SnowballError("unexpected_response")
        if not isinstance(data, (dict, list)):
            raise SnowballError("unexpected_response")
        empty = not data or (isinstance(data, dict) and "data" in data and data["data"] in (None, [], {}))
        return {"status": "empty" if empty else "ok", "data": data}
    finally:
        for name, handler in previous.items():
            setattr(utls, name, handler)


def main():
    try:
        payload = json.loads(sys.stdin.read(32768))
        with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            result = invoke_sdk(payload["function"], payload["arguments"], SafeTransport(payload.get("token", "")))
        serialized = json.dumps(result, ensure_ascii=False, allow_nan=False)
        if len(serialized.encode("utf-8")) > MAX_RESPONSE:
            raise SnowballError("response_too_large")
    except ImportError:
        serialized = json.dumps({"status": "missing_dependency"})
    except SnowballError as exc:
        serialized = json.dumps({"status": str(exc)})
    except Exception:
        serialized = json.dumps({"status": "sdk_error"})
    print(serialized)


if __name__ == "__main__":
    main()
