from contextlib import redirect_stderr
from io import StringIO
import importlib.util
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.tools.snowball_adapter import (
    SnowballError, SnowballSettings, _RUN_LOCK, _worker_call, load_snowball_settings,
    run_snowball_tool, validate_snowball_arguments,
)
from private_quant_lab.tools.snowball_catalog import SPECS, snowball_catalog
from private_quant_lab.tools.snowball_worker import SafeTransport, invoke_sdk
from private_quant_lab.web.server import run_tool_request

TOKEN = "xq_a_token=TEST_SECRET_TOKEN; u=1234567890123"
HKEX_HTML = b'''<table id="mutualmarket-result"><tbody><tr>
<td class="col-stock-code"><div class="mobile-list-body">70001</div></td>
<td class="col-stock-name"><div class="mobile-list-body">SYNTHETIC</div></td>
<td class="col-shareholding"><div class="mobile-list-body">1,000</div></td>
<td class="col-shareholding-percent"><div class="mobile-list-body">0.01%</div></td>
</tr></tbody></table>'''


def settings():
    result = SnowballSettings(content_permission_confirmed=True)
    result.set_token(TOKEN)
    return result


class StubTransport:
    last_error = None

    def __init__(self):
        self.calls = []

    def json(self, url, authenticated=False):
        self.calls.append((url, authenticated))
        return {"error_code": 0, "data": [{"fixture": True, "number": 12.5}]}

    def hkex(self, url, txt_date):
        self.calls.append((url, False))
        return HKEX_HTML


