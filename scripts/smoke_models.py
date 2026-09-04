"""Optional live smoke test for configured model names.

Usage:
    python3 scripts/smoke_models.py --model deepseek-v4-flash
    python3 scripts/smoke_models.py --model gpt-5.6-sol
"""

import argparse
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.models import (
    ChatMessage,
    ModelConfigError,
    ModelError,
    build_chat_model,
    load_model_config,
)


def main():
    args = _parse_args()
    theme = _Theme(enabled=not args.no_color and sys.stdout.isatty())

    print(theme.header("Private Quant Lab - Model Smoke Test"))
    print(theme.dim("Checking the configured chat model before live use."))
    print()

    started = perf_counter()
    try:
        config = load_model_config(
            model_name=args.model,
            base_url=args.base_url,
            timeout_seconds=args.timeout,
        )
        _print_config(config, theme)
        model = build_chat_model(config)
        print()
        print(theme.step("Sending prompt"))
        response = model.complete(
            [ChatMessage(role="user", content="介绍一下自己")],
            temperature=0,
            max_tokens=args.max_tokens,
        )
    except (ModelConfigError, ModelError, ValueError) as exc:
        print()
        print(theme.fail("FAILED"))
        print(theme.label("Reason"), str(exc))
        return 1

    elapsed = perf_counter() - started
    if response.content.strip():
        print(theme.ok("Completed"))
    else:
        print(theme.fail("EMPTY RESPONSE"))
    print()
    print(theme.label("Response"), response.content)
    if response.reasoning_content:
        print(theme.label("Reasoning"), response.reasoning_content)
    if response.model:
        print(theme.label("Model"), response.model)
    if response.finish_reason:
        print(theme.label("Finish"), response.finish_reason)
    if response.usage.total_tokens:
        print(theme.label("Tokens"), str(response.usage.total_tokens))
    print(theme.label("Elapsed"), "{0:.2f}s".format(elapsed))
    if not response.content.strip():
        print()
        print(
            theme.dim(
                "Empty content usually means the completion limit was too small, "
                "the model returned only reasoning/tool data, or the selected model "
                "does not behave like a plain chat-completions text model."
            )
        )
    return 0


def _parse_args():
    parser = argparse.ArgumentParser(description="Run a live chat model smoke test.")
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI color output",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=200,
        help="maximum output tokens for the smoke prompt",
    )
    parser.add_argument(
        "--model",
        help="override MODEL_NAME",
    )
    parser.add_argument(
        "--base-url",
        help="override MODEL_BASE_URL",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="override MODEL_TIMEOUT_SECONDS",
    )
    return parser.parse_args()


def _print_config(config, theme):
    rows = [
        ("Model", config.model),
        ("Base URL", config.base_url),
        ("API key", config.api_key_env),
        ("Timeout", "{0:g}s".format(config.timeout_seconds)),
    ]
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print("{0} {1}".format(theme.label(label.ljust(width)), value))


class _Theme:
    def __init__(self, enabled):
        self.enabled = enabled

    def header(self, text):
        return self._paint(text, "1;36")

    def dim(self, text):
        return self._paint(text, "2")

    def label(self, text):
        return self._paint(text + ":", "1")

    def step(self, text):
        return self._paint(".. " + text, "36")

    def ok(self, text):
        return self._paint("OK " + text, "32")

    def fail(self, text):
        return self._paint("!! " + text, "31")

    def _paint(self, text, code):
        if not self.enabled:
            return text
        return "\033[{0}m{1}\033[0m".format(code, text)


if __name__ == "__main__":
    raise SystemExit(main())
