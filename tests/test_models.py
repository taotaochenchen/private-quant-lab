from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.models import (
    ChatMessage,
    ChatModel,
    ChatToolCall,
    ModelConfigError,
    ModelRequestError,
    OpenAICompatibleChatModel,
    build_chat_model,
    load_model_config,
    load_model_name_config,
    resolve_model_provider,
)


class ModelInterfaceTests(unittest.TestCase):
    def test_chat_model_is_abstract(self):
        with self.assertRaises(TypeError):
            ChatModel()

    def test_chat_message_validates_common_roles(self):
        self.assertEqual(ChatMessage("user", "hello").role, "user")
        self.assertEqual(
            ChatMessage(
                "assistant",
                "",
                tool_calls=[ChatToolCall("call-1", "market_snapshot", {"symbol": "NVDA"})],
            ).tool_calls[0].name,
            "market_snapshot",
        )
        with self.assertRaisesRegex(ValueError, "unsupported chat role"):
            ChatMessage("bad-role", "hello")
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            ChatMessage("user", "")


class ModelConfigurationTests(unittest.TestCase):
    def test_builds_deepseek_config_from_model_name(self):
        config = load_model_config(
            env_path=_missing_env_path(),
            environ={
                "MODEL_NAME": "deepseek-v4-flash",
                "DEEPSEEK_API_KEY": "deepseek-secret",
            },
        )

        self.assertEqual(config.model, "deepseek-v4-flash")
        self.assertEqual(config.base_url, "https://api.deepseek.com")
        self.assertEqual(config.api_key_env, "DEEPSEEK_API_KEY")
        self.assertNotIn("deepseek-secret", repr(config))
        self.assertIsInstance(build_chat_model(config), OpenAICompatibleChatModel)

    def test_builds_chatgpt_config_from_model_name(self):
        config = load_model_config(
            env_path=_missing_env_path(),
            environ={
                "MODEL_NAME": "gpt-5.6-sol",
                "OPENAI_API_KEY": "openai-secret",
                "MODEL_TIMEOUT_SECONDS": "30",
            },
        )

        self.assertEqual(config.model, "gpt-5.6-sol")
        self.assertEqual(config.base_url, "https://api.openai.com/v1")
        self.assertEqual(config.api_key_env, "OPENAI_API_KEY")
        self.assertEqual(config.timeout_seconds, 30.0)
        self.assertNotIn("openai-secret", repr(config))

    def test_rejects_missing_key(self):
        with self.assertRaisesRegex(ModelConfigError, "OPENAI_API_KEY"):
            load_model_config(
                env_path=_missing_env_path(),
                environ={"MODEL_NAME": "gpt-5.6-sol"},
            )

    def test_loads_named_model_without_editing_environment(self):
        config = load_model_name_config(
            "gpt-5.6-sol",
            env_path=_missing_env_path(),
            environ={"OPENAI_API_KEY": "openai-secret"},
        )

        self.assertEqual(config.model, "gpt-5.6-sol")

    def test_config_overrides_are_explicit(self):
        config = load_model_config(
            env_path=_missing_env_path(),
            environ={
                "MODEL_NAME": "deepseek-v4-flash",
                "DEEPSEEK_API_KEY": "deepseek-secret",
            },
        ).with_overrides(model="deepseek-v4-pro", timeout_seconds=10)

        self.assertEqual(config.model, "deepseek-v4-pro")
        self.assertEqual(config.timeout_seconds, 10)

    def test_model_name_override_selects_matching_key(self):
        config = load_model_config(
            env_path=_missing_env_path(),
            environ={
                "MODEL_NAME": "deepseek-v4-flash",
                "DEEPSEEK_API_KEY": "deepseek-secret",
                "OPENAI_API_KEY": "openai-secret",
                "MODEL_BASE_URL": "https://api.deepseek.com",
            },
            model_name="gpt-5.6-sol",
        )

        self.assertEqual(config.model, "gpt-5.6-sol")
        self.assertEqual(config.api_key_env, "OPENAI_API_KEY")
        self.assertEqual(config.base_url, "https://api.openai.com/v1")

    def test_provider_specific_base_url_override(self):
        config = load_model_config(
            env_path=_missing_env_path(),
            environ={
                "MODEL_NAME": "gpt-custom",
                "OPENAI_API_KEY": "openai-secret",
                "OPENAI_BASE_URL": "https://proxy.example/v1",
            },
        )

        self.assertEqual(config.base_url, "https://proxy.example/v1")

    def test_cross_provider_config_override_is_rejected_without_matching_key(self):
        config = load_model_config(
            env_path=_missing_env_path(),
            environ={
                "MODEL_NAME": "deepseek-v4-flash",
                "DEEPSEEK_API_KEY": "deepseek-secret",
            },
        )

        with self.assertRaisesRegex(ModelConfigError, "load_model_config"):
            config.with_overrides(model="gpt-5.6-sol")

    def test_resolves_provider_from_model_prefix(self):
        self.assertEqual(
            resolve_model_provider("deepseek-custom")["api_key_env"],
            "DEEPSEEK_API_KEY",
        )
        self.assertEqual(
            resolve_model_provider("gpt-custom")["api_key_env"],
            "OPENAI_API_KEY",
        )


