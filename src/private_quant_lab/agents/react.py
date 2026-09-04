"""Minimal ReAct agent loop for text-only chat models."""

import json
import re

from private_quant_lab.models import ChatMessage


ACTION_RE = re.compile(
    r"Action:\s*(?P<name>[A-Za-z0-9_]+)\s*[\r\n]+Action Input:\s*(?P<input>\{.*?\})",
    re.DOTALL,
)
FINAL_RE = re.compile(r"Final:\s*(?P<final>.*)", re.DOTALL)


class ReActAgentError(RuntimeError):
    """Raised when a ReAct loop cannot continue."""

    def __init__(self, message, trace=None):
        super().__init__(message)
        self.trace = trace or []


class ReActAgent:
    """Text ReAct agent that can run against OpenAI-compatible chat completions."""

    def __init__(self, model, tool_environment, max_steps=4):
        if max_steps <= 0:
            raise ValueError("max_steps must be positive")
        self.model = model
        self.tool_environment = tool_environment
        self.max_steps = max_steps

    def run(self, task, temperature=0, max_tokens=700):
        messages = [
            ChatMessage("system", self._system_prompt()),
            ChatMessage("user", str(task).strip()),
        ]
        trace = []

        for _step in range(self.max_steps):
            response = self.model.complete(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.content.strip()
            trace.append({"type": "assistant", "content": content})
            final = _parse_final(content)
            if final:
                return ReActRunResult(final=final, trace=trace)

            action_name, arguments = _parse_action(content)
            tool_result = self.tool_environment.run(action_name, arguments)
            observation = json.dumps(tool_result.output, ensure_ascii=False, sort_keys=True)
            trace.append(
                {
                    "type": "tool",
                    "name": tool_result.name,
                    "output": tool_result.output,
                }
            )
            messages.append(ChatMessage("assistant", content))
            messages.append(ChatMessage("user", "Observation: {0}".format(observation)))

        raise ReActAgentError("agent reached max_steps without Final", trace=trace)

    def _system_prompt(self):
        return (
            "You are a quant research ReAct agent. Use tools when useful, then provide a concise answer.\n"
            "You should use at most two tool calls before Final unless the user explicitly asks for more.\n"
            "After receiving an Observation, either call one more necessary tool or answer with Final.\n"
            "Available tools:\n"
            "{0}\n\n"
            "Use exactly one of these response formats:\n"
            "Thought: short reason\n"
            "Action: tool_name\n"
            "Action Input: {{\"key\": \"value\"}}\n\n"
            "or:\n"
            "Final: answer for the user\n"
            "Tool outputs are mocked and must be treated as flow-test data, not investment advice."
        ).format(self.tool_environment.describe())


class ReActRunResult:
    def __init__(self, final, trace):
        self.final = final
        self.trace = trace


def _parse_final(content):
    match = FINAL_RE.search(content)
    if not match:
        return ""
    return match.group("final").strip()


def _parse_action(content):
    match = ACTION_RE.search(content)
    if not match:
        raise ReActAgentError(
            "model response did not contain Action/Action Input or Final: {0}".format(content)
        )
    try:
        arguments = json.loads(match.group("input"))
    except ValueError as exc:
        raise ReActAgentError("Action Input must be valid JSON") from exc
    return match.group("name").strip(), arguments
