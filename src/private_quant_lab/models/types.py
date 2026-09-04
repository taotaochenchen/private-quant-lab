"""Shared chat model value objects."""

from dataclasses import dataclass


VALID_ROLES = {"system", "user", "assistant", "tool"}


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    def __post_init__(self):
        if self.role not in VALID_ROLES:
            raise ValueError("unsupported chat role: {0}".format(self.role))
        if not self.content:
            raise ValueError("message content must not be empty")


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
