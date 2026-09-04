"""Shared chat model value objects."""

from dataclasses import dataclass, field
import json
from typing import Any, Dict, List


VALID_ROLES = {"system", "user", "assistant", "tool"}


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str
    tool_call_id: str = ""
    tool_calls: List["ChatToolCall"] = field(default_factory=list)

    def __post_init__(self):
        if self.role not in VALID_ROLES:
            raise ValueError("unsupported chat role: {0}".format(self.role))
        if not self.content and not self.tool_calls:
            raise ValueError("message content must not be empty")


@dataclass(frozen=True)
class ChatToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]

    def arguments_json(self):
        return json.dumps(self.arguments, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class ChatResponse:
    content: str
    model: str
    finish_reason: str = ""
    usage: TokenUsage = TokenUsage()
    reasoning_content: str = ""
    response_id: str = ""
    tool_calls: List[ChatToolCall] = field(default_factory=list)
