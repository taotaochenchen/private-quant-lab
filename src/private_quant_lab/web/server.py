"""Local web UI for testing the ReAct agent loop."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from private_quant_lab.agents import ReActAgent, ReActAgentError
from private_quant_lab.models import ModelConfigError, ModelError, build_chat_model, load_model_config
from private_quant_lab.tools import build_mock_quant_environment, common_quant_tool_names
from private_quant_lab.web.logging import LoggingChatModel, RequestLogStore


STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TASK = "先用 web_search 查 NVDA AI demand，再用 technical_indicators 看 NVDA 技术面，最后输出 Final。"
REQUEST_LOGS = RequestLogStore()


def create_server(host="127.0.0.1", port=8765):
    """Create the local ReAct test server."""

    return ThreadingHTTPServer((host, port), ReActWebHandler)


class ReActWebHandler(BaseHTTPRequestHandler):
    server_version = "PrivateQuantReActWeb/0.1"

    def do_GET(self):
        path = urlparse(self.path).path
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
            self._send_json({"tools": common_quant_tool_names(), "default_task": DEFAULT_TASK})
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
        self._send_json({"error": "not found"}, status=404)

    def do_HEAD(self):
        path = urlparse(self.path).path
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
        if path == "/api/logs/clear":
            REQUEST_LOGS.clear()
            self._send_json({"ok": True})
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


def run_react_request(payload, run_id=None, log_store=None):
    """Run one ReAct request from web JSON payload."""

    if run_id is None:
        run_id = str(uuid4())
    task = str(payload.get("task") or DEFAULT_TASK).strip()
    if not task:
        raise ValueError("task must not be empty")
    model_name = str(payload.get("model") or DEFAULT_MODEL).strip()
    max_steps = int(payload.get("max_steps") or 4)
    max_tokens = int(payload.get("max_tokens") or 900)
    use_llm_observation = bool(payload.get("llm_observation", True))

    config = load_model_config(
        model_name=model_name,
        base_url=payload.get("base_url") or None,
        timeout_seconds=float(payload.get("timeout") or 120),
    )
    base_model = build_chat_model(config)
    if log_store is None:
        model = base_model
        observation_model = model if use_llm_observation else None
    else:
        model = LoggingChatModel(base_model, log_store, run_id, purpose="agent")
        observation_model = (
            LoggingChatModel(base_model, log_store, run_id, purpose="observation")
            if use_llm_observation
            else None
        )
    environment = build_mock_quant_environment(observation_model=observation_model)
    agent = ReActAgent(model, environment, max_steps=max_steps)
    return agent.run(task, max_tokens=max_tokens)


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
