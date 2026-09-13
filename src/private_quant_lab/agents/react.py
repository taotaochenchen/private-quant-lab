"""OpenAI tool-calling agent loop."""

import json
import time

from private_quant_lab.models import ChatMessage


DEFAULT_SYSTEM_PROMPT = (
    "You are a quant research assistant. Use the provided tools when data is needed. "
    "Return a concise final answer after enough tool observations. "
    "Tool outputs are mocked and must be treated as flow-test data, not investment advice."
)


class ReActAgentError(RuntimeError):
    """Raised when the agent loop cannot continue."""

    def __init__(self, message, trace=None):
        super().__init__(message)
        self.trace = trace or []


class ReActAgent:
    """Agent loop using the standard OpenAI chat-completions tools protocol."""

    def __init__(
        self,
        model,
        tool_environment,
        max_steps=4,
        max_runtime_seconds=180,
        max_tool_repeats=2,
        tool_retry_limit=1,
    ):
        if max_steps <= 0:
            raise ValueError("max_steps must be positive")
        self.model = model
        self.tool_environment = tool_environment
        self.max_steps = max_steps
        self.max_runtime_seconds = max_runtime_seconds
        self.max_tool_repeats = max_tool_repeats
        self.tool_retry_limit = tool_retry_limit

    def run(
        self,
        task,
        temperature=0,
        max_tokens=700,
        model_extra_body=None,
        system_prompt=None,
        on_event=None,
    ):
        prompt = str(system_prompt or DEFAULT_SYSTEM_PROMPT).strip()
        if not prompt:
            prompt = DEFAULT_SYSTEM_PROMPT
        messages = [
            ChatMessage("system", prompt),
            ChatMessage("user", str(task).strip()),
        ]
        trace = []
        tools = self.tool_environment.openai_tools()
        started_at = time.monotonic()
        tool_call_counts = {}

        _emit(on_event, "run_started", {"max_steps": self.max_steps, "protocol": "openai_tools"})
        for step in range(1, self.max_steps + 1):
            if self.max_runtime_seconds and time.monotonic() - started_at > self.max_runtime_seconds:
                _emit(on_event, "error", {"error": "agent reached max runtime"})
                raise ReActAgentError("agent reached max runtime", trace=trace)

            response = self.model.complete(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                tool_choice="auto",
                extra_body=model_extra_body,
            )

            assistant_item = {
                "type": "assistant",
                "step": step,
                "content": response.content,
                "reasoning_content": response.reasoning_content,
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                    }
                    for tool_call in response.tool_calls
                ],
            }
            trace.append(assistant_item)
            _emit(on_event, "assistant", assistant_item)

            if not response.tool_calls:
                final = response.content.strip()
                if not final:
                    raise ReActAgentError("model returned neither content nor tool_calls", trace=trace)
                _emit(on_event, "final", {"final": final, "trace": trace})
                return ReActRunResult(final=final, trace=trace)

            messages.append(
                ChatMessage(
                    "assistant",
                    response.content,
                    tool_calls=response.tool_calls,
                )
            )

            for tool_call in response.tool_calls:
                if not tool_call.name:
                    raise ReActAgentError("tool call name must not be empty", trace=trace)
                tool_repeat_key = "{0}:{1}".format(
                    tool_call.name,
                    json.dumps(tool_call.arguments, ensure_ascii=False, sort_keys=True),
                )
                tool_call_counts[tool_repeat_key] = tool_call_counts.get(tool_repeat_key, 0) + 1
                if self.max_tool_repeats and tool_call_counts[tool_repeat_key] > self.max_tool_repeats:
                    message = "tool repeated too many times: {0}".format(tool_call.name)
                    _emit(on_event, "error", {"error": message, "tool": tool_call.name})
                    raise ReActAgentError(message, trace=trace)
                _emit(
                    on_event,
                    "tool_started",
                    {
                        "step": step,
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                    },
                )
                tool_result = self._run_tool_with_retry(tool_call.name, tool_call.arguments)
                tool_content = json.dumps(
                    tool_result.output,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                tool_item = {
                    "type": "tool",
                    "step": step,
                    "id": tool_call.id,
                    "name": tool_result.name,
                    "output": tool_result.output,
                }
                trace.append(tool_item)
                _emit(on_event, "tool_finished", tool_item)
                messages.append(
                    ChatMessage(
                        "tool",
                        tool_content,
                        tool_call_id=tool_call.id,
                    )
                )

        _emit(on_event, "error", {"error": "agent reached max_steps without final answer"})
        raise ReActAgentError("agent reached max_steps without final answer", trace=trace)

    def _run_tool_with_retry(self, name, arguments):
        attempts = max(0, self.tool_retry_limit) + 1
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                return self.tool_environment.run(name, arguments)
            except Exception as exc:
                last_error = exc
                if attempt >= attempts:
                    break
        return FailedToolResult(
            name=name,
            output={
                "mock": True,
                "data_missing": True,
                "error": str(last_error),
                "retry_count": attempts - 1,
            },
        )

class ReActRunResult:
    def __init__(self, final, trace):
        self.final = final
        self.trace = trace


class FailedToolResult:
    def __init__(self, name, output):
        self.name = name
        self.output = output


def _emit(callback, event, data):
    if callback is not None:
        callback(event, data)
