"""OpenAI-compatible chat-completions adapter."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import ChatModel
from .types import ChatResponse, TokenUsage


class ModelError(RuntimeError):
    """Base class for model provider failures."""


class ModelAuthenticationError(ModelError):
    """Raised when the provider rejects credentials."""


class ModelRateLimitError(ModelError):
    """Raised when the provider rate limits a request."""


class ModelRequestError(ModelError):
    """Raised for transport errors or malformed provider responses."""


class OpenAICompatibleChatModel(ChatModel):
    """Minimal non-streaming client for OpenAI-compatible chat APIs."""

    def __init__(self, api_key, model, base_url, timeout_seconds=60.0, post_json=None):
        self.api_key = _required(api_key, "api_key")
        self.model = _required(model, "model")
        self.base_url = _required(base_url, "base_url").rstrip("/")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self._post_json = post_json or self._http_post_json

    def complete(
        self,
        messages,
        temperature=None,
        max_tokens=None,
        extra_body=None,
    ):
        if not messages:
            raise ValueError("messages must not be empty")
        if max_tokens is not None and max_tokens <= 0:
            raise ValueError("max_tokens must be positive")

        body = {
            "model": self.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": False,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if extra_body:
            blocked = sorted(set(extra_body).intersection({"model", "messages", "stream"}))
            if blocked:
                raise ValueError(
                    "extra_body cannot override protected fields: {0}".format(
                        ", ".join(blocked)
                    )
                )
            body.update(extra_body)

        payload = self._post_json(
            self.base_url + "/chat/completions",
            {
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            body,
            self.timeout_seconds,
        )
        return _parse_response(payload)

    @staticmethod
    def _http_post_json(url, headers, body, timeout_seconds):
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ModelAuthenticationError("model authentication failed") from exc
            if exc.code == 429:
                raise ModelRateLimitError("model rate limit exceeded") from exc
            raise ModelRequestError("model provider HTTP error: {0}".format(exc.code)) from exc
        except URLError as exc:
            raise ModelRequestError("model provider network error: {0}".format(exc.reason)) from exc

        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ModelRequestError("model provider returned invalid JSON") from exc


def _parse_response(payload):
    try:
        choices = payload["choices"]
        choice = choices[0]
        message = choice["message"]
        content = message["content"]
        if not isinstance(content, str):
            raise TypeError("content is not text")
        reasoning_content = message.get("reasoning_content") or ""
        usage_payload = payload.get("usage") or {}
        return ChatResponse(
            content=content,
            model=str(payload.get("model") or ""),
            finish_reason=str(choice.get("finish_reason") or ""),
            usage=TokenUsage(
                prompt_tokens=int(usage_payload.get("prompt_tokens", 0)),
                completion_tokens=int(usage_payload.get("completion_tokens", 0)),
                total_tokens=int(usage_payload.get("total_tokens", 0)),
            ),
            reasoning_content=reasoning_content if isinstance(reasoning_content, str) else "",
            response_id=str(payload.get("id") or ""),
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ModelRequestError("model provider returned an invalid response") from exc


def _required(value, label):
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("{0} must not be empty".format(label))
    return normalized
