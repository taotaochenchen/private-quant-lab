"""Configuration loading and model factory."""

from dataclasses import dataclass, field
import os
from pathlib import Path

from .openai_compatible import OpenAICompatibleChatModel


PROJECT_ROOT = Path(__file__).resolve().parents[3]

MODEL_PROVIDERS = {
    "deepseek-v4-flash": {
        "base_url": "https://api.deepseek.com",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "deepseek-v4-pro": {
        "base_url": "https://api.deepseek.com",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "gpt-5.6-sol": {
        "base_url": "https://api.openai.com/v1",
        "base_url_env": "OPENAI_BASE_URL",
        "api_key_env": "OPENAI_API_KEY",
    },
}

MODEL_PREFIX_PROVIDERS = {
    "deepseek-": {
        "base_url": "https://api.deepseek.com",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "gpt-": {
        "base_url": "https://api.openai.com/v1",
        "base_url_env": "OPENAI_BASE_URL",
        "api_key_env": "OPENAI_API_KEY",
    },
}

DEFAULT_MODEL = "deepseek-v4-flash"


class ModelConfigError(RuntimeError):
    """Raised when model configuration is invalid."""


@dataclass(frozen=True)
class ModelConfig:
    model: str
    api_key: str = field(repr=False)
    base_url: str
    api_key_env: str
    timeout_seconds: float = 60.0

    def with_overrides(
        self,
        model=None,
        api_key=None,
        base_url=None,
        timeout_seconds=None,
    ):
        resolved = resolve_model_provider(str(model or self.model).strip())
        if api_key is None and resolved["api_key_env"] != self.api_key_env:
            raise ModelConfigError(
                "Use load_model_config(model_name=...) when changing model providers."
            )
        return ModelConfig(
            model=str(model or self.model).strip(),
            api_key=str(api_key or self.api_key).strip(),
            base_url=str(base_url or resolved["base_url"]).strip(),
            api_key_env=resolved["api_key_env"],
            timeout_seconds=(
                self.timeout_seconds if timeout_seconds is None else float(timeout_seconds)
            ),
        )


def load_model_config(
    env_path=None,
    environ=None,
    model_name=None,
    base_url=None,
    timeout_seconds=None,
):
    """Load model settings from environment variables and optional .env file."""

    values = {}
    if env_path is None:
        env_path = PROJECT_ROOT / ".env"
    path = Path(env_path)
    if path.exists():
        values.update(_read_dotenv(path))
    values.update(dict(os.environ if environ is None else environ))

    model = str(model_name or _value(values, "MODEL_NAME", DEFAULT_MODEL)).strip()
    provider_config = resolve_model_provider(model)
    api_key = _value(values, provider_config["api_key_env"], "")
    resolved_base_url = _resolve_base_url(values, provider_config, base_url)
    timeout_text = str(
        timeout_seconds
        if timeout_seconds is not None
        else _value(values, "MODEL_TIMEOUT_SECONDS", "60")
    ).strip()

    if not api_key:
        raise ModelConfigError("{0} is required".format(provider_config["api_key_env"]))
    try:
        timeout_seconds = float(timeout_text)
    except ValueError as exc:
        raise ModelConfigError("MODEL_TIMEOUT_SECONDS must be a number") from exc
    if timeout_seconds <= 0:
        raise ModelConfigError("MODEL_TIMEOUT_SECONDS must be positive")

    return ModelConfig(
        model=model,
        api_key=api_key,
        base_url=resolved_base_url,
        api_key_env=provider_config["api_key_env"],
        timeout_seconds=timeout_seconds,
    )


def load_model_name_config(model_name, env_path=None, environ=None):
    """Load configuration for a model name, inferring provider details."""

    return load_model_config(
        env_path=env_path,
        environ=environ,
        model_name=model_name,
    )


def resolve_model_provider(model_name):
    """Resolve endpoint and secret name from a model name."""

    model = str(model_name or "").strip()
    if not model:
        raise ModelConfigError("MODEL_NAME is required")
    if model in MODEL_PROVIDERS:
        return MODEL_PROVIDERS[model]
    for prefix, provider_config in MODEL_PREFIX_PROVIDERS.items():
        if model.startswith(prefix):
            return provider_config
    raise ModelConfigError(
        "Unsupported MODEL_NAME. Add it to MODEL_PROVIDERS or MODEL_PREFIX_PROVIDERS."
    )


def build_chat_model(config):
    """Create a chat model instance from ModelConfig."""

    return OpenAICompatibleChatModel(
        api_key=config.api_key,
        model=config.model,
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
    )


def _value(values, name, default):
    value = values.get(name, default)
    return str(value or "").strip()


def _resolve_base_url(values, provider_config, explicit_base_url):
    if explicit_base_url:
        return str(explicit_base_url).strip()
    base_url_env = provider_config.get("base_url_env", "")
    if base_url_env:
        configured = _value(values, base_url_env, "")
        if configured:
            return configured
    return provider_config["base_url"]


def _read_dotenv(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name:
            values[name] = value
    return values
