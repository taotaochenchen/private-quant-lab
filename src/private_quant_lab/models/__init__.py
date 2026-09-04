"""Provider-neutral chat model interface and adapters."""

from .base import ChatModel
from .config import (
    ModelConfig,
    ModelConfigError,
    build_chat_model,
    load_model_config,
    load_model_name_config,
    resolve_model_provider,
)
from .openai_compatible import (
    ModelAuthenticationError,
    ModelError,
    ModelRateLimitError,
    ModelRequestError,
    OpenAICompatibleChatModel,
)
from .types import ChatMessage, ChatResponse, ChatToolCall, TokenUsage

__all__ = [
    "ChatMessage",
    "ChatModel",
    "ChatResponse",
    "ChatToolCall",
    "ModelAuthenticationError",
    "ModelConfig",
    "ModelConfigError",
    "ModelError",
    "ModelRateLimitError",
    "ModelRequestError",
    "OpenAICompatibleChatModel",
    "TokenUsage",
    "build_chat_model",
    "load_model_config",
    "load_model_name_config",
    "resolve_model_provider",
]