class SnowballAdapterTests(unittest.TestCase):
    def test_full_catalog_and_defaults(self):
        self.assertEqual(len(SPECS), 56)
        self.assertEqual(len({item["name"] for item in snowball_catalog()}), 56)
        for name, spec in SPECS.items():
            with self.subTest(name=name):
                value = validate_snowball_arguments(name, spec["example"])
                self.assertEqual(set(value), set(spec["schema"]["properties"]))
        self.assertNotIn("get_token", SPECS)
        self.assertNotIn("set_token", SPECS)

    def test_invalid_types_limits_and_injection(self):
        bad = [("kline", {"symbol": "SH600000", "count": True}),
               ("kline", {"symbol": "SH600000", "count": 1001}),
               ("quotec", {"symbols": "SH600000,SH600000"}),
               ("quotec", {"symbols": "SH600000,,SZ000001"}),
               ("pankou", {"symbol": "SH600000&secret=1"}),
               ("watch_list", {"token": "DO_NOT_ECHO"}),
               ("cash_flow_v2", {"symbol": "AAPL", "region": "invalid"}),
               ("northbound_shareholding_sh", {"txt_date": "2026/02/30"}),
               ("northbound_shareholding_sh", {"txt_date": "2026/9/1"}),
               ("suggest_stock", {"keyword": "a\nb"}), ("get_token", {})]
        for name, args in bad:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_snowball_arguments(name, args)

    def test_token_methods_are_local_and_not_echoed(self):
        config = SnowballSettings()
        self.assertIsNone(config.set_token(TOKEN))
        self.assertEqual(config.get_token(), TOKEN)
        self.assertNotIn("TEST_SECRET", repr(config))
        for value in ("u=123", "xq_a_token=", "xq_a_token=valid; u=", "xq_a_token=bad\r\nCookie: injection;u=123", 123):
            with self.assertRaises(SnowballError):
                config.set_token(value)

    def test_token_without_user_id_is_loaded_and_redacted(self):
        token = "xq_a_token=TEST_TOKEN_ONLY"
        with tempfile.TemporaryDirectory() as directory:
            config = load_snowball_settings(Path(directory) / "missing.env", {
                "XUEQIUTOKEN": token, "XUEQIU_CONTENT_PERMISSION_CONFIRMED": "true"})
        self.assertEqual(config.get_token(), token)
        self.assertNotIn("TEST_TOKEN_ONLY", repr(config))
        output = run_snowball_tool("pankou", {"symbol": "SH600000"}, config,
                                   lambda *args: {"status": "ok", "data": {"message": "TEST_TOKEN_ONLY"}})
        self.assertEqual(output["status"], "ok")
        self.assertNotIn("TEST_TOKEN_ONLY", json.dumps(output))
        config.set_token(token + "; other_cookie=ignored")
        self.assertEqual(config.get_token(), token)

    def test_configuration_does_not_require_model_key(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_snowball_settings(Path(directory) / "missing.env", {
                "XUEQIUTOKEN": TOKEN, "SNOWBALL_TIMEOUT_SECONDS": "40", "XUEQIU_CONTENT_PERMISSION_CONFIRMED": "true"})
            self.assertEqual(config.timeout_seconds, 40)
            self.assertTrue(config.content_permission_confirmed)
            for timeout in ("NaN", "inf", "0", "121", "oops"):
                with self.assertRaises(SnowballError):
                    load_snowball_settings(Path(directory) / "missing.env", {"SNOWBALL_TIMEOUT_SECONDS": timeout})

    def test_permission_and_token_gates_do_not_start_worker(self):
        def fail(*args):
            self.fail("worker should not run")
        result = run_snowball_tool("quotec", {"symbols": "SH600000"}, settings=SnowballSettings(), runner=fail)
        self.assertEqual(result["status"], "content_permission_required")
        result = run_snowball_tool("pankou", {"symbol": "SH600000"},
                                   settings=SnowballSettings(content_permission_confirmed=True), runner=fail)
        self.assertEqual(result["status"], "token_required")
        self.assertTrue(result["data_missing"])

    def test_credentials_are_redacted_in_values_keys_and_nested_fields(self):
        def runner(*args):
            return {"status": "ok", "data": {"token": TOKEN, "nested": [{"message": "TEST_SECRET_TOKEN"}],
                                              "TEST_SECRET_TOKEN": "1234567890123", "number": 12.5}}
        output = run_snowball_tool("quotec", {"symbols": "SH600000"}, settings(), runner)
        self.assertNotIn("TEST_SECRET_TOKEN", json.dumps(output))
        self.assertNotIn("1234567890123", json.dumps(output))
        self.assertEqual(output["data"]["number"], 12.5)

    def test_error_empty_and_mapping_results_do_not_fall_back(self):
        for status in ("empty", "rate_limited", "auth_or_access_denied", "timeout", "missing_dependency"):
            output = run_snowball_tool("quotec", {"symbols": "SH600000"}, settings(),
                                       lambda *args: {"status": status})
            self.assertEqual(output["status"], status)
            self.assertIsNone(output["data"])
            self.assertFalse(output["mock"])
        output = run_snowball_tool("shareschg", {"symbol": "SH600000"}, settings(),
                                   lambda *args: {"status": "ok", "data": {"business": "not shares"}})
        self.assertEqual(output["status"], "upstream_mapping_unverified")
        self.assertTrue(output["data_missing"])

    def test_single_worker_and_timeout_boundary(self):
        with _RUN_LOCK:
            output = run_snowball_tool("quotec", {"symbols": "SH600000"}, settings(), lambda *args: self.fail())
        self.assertEqual(output["status"], "busy")
        with patch("private_quant_lab.tools.snowball_adapter.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 1)):
            with self.assertRaisesRegex(SnowballError, "timeout"):
                _worker_call("quotec", {"symbols": "SH600000"}, settings())

    def test_subprocess_secrets_use_stdin_and_errors_are_sanitized(self):
        with patch("private_quant_lab.tools.snowball_adapter.subprocess.run", return_value=SimpleNamespace(
                returncode=0, stdout='{"status":"ok","data":[]}', stderr="PRIVATE_ERROR")) as process:
            _worker_call("pankou", {"symbol": "SH600000"}, settings())
        call = process.call_args
        self.assertNotIn("TEST_SECRET", str(call.args))
        self.assertNotIn("TEST_SECRET", str(call.kwargs["env"]))
        self.assertIn("TEST_SECRET", call.kwargs["input"])
        self.assertEqual(call.kwargs["timeout"], 35)
        with patch("private_quant_lab.tools.snowball_adapter.subprocess.run", return_value=SimpleNamespace(
                returncode=1, stdout=TOKEN, stderr=TOKEN)):
            with self.assertRaisesRegex(SnowballError, "^worker_failed$"):
                _worker_call("pankou", {"symbol": "SH600000"}, settings())

    def test_web_real_mode_only_and_no_model(self):
        with patch("private_quant_lab.web.server._build_models_from_payload", side_effect=AssertionError("model")), \
                patch("private_quant_lab.tools.snowball_adapter.load_snowball_settings", return_value=SnowballSettings()):
            response = run_tool_request({"name": "snowball_quotec", "arguments": {"symbols": "SH600000"}, "mode": "real"})
            self.assertEqual(response["result"]["status"], "content_permission_required")
            for mode in ("local", "llm"):
                with self.assertRaises(ValueError):
                    run_tool_request({"name": "snowball_quotec", "arguments": {"symbols": "SH600000"}, "mode": mode})
            with self.assertRaises(ValueError):
                run_tool_request({"name": "snowball_get_token", "arguments": {}, "mode": "real"})


@unittest.skipUnless(importlib.util.find_spec("pysnowball"), "install snowball extra for actual SDK contract tests")
class SDKCoverageTests(unittest.TestCase):
    def test_every_public_data_function_and_signature_is_covered(self):
        import pysnowball as sdk
        exported = {name for name, fn in inspect.getmembers(sdk, inspect.isfunction)
                    if fn.__module__.startswith("pysnowball") and name not in ("get_token", "set_token")}
        self.assertEqual(set(SPECS), exported)
        for name, spec in SPECS.items():
            with self.subTest(function=name):
                signature = inspect.signature(getattr(sdk, name))
                self.assertEqual(set(signature.parameters), set(spec["schema"]["properties"]))
                for key, parameter in signature.parameters.items():
                    prop = spec["schema"]["properties"][key]
                    if parameter.default is not inspect.Parameter.empty:
                        self.assertEqual(prop["default"], parameter.default)

    def test_all_56_real_sdk_functions_with_stubbed_network(self):
        from pysnowball import utls
        original = utls.fetch
        for name, spec in SPECS.items():
            with self.subTest(function=name), patch("requests.sessions.Session.request", side_effect=AssertionError("live network")):
                transport = StubTransport()
                output = run_snowball_tool(spec["name"], spec["example"], settings(),
                    runner=lambda fn, args, cfg: invoke_sdk(fn, args, transport))
                self.assertEqual(output["status"], "upstream_mapping_unverified" if name == "shareschg" else "ok")
                self.assertEqual(len(transport.calls), 1)
                self.assertIs(utls.fetch, original)

    def test_search_keyword_cannot_inject_query_parameters(self):
        transport = StubTransport()
        invoke_sdk("suggest_stock", {"keyword": "行业 & token=synthetic"}, transport)
        query = parse_qs(urlsplit(transport.calls[0][0]).query)
        self.assertEqual(query, {"q": ["行业 & token=synthetic"]})

    def test_hkex_swallowed_errors_remain_visible(self):
        transport = StubTransport()
        def fail(*args):
            raise SnowballError("form_changed")
        transport.hkex = fail
        with redirect_stderr(StringIO()), self.assertRaisesRegex(SnowballError, "form_changed"):
            invoke_sdk("northbound_shareholding_sh", {"txt_date": None}, transport)


class FakeResponse:
    def __init__(self, data=b'{"data":[1],"error_code":0}', status=200):
        self.data, self.status_code = data, status
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def iter_content(self, size):
        yield self.data


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


class SafeTransportTests(unittest.TestCase):
    def test_auth_is_scoped_and_tls_timeout_redirects_enforced(self):
        session = FakeSession([FakeResponse(), FakeResponse()])
        transport = SafeTransport(TOKEN, session=session, sleep=lambda _: None)
        transport.json("https://stock.xueqiu.com/test", authenticated=True)
        transport.json("https://www.csindex.com.cn/test")
        first = session.calls[0][2]
        self.assertTrue(first["verify"])
        self.assertFalse(first["allow_redirects"])
        self.assertEqual(first["timeout"], (5, 15))
        self.assertEqual(first["headers"]["Cookie"], TOKEN)
        self.assertNotIn("Cookie", session.calls[1][2]["headers"])
        with self.assertRaises(SnowballError):
            transport.json("https://www.csindex.com.cn/test", authenticated=True)

    def test_http_and_json_failures(self):
        for response, expected in ((FakeResponse(status=403), "auth_or_access_denied"),
                (FakeResponse(status=429), "rate_limited"), (FakeResponse(status=302), "redirect_blocked"),
                (FakeResponse(status=500), "http_error"), (FakeResponse(b"<html>blocked</html>"), "invalid_json"),
                (FakeResponse(b"<meta name=aliyun_waf>"), "access_challenge"),
                (FakeResponse(b'{"error_code":123,"message":"private"}'), "upstream_error"),
                (FakeResponse(b'{"success":false}'), "upstream_error"),
                (FakeResponse(b'{"code":400}'), "upstream_error"),
                (FakeResponse(b'{"data":NaN}'), "invalid_json"), (FakeResponse(b"null"), "unexpected_response")):
            with self.subTest(status=expected), self.assertRaisesRegex(SnowballError, "^" + expected + "$"):
                SafeTransport(session=FakeSession([response])).json("https://xueqiu.com/test")

    def test_endpoint_allowlist_and_size_limit(self):
        transport = SafeTransport(session=FakeSession([FakeResponse(b"x" * (4 * 1024 * 1024 + 1))]))
        for url in ("https://localhost/", "http://xueqiu.com/", "https://xueqiu.com.evil.test/",
                    "https://token@xueqiu.com/", "https://xueqiu.com:444/"):
            with self.assertRaisesRegex(SnowballError, "endpoint_not_allowed"):
                transport.json(url)
        with self.assertRaisesRegex(SnowballError, "response_too_large"):
            transport.json("https://xueqiu.com/test")

    def test_hkex_fetches_fresh_form_and_uses_https(self):
        form = b'<input type="hidden" name="__VIEWSTATE" value="NEW_STATE"><input type="hidden" name="__EVENTVALIDATION" value="NEW_VALIDATION">'
        session = FakeSession([FakeResponse(form), FakeResponse(HKEX_HTML)])
        transport = SafeTransport(session=session, sleep=lambda _: None)
        self.assertEqual(transport.hkex("http://www.hkexnews.hk/sdw/search/mutualmarket.aspx?t=sh", "2026/09/11"), HKEX_HTML)
        self.assertEqual([call[0] for call in session.calls], ["GET", "POST"])
        self.assertTrue(all(call[1].startswith("https:") for call in session.calls))
        fields = session.calls[1][2]["data"]
        self.assertEqual(fields["__VIEWSTATE"], "NEW_STATE")
        self.assertEqual(fields["txtShareholdingDate"], "2026/09/11")
        with self.assertRaisesRegex(SnowballError, "form_changed"):
            SafeTransport(session=FakeSession([FakeResponse(b"no form")])).hkex("https://www.hkexnews.hk/test")


if __name__ == "__main__":
    unittest.main()