class OpenAICompatibleAdapterTests(unittest.TestCase):
    def test_sends_chat_completion_request_and_maps_response(self):
        calls = []

        def fake_post(url, headers, body, timeout_seconds):
            calls.append((url, headers, body, timeout_seconds))
            return {
                "id": "completion-1",
                "model": "demo-model",
                "choices": [
                    {
                        "message": {"content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "total_tokens": 3,
                },
            }

        model = OpenAICompatibleChatModel(
            api_key="secret",
            model="demo-model",
            base_url="https://provider.example/v1/",
            timeout_seconds=12,
            post_json=fake_post,
        )
        response = model.complete(
            [ChatMessage("system", "Be brief."), ChatMessage("user", "Ping")],
            temperature=0.1,
            max_tokens=20,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "market_snapshot",
                        "description": "Get quote.",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            tool_choice="auto",
        )

        self.assertEqual(response.content, "ok")
        self.assertEqual(response.usage.total_tokens, 3)
        self.assertEqual(calls[0][0], "https://provider.example/v1/chat/completions")
        self.assertEqual(calls[0][1]["Authorization"], "Bearer secret")
        self.assertEqual(calls[0][2]["messages"][1]["content"], "Ping")
        self.assertEqual(calls[0][2]["tools"][0]["function"]["name"], "market_snapshot")
        self.assertEqual(calls[0][2]["tool_choice"], "auto")
        self.assertEqual(calls[0][2]["temperature"], 0.1)
        self.assertEqual(calls[0][3], 12)

    def test_maps_tool_calls_and_sends_tool_messages(self):
        calls = []

        def fake_post(url, headers, body, timeout_seconds):
            calls.append(body)
            return {
                "id": "completion-1",
                "model": "demo-model",
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "market_snapshot",
                                        "arguments": '{"symbol": "NVDA"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }

        model = OpenAICompatibleChatModel(
            api_key="secret",
            model="demo-model",
            base_url="https://provider.example/v1/",
            post_json=fake_post,
        )

        response = model.complete(
            [
                ChatMessage(
                    "assistant",
                    "",
                    tool_calls=[ChatToolCall("call-1", "market_snapshot", {"symbol": "NVDA"})],
                ),
                ChatMessage("tool", '{"price": 1}', tool_call_id="call-1"),
            ]
        )

        self.assertEqual(response.tool_calls[0].name, "market_snapshot")
        self.assertEqual(response.tool_calls[0].arguments["symbol"], "NVDA")
        self.assertEqual(calls[0]["messages"][0]["tool_calls"][0]["id"], "call-1")
        self.assertEqual(calls[0]["messages"][1]["tool_call_id"], "call-1")

    def test_maps_optional_reasoning_content(self):
        model = OpenAICompatibleChatModel(
            api_key="secret",
            model="demo-model",
            base_url="https://provider.example/v1/",
            post_json=lambda *args: {
                "model": "demo-model",
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": "internal notes",
                        },
                        "finish_reason": "length",
                    }
                ],
            },
        )

        response = model.complete([ChatMessage("user", "Ping")])

        self.assertEqual(response.content, "")
        self.assertEqual(response.reasoning_content, "internal notes")
        self.assertEqual(response.finish_reason, "length")

    def test_rejects_invalid_requests_and_responses(self):
        model = OpenAICompatibleChatModel(
            api_key="secret",
            model="demo",
            base_url="https://provider.example/v1",
            post_json=lambda *args: {"choices": []},
        )

        with self.assertRaisesRegex(ValueError, "messages must not be empty"):
            model.complete([])
        with self.assertRaisesRegex(ValueError, "max_tokens"):
            model.complete([ChatMessage("user", "hello")], max_tokens=0)
        with self.assertRaisesRegex(ValueError, "protected fields"):
            model.complete([ChatMessage("user", "hello")], extra_body={"model": "x"})
        with self.assertRaisesRegex(ValueError, "protected fields"):
            model.complete([ChatMessage("user", "hello")], extra_body={"tools": []})
        with self.assertRaises(ModelRequestError):
            model.complete([ChatMessage("user", "hello")])


def _missing_env_path():
    directory = tempfile.TemporaryDirectory()
    path = Path(directory.name) / ".env"
    _MISSING_ENV_DIRS.append(directory)
    return path


_MISSING_ENV_DIRS = []


if __name__ == "__main__":
    unittest.main()
