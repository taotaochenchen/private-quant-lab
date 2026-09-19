"""Local web UI for testing the ReAct agent loop."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from time import perf_counter
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from private_quant_lab.agents import DEFAULT_SYSTEM_PROMPT, ReActAgent, ReActAgentError
from private_quant_lab.domain import empty_pre_market_report, get_trading_calendar, pre_market_report_schema
from private_quant_lab.models import ModelConfigError, ModelError, build_chat_model, load_model_config
from private_quant_lab.tools import build_mock_quant_environment, common_quant_tool_names
from private_quant_lab.web.logging import LoggingChatModel, RequestLogStore
from private_quant_lab.web.tool_testing import tool_catalog, validate_arguments, snowball_config_status
from private_quant_lab.tools.real_market import real_market_snapshot
from private_quant_lab.workflows import (
    DEFAULT_AUTO_TRADING_TASK,
    DEFAULT_PRE_MARKET_TASK,
    AutoTradingWorkflow,
    PreMarketWorkflow,
    auto_trading_schema,
    build_empty_auto_trading_run,
    build_pre_market_system_prompt,
    pre_market_agent_prompts,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_THINKING_MODEL = "deepseek-reasoner"
DEFAULT_TASK = "先用 web_search 查 NVDA AI demand，再用 technical_indicators 看 NVDA 技术面，最后输出 Final。"
REQUEST_LOGS = RequestLogStore()


def create_server(host="127.0.0.1", port=8765):
    """Create the local ReAct test server."""

    return ThreadingHTTPServer((host, port), ReActWebHandler)


class ReActWebHandler(BaseHTTPRequestHandler):
    server_version = "PrivateQuantReActWeb/0.1"

    def do_GET(self):
        path = urlparse(self.path).path
        tool_assets = {"/tools": ("tools.html", "text/html"), "/tools.css": ("tools.css", "text/css"),
                       "/tools.js": ("tools.js", "application/javascript")}
        if path in tool_assets:
            filename, content_type = tool_assets[path]
            self._send_static(filename, content_type + "; charset=utf-8")
            return
        if path == "/api/tool_catalog":
            self._send_json({"tools": tool_catalog()})
            return
        if path == "/api/tools/snowball_config":
            self._send_json(snowball_config_status())
            return
        if path == "/":
            self._send_static("index.html", "text/html; charset=utf-8")
            return
        if path == "/app.css":
            self._send_static("app.css", "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._send_static("app.js", "application/javascript; charset=utf-8")
            return
        if path == "/api/tools":
            environment = build_mock_quant_environment()
            self._send_json(
                {
                    "tools": common_quant_tool_names(),
                    "tool_schemas": environment.openai_tools(),
                    "default_task": DEFAULT_TASK,
                    "default_system_prompt": DEFAULT_SYSTEM_PROMPT,
                    "default_pre_market_task": DEFAULT_PRE_MARKET_TASK,
                    "default_auto_trading_task": DEFAULT_AUTO_TRADING_TASK,
                    "default_pre_market_system_prompt": build_pre_market_system_prompt(),
                    "pre_market_agent_prompts": pre_market_agent_prompts(),
                }
            )
            return
        if path == "/api/schemas/pre_market":
            self._send_json(
                {
                    "schema": pre_market_report_schema(),
                    "empty_report": empty_pre_market_report().to_dict(),
                }
            )
            return
        if path == "/api/schemas/auto_trading":
            self._send_json(
                {
                    "schema": auto_trading_schema(),
                    "empty_run": build_empty_auto_trading_run(),
                }
            )
            return
        if path == "/api/logs":
            query = urlparse(self.path).query
            filters = _parse_query(query)
            logs = REQUEST_LOGS.list(
                run_id=filters.get("run_id"),
                limit=int(filters.get("limit") or 100),
            )
            self._send_json({"logs": logs})
            return
        if path == "/api/calendar":
            self._send_json(calendar_snapshot())
            return
        self._send_json({"error": "not found"}, status=404)

    def do_HEAD(self):
        path = urlparse(self.path).path
        tool_assets = {"/tools": ("tools.html", "text/html"), "/tools.css": ("tools.css", "text/css"),
                       "/tools.js": ("tools.js", "application/javascript")}
        if path in tool_assets:
            filename, content_type = tool_assets[path]
            self._send_static_head(filename, content_type + "; charset=utf-8")
            return
        if path == "/":
            self._send_static_head("index.html", "text/html; charset=utf-8")
            return
        if path == "/app.css":
            self._send_static_head("app.css", "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._send_static_head("app.js", "application/javascript; charset=utf-8")
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/tools/execute":
            run_id = str(uuid4())
            started = perf_counter()
            try:
                result = run_tool_request(self._read_json(), run_id=run_id, log_store=REQUEST_LOGS)
                status = 200
            except ValueError as exc:
                result, status = {"ok": False, "error": str(exc)}, 400
            except Exception as exc:
                result, status = {"ok": False, "error": str(exc)}, 500
            result.update(run_id=run_id, elapsed_ms=round((perf_counter() - started) * 1000, 2))
            self._send_json(result, status=status)
            return
        if path == "/api/logs/clear":
            REQUEST_LOGS.clear()
            self._send_json({"ok": True})
            return

        if path == "/api/run_stream":
            self._handle_run_stream()
            return

        if path == "/api/pre_market_stream":
            self._handle_pre_market_stream()
            return

        if path == "/api/auto_trade_stream":
            self._handle_auto_trade_stream()
            return

        if path != "/api/run":
            self._send_json({"error": "not found"}, status=404)
            return

        run_id = str(uuid4())
        try:
            payload = self._read_json()
            result = run_react_request(payload, run_id=run_id, log_store=REQUEST_LOGS)
        except ValueError as exc:
            self._send_json({"ok": False, "run_id": run_id, "error": str(exc)}, status=400)
            return
        except (ModelConfigError, ModelError, ReActAgentError) as exc:
            body = {"ok": False, "run_id": run_id, "error": str(exc)}
            if isinstance(exc, ReActAgentError) and exc.trace:
                body["trace"] = exc.trace
            self._send_json(body, status=200)
            return

        self._send_json(
            {
                "ok": True,
                "run_id": run_id,
                "final": result.final,
                "trace": result.trace,
            }
        )

    def _handle_run_stream(self):
        run_id = str(uuid4())
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json({"ok": False, "run_id": run_id, "error": str(exc)}, status=400)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def emit(event, data):
            data = dict(data)
            data.setdefault("run_id", run_id)
            self._send_sse(event, data)

        emit("run_created", {"run_id": run_id})
        try:
            result = run_react_request(
                payload,
                run_id=run_id,
                log_store=REQUEST_LOGS,
                on_event=emit,
            )
        except (ModelConfigError, ModelError, ReActAgentError, ValueError) as exc:
            body = {"ok": False, "run_id": run_id, "error": str(exc)}
            if isinstance(exc, ReActAgentError) and exc.trace:
                body["trace"] = exc.trace
            emit("run_error", body)
            return

        emit(
            "run_finished",
            {
                "ok": True,
                "run_id": run_id,
                "final": result.final,
                "trace": result.trace,
            },
        )

    def _handle_pre_market_stream(self):
        run_id = str(uuid4())
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json({"ok": False, "run_id": run_id, "error": str(exc)}, status=400)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def emit(event, data):
            data = dict(data)
            data.setdefault("run_id", run_id)
            self._send_sse(event, data)

        emit("run_created", {"run_id": run_id, "workflow": "pre_market"})
        try:
            result = run_pre_market_request(
                payload,
                run_id=run_id,
                log_store=REQUEST_LOGS,
                on_event=emit,
            )
        except (ModelConfigError, ModelError, ReActAgentError, ValueError) as exc:
            body = {"ok": False, "run_id": run_id, "error": str(exc)}
            if isinstance(exc, ReActAgentError) and exc.trace:
                body["trace"] = exc.trace
            emit("run_error", body)
            return

        emit(
            "run_finished",
            {
                "ok": True,
                "run_id": run_id,
                "workflow": "pre_market",
                "final": result.final,
                "report": result.report,
                "trace": result.trace,
            },
        )

    def _handle_auto_trade_stream(self):
        run_id = str(uuid4())
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json({"ok": False, "run_id": run_id, "error": str(exc)}, status=400)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def emit(event, data):
            data = dict(data)
            data.setdefault("run_id", run_id)
            self._send_sse(event, data)

        emit("run_created", {"run_id": run_id, "workflow": "auto_trade"})
        try:
            result = run_auto_trade_request(
                payload,
                run_id=run_id,
                log_store=REQUEST_LOGS,
                on_event=emit,
            )
        except (ModelConfigError, ModelError, ReActAgentError, ValueError) as exc:
            body = {"ok": False, "run_id": run_id, "error": str(exc)}
            if isinstance(exc, ReActAgentError) and exc.trace:
                body["trace"] = exc.trace
            emit("run_error", body)
            return

        emit(
            "run_finished",
            {
                "ok": True,
                "run_id": run_id,
                "workflow": "auto_trade",
                "final": result.final,
                "report": result.report,
                "auto_trade": result.run,
                "trace": result.trace,
            },
        )

    def log_message(self, format, *args):
        return

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def _send_static(self, filename, content_type):
        path = STATIC_DIR / filename
        if not path.exists():
            self._send_json({"error": "static file not found"}, status=404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static_head(self, filename, content_type):
        path = STATIC_DIR / filename
        if not path.exists():
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()

    def _send_json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_sse(self, event, value):
        payload = json.dumps(value, ensure_ascii=False)
        body = "event: {0}\ndata: {1}\n\n".format(event, payload).encode("utf-8")
        self.wfile.write(body)
        self.wfile.flush()


def run_tool_request(payload, run_id=None, log_store=None):
    """直接执行单工具；先校验参数，再按需创建 observation 模型。"""
    if not isinstance(payload, dict):
        raise ValueError("request must be an object")
    name = payload.get("name")
    catalog = {item["name"]: item for item in tool_catalog()}
    if not isinstance(name, str) or name not in catalog:
        raise ValueError("unknown tool")
    mode = payload.get("mode", "local")
    if mode not in ("local", "llm", "real"):
        raise ValueError("unsupported execution mode")
    arguments = payload.get("arguments")
    if name.startswith("snowball_"):
        if mode != "real":
            raise ValueError("pysnowball tools only support real mode")
        from private_quant_lab.tools.snowball_adapter import run_snowball_tool
        output = run_snowball_tool(name, arguments)
        return {"ok": output["status"] == "ok", "name": name, "arguments": arguments,
                "mode": mode, "result": output,
                "error": None if output["status"] == "ok" else "pysnowball: " + output["status"]}
    validate_arguments(arguments, catalog[name]["schema"])
    if mode == "real":
        if name != "get_market_snapshot":
            raise ValueError("real data not implemented for this tool")
        output = real_market_snapshot(arguments)
        return {"ok": not bool(output["missing_fields"]), "name": name, "arguments": arguments,
                "mode": mode, "result": output,
                "error": "部分或全部真实数据缺失，请查看 errors。" if output["missing_fields"] else None}
    observation_model = None
    if mode == "llm" and name != "compute_market_regime_metrics":
        _, observation_model = _build_models_from_payload(
            {"model": payload.get("model") or DEFAULT_MODEL, "llm_observation": True}, run_id, log_store)
    output = build_mock_quant_environment(observation_model=observation_model).run(name, arguments).output
    return {"ok": True, "name": name, "arguments": arguments, "mode": mode, "result": output}


def run_react_request(payload, run_id=None, log_store=None, on_event=None):
    """Run one ReAct request from web JSON payload."""

    if run_id is None:
        run_id = str(uuid4())
    task = str(payload.get("task") or DEFAULT_TASK).strip()
    if not task:
        raise ValueError("task must not be empty")
    max_steps = int(payload.get("max_steps") or 4)
    max_tokens = int(payload.get("max_tokens") or 900)
    model, observation_model = _build_models_from_payload(payload, run_id, log_store)
    environment = build_mock_quant_environment(observation_model=observation_model)
    agent = ReActAgent(model, environment, max_steps=max_steps)
    return agent.run(
        task,
        max_tokens=max_tokens,
        model_extra_body=_model_extra_body(payload),
        system_prompt=payload.get("system_prompt") or DEFAULT_SYSTEM_PROMPT,
        on_event=on_event,
    )


def calendar_snapshot():
    """返回今日交易日历事实供前端自动填充 T-1，并如实标注是否经校验。"""
    from datetime import date

    today = date.today()
    calendar = get_trading_calendar()
    snapshot = {
        "trade_date": today.isoformat(),
        "is_trading_day": calendar.is_trading_day(today),
        "calendar_verified": calendar.verified,
        "calendar_source": calendar.source,
    }
    for key, method in (("prev_trading_day", calendar.previous_trading_day),
                        ("next_trading_day", calendar.next_trading_day)):
        try:
            snapshot[key] = method(today).isoformat()
        except (ValueError, TypeError):
            snapshot[key] = None
    return snapshot


def run_pre_market_request(payload, run_id=None, log_store=None, on_event=None):
    """Run one pre-market workflow request from web JSON payload."""

    model, observation_model = _build_models_from_payload(payload, run_id, log_store)
    environment = build_mock_quant_environment(observation_model=observation_model)
    max_steps = int(payload.get("max_steps") or 8)
    max_tokens = int(payload.get("max_tokens") or 1200)
    workflow = PreMarketWorkflow(model, environment, max_steps=max_steps)
    extra_body = _model_extra_body(payload)
    extra_body.setdefault("response_format", {"type": "json_object"})
    task_context = payload.get("task_context") if "task_context" in payload else payload.get("task")
    return workflow.run(
        task=str(task_context or DEFAULT_PRE_MARKET_TASK).strip(),
        max_tokens=max_tokens,
        model_extra_body=extra_body,
        system_prompt=payload.get("system_prompt") or None,
        agent_system_prompts=_agent_system_prompts_from_payload(payload),
        on_event=on_event,
        manual_advice=True,
        previous_report=payload.get("previous_report"),
        previous_trade_date=payload.get("previous_trade_date"),
        execution_feedback=payload.get("execution_feedback", ""),
        calendar=get_trading_calendar(),
    )


def run_auto_trade_request(payload, run_id=None, log_store=None, on_event=None):
    """Run one autonomous paper-trading request from web JSON payload."""

    model, observation_model = _build_models_from_payload(payload, run_id, log_store)
    environment = build_mock_quant_environment(observation_model=observation_model)
    max_steps = int(payload.get("max_steps") or 8)
    max_tokens = int(payload.get("max_tokens") or 3000)
    workflow = AutoTradingWorkflow(model, environment, max_steps=max_steps)
    extra_body = _model_extra_body(payload)
    extra_body.setdefault("response_format", {"type": "json_object"})
    task_context = payload.get("task_context") if "task_context" in payload else payload.get("task")
    account_state = payload.get("account_state") or {}
    if not isinstance(account_state, dict):
        raise ValueError("account_state must be a JSON object")
    market_data = payload.get("market_data") or {}
    if not isinstance(market_data, dict):
        raise ValueError("market_data must be a JSON object")
    return workflow.run(
        task=str(task_context or DEFAULT_AUTO_TRADING_TASK).strip(),
        account_state=account_state,
        max_tokens=max_tokens,
        model_extra_body=extra_body,
        system_prompt=payload.get("system_prompt") or None,
        agent_system_prompts=_agent_system_prompts_from_payload(payload),
        on_event=on_event,
        market_data=market_data,
    )


def _build_models_from_payload(payload, run_id=None, log_store=None):
    model_name = str(payload.get("model") or DEFAULT_MODEL).strip()
    thinking_mode = bool(payload.get("thinking_mode", False))
    if thinking_mode and model_name == DEFAULT_MODEL:
        model_name = DEFAULT_THINKING_MODEL
    use_llm_observation = bool(payload.get("llm_observation", True))

    requested_base_url = payload.get("base_url") or None
    timeout_seconds = float(payload.get("timeout") or 120)

    config = load_model_config(
        model_name=model_name,
        base_url=requested_base_url,
        timeout_seconds=timeout_seconds,
    )
    base_model = build_chat_model(config)
    observation_base_model = base_model
    if use_llm_observation and thinking_mode and model_name == DEFAULT_THINKING_MODEL:
        observation_config = load_model_config(
            model_name=DEFAULT_MODEL,
            base_url=requested_base_url,
            timeout_seconds=timeout_seconds,
        )
        observation_base_model = build_chat_model(observation_config)

    if log_store is None:
        return base_model, observation_base_model if use_llm_observation else None

    model = LoggingChatModel(base_model, log_store, run_id, purpose="agent")
    observation_model = (
        LoggingChatModel(observation_base_model, log_store, run_id, purpose="observation")
        if use_llm_observation
        else None
    )
    return model, observation_model


def _model_extra_body(payload):
    extra_body = payload.get("model_extra_body") or {}
    if isinstance(extra_body, str):
        if not extra_body.strip():
            return {}
        extra_body = json.loads(extra_body)
    if not isinstance(extra_body, dict):
        raise ValueError("model_extra_body must be a JSON object")
    return extra_body


def _agent_system_prompts_from_payload(payload):
    prompts = payload.get("agent_system_prompts") or {}
    if isinstance(prompts, str):
        if not prompts.strip():
            return {}
        prompts = json.loads(prompts)
    if not isinstance(prompts, dict):
        raise ValueError("agent_system_prompts must be a JSON object")
    return {str(key): str(value) for key, value in prompts.items() if str(value).strip()}


def _parse_query(query):
    values = {}
    if not query:
        return values
    for part in query.split("&"):
        if not part:
            continue
        if "=" not in part:
            values[part] = ""
            continue
        key, value = part.split("=", 1)
        values[key] = value
    return values
