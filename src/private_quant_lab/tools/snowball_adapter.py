"""pysnowball 查询适配：白名单分发、进程超时、服务端凭据和统一错误输出。"""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.cookies import SimpleCookie
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from private_quant_lab.models.config import PROJECT_ROOT, _read_dotenv
from .snowball_catalog import SPECS, UPSTREAM_COMMIT

_RUN_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0


class SnowballError(ValueError):
    """错误只携带状态码，禁止携带上游正文或凭据。"""


@dataclass
class SnowballSettings:
    timeout_seconds: float = 35
    content_permission_confirmed: bool = False
    _token: str = field(default="", repr=False)

    def set_token(self, token):
        """本地配置：xq_a_token 必填，u 可选；不回显、不改进程全局环境。"""
        if not isinstance(token, str) or len(token) > 8192 or any(ord(c) < 32 for c in token):
            raise SnowballError("invalid_token_configuration")
        cookie = SimpleCookie()
        try:
            cookie.load(token)
            if "xq_a_token" not in cookie:
                raise ValueError()
            values = {key: cookie[key].value for key in ("xq_a_token", "u") if key in cookie}
            if not all(re.fullmatch(r"[A-Za-z0-9_-]{1,2048}", value) for value in values.values()):
                raise ValueError()
            self._token = "; ".join(key + "=" + value for key, value in values.items())
        except Exception as exc:
            raise SnowballError("invalid_token_configuration") from exc

    def get_token(self):
        """仅供服务端请求层使用；不注册为网页接口或 Agent tool。"""
        return self._token


def load_snowball_settings(env_path=None, environ=None):
    values = {}
    path = Path(env_path) if env_path is not None else PROJECT_ROOT / ".env"
    if path.exists():
        values.update(_read_dotenv(path))
    values.update(os.environ if environ is None else environ)
    try:
        timeout = float(values.get("SNOWBALL_TIMEOUT_SECONDS", "35"))
        if not math.isfinite(timeout) or not 5 <= timeout <= 120:
            raise ValueError()
        permission = str(values.get("XUEQIU_CONTENT_PERMISSION_CONFIRMED", "false")).lower()
        if permission not in ("true", "false", "1", "0"):
            raise ValueError()
    except (ValueError, TypeError) as exc:
        raise SnowballError("invalid_snowball_configuration") from exc
    settings = SnowballSettings(timeout, permission in ("true", "1"))
    token = values.get("XUEQIUTOKEN", "")
    if token:
        settings.set_token(token)
    return settings


def validate_snowball_arguments(function, arguments):
    """依据完整签名做扁平参数校验并补默认值，阻止 URL/查询参数注入。"""
    if function not in SPECS or not isinstance(arguments, dict):
        raise ValueError("unknown snowball function or invalid arguments")
    schema = SPECS[function]["schema"]
    properties = schema["properties"]
    if set(arguments) - set(properties):
        raise ValueError("unexpected snowball arguments")
    values = deepcopy(arguments)
    for key, prop in properties.items():
        if key not in values:
            if "default" not in prop:
                raise ValueError(key + " is required")
            values[key] = prop["default"]
        value = values[key]
        kind = prop["type"]
        if value is None and isinstance(kind, list) and "null" in kind:
            continue
        kind = "string" if isinstance(kind, list) else kind
        valid = {"string": isinstance(value, str), "integer": type(value) is int,
                 "boolean": type(value) is bool}.get(kind, False)
        if not valid:
            raise ValueError(key + " has invalid type")
        if kind == "string":
            if not prop.get("minLength", 1) <= len(value) <= prop.get("maxLength", 64) or any(ord(c) < 32 for c in value):
                raise ValueError(key + " has invalid length or control characters")
            if "pattern" in prop and not re.fullmatch(prop["pattern"], value):
                raise ValueError(key + " has invalid format")
        if kind == "integer" and not prop["minimum"] <= value <= prop["maximum"]:
            raise ValueError(key + " out of range")
        if "enum" in prop and value not in prop["enum"]:
            raise ValueError(key + " unsupported value")
    if function == "quotec":
        symbols = values["symbols"].split(",")
        if not 1 <= len(symbols) <= 10 or len(set(symbols)) != len(symbols) or any(
                not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,23}", symbol) for symbol in symbols):
            raise ValueError("symbols requires 1 to 10 distinct securities")
    if "txt_date" in values and values["txt_date"] is not None:
        try:
            parsed = datetime.strptime(values["txt_date"], "%Y/%m/%d")
            if parsed.strftime("%Y/%m/%d") != values["txt_date"]:
                raise ValueError()
        except ValueError as exc:
            raise ValueError("txt_date must be YYYY/MM/DD") from exc
    return values


