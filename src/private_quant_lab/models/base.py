"""Provider-neutral model contracts."""

from abc import ABC, abstractmethod

from .types import ChatMessage, ChatResponse


class ChatModel(ABC):
    """Common interface for all chat model providers."""

    @abstractmethod
    def complete(
        self,
        messages,
        temperature=None,
        max_tokens=None,
        tools=None,
        tool_choice=None,
        extra_body=None,
    ):
        """Return one non-streaming chat completion.

        Args:
            messages: Sequence of ChatMessage values.
            temperature: Optional provider temperature value.
            max_tokens: Optional completion token limit.
            tools: Optional OpenAI-compatible tool definitions.
            tool_choice: Optional OpenAI-compatible tool choice.
            extra_body: Optional provider-specific request fields.
        """
