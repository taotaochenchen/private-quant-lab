"""In-memory request logs for the local ReAct web UI."""

from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4


class RequestLogStore:
    """Store raw model request/response logs for local debugging."""

    def __init__(self, limit=200):
        self.limit = limit
        self._entries = []

    def add(self, entry):
        self._entries.append(entry)
        if len(self._entries) > self.limit:
            self._entries = self._entries[-self.limit :]

    def list(self, run_id=None, limit=100):
        entries = self._entries
        if run_id:
            entries = [entry for entry in entries if entry["run_id"] == run_id]
        return list(reversed(entries[-limit:]))

    def clear(self):
        self._entries = []


class LoggingChatModel:
    """Wrap a ChatModel and record every raw complete() call."""

    def __init__(self, model, log_store, run_id, purpose):
        self.model = model
        self.log_store = log_store
        self.run_id = run_id
        self.purpose = purpose

    def complete(
        self,
        messages,
        temperature=None,
        max_tokens=None,
        tools=None,
        tool_choice=None,
        extra_body=None,
    ):
        started = perf_counter()
        entry = {
            "id": str(uuid4()),
            "run_id": self.run_id,
            "purpose": self.purpose,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model_name": getattr(self.model, "model", ""),
            "parameters": {
                "temperature": temperature,
                "max_tokens": max_tokens,
                "tool_choice": tool_choice,
                "extra_body": extra_body or {},
            },
            "tools": tools or [],
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                    "tool_call_id": message.tool_call_id,
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                        }
                        for tool_call in message.tool_calls
                    ],
                }
                for message in messages
            ],
        }
        try:
            response = self.model.complete(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                tool_choice=tool_choice,
                extra_body=extra_body,
            )
        except Exception as exc:
            entry["duration_ms"] = round((perf_counter() - started) * 1000, 2)
            entry["error"] = {
                "type": exc.__class__.__name__,
                "message": str(exc),
            }
            self.log_store.add(entry)
            raise

        entry["duration_ms"] = round((perf_counter() - started) * 1000, 2)
        entry["response"] = {
            "content": response.content,
            "model": response.model,
            "finish_reason": response.finish_reason,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            "reasoning_content": response.reasoning_content,
            "response_id": response.response_id,
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                }
                for tool_call in response.tool_calls
            ],
        }
        self.log_store.add(entry)
        return response