def _worker_call(function, arguments, settings):
    allowed_env = {"PATH", "HOME", "LANG", "TMPDIR", "SYSTEMROOT", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
                   "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"}
    env = {key: value for key, value in os.environ.items() if key in allowed_env}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    request = {"function": function, "arguments": arguments,
               "token": settings.get_token() if SPECS[function]["requires_token"] else ""}
    try:
        process = subprocess.run([sys.executable, "-m", "private_quant_lab.tools.snowball_worker"],
                                 input=json.dumps(request), capture_output=True, text=True,
                                 timeout=settings.timeout_seconds, env=env)
    except subprocess.TimeoutExpired as exc:
        raise SnowballError("timeout") from exc
    except OSError as exc:
        raise SnowballError("worker_unavailable") from exc
    if process.returncode or len(process.stdout) > 5 * 1024 * 1024:
        raise SnowballError("worker_failed")
    try:
        value = json.loads(process.stdout)
        if not isinstance(value, dict) or value.get("status") not in WORKER_STATUSES:
            raise ValueError()
        return value
    except ValueError as exc:
        raise SnowballError("invalid_worker_response") from exc


WORKER_STATUSES = {"ok", "empty", "missing_dependency", "unsupported_sdk", "timeout", "network_error",
                   "auth_or_access_denied", "rate_limited", "http_error", "redirect_blocked", "response_too_large",
                   "invalid_json", "upstream_error", "unexpected_response", "endpoint_not_allowed",
                   "form_changed", "sdk_error", "access_challenge", "worker_failed"}


def _redact(value, token):
    secrets = [token] if token else []
    if token:
        cookie = SimpleCookie(token)
        secrets.extend(m.value for m in cookie.values())
    def visit(item):
        if isinstance(item, dict):
            return {visit(str(key)): "[REDACTED]" if any(word in str(key).lower() for word in
                    ("token", "cookie", "authorization", "password")) else visit(child) for key, child in item.items()}
        if isinstance(item, list):
            return [visit(child) for child in item]
        if isinstance(item, str):
            for secret in secrets:
                if secret:
                    item = item.replace(secret, "[REDACTED]")
        return item
    return visit(value)


def run_snowball_tool(name, arguments, settings=None, runner=None):
    global _LAST_REQUEST_AT
    function = name.removeprefix("snowball_") if isinstance(name, str) else ""
    values = validate_snowball_arguments(function, arguments)
    spec = SPECS[function]
    result = {"source": spec["provider"] + ":pysnowball:" + function, "function": function,
              "mock": False, "is_mock": False, "fetched_at": datetime.now(timezone.utc).isoformat(),
              "source_timestamp": None, "point_in_time_verified": False, "upstream_commit": UPSTREAM_COMMIT,
              "schema_verified": False,
              "data": None, "data_missing": True, "missing_fields": ["data"], "warnings": [
                  "保留上游字段与数据时间；抓取时间不是行情或报告发布时间。",
                  "第三方接口可用性、数据许可及披露口径需单独核验，不用于自动交易。"], "errors": {}}
    if spec["notes"]:
        result["warnings"].append(spec["notes"])
    if spec["sensitive"]:
        result["warnings"].append("返回本人自选信息，仅在当前工具测试中显示，不发送给 Agent。")
    try:
        settings = settings or load_snowball_settings()
        if spec["provider"] in ("xueqiu", "danjuan") and not settings.content_permission_confirmed:
            raise SnowballError("content_permission_required")
        if spec["requires_token"] and not settings.get_token():
            raise SnowballError("token_required")
        if not _RUN_LOCK.acquire(blocking=False):
            raise SnowballError("busy")
        try:
            if runner is None:
                time.sleep(max(0, 2 - (time.monotonic() - _LAST_REQUEST_AT)))
                _LAST_REQUEST_AT = time.monotonic()
            output = (runner or _worker_call)(function, values, settings)
        finally:
            _RUN_LOCK.release()
        if output.get("status") not in WORKER_STATUSES:
            raise SnowballError("invalid_worker_response")
        result["status"] = output["status"]
        if output["status"] == "ok":
            if not isinstance(output.get("data"), (dict, list)):
                raise SnowballError("invalid_worker_response")
            result["data"] = _redact(output.get("data"), settings.get_token())
            result["data_missing"] = False
            result["missing_fields"] = []
            if function == "shareschg":
                result.update(status="upstream_mapping_unverified", data_missing=True,
                              missing_fields=["verified_endpoint_mapping"],
                              errors={"upstream": "固定版本将股本变动映射到了经营分析，不能确认返回语义。"})
        else:
            result["errors"] = {"upstream": output["status"]}
    except SnowballError as exc:
        result["status"] = str(exc)
        result["errors"] = {"adapter": str(exc)}
    return result
