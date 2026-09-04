"""Live DeepSeek ReAct smoke test with mocked quant tools.

Usage:
    python3 scripts/smoke_quant_react.py "分析一下 NVDA 的趋势和风险"
    python3 scripts/smoke_quant_react.py --local-observation "分析一下 NVDA 的趋势和风险"
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.agents import ReActAgent, ReActAgentError
from private_quant_lab.models import ModelConfigError, ModelError, build_chat_model, load_model_config
from private_quant_lab.tools import build_mock_quant_environment, common_quant_tool_names


DEFAULT_TASK = "用 mock 工具分析一下 NVDA 的市场快照、技术面和主要风险，最后给出简短结论。"


def main():
    args = _parse_args()
    print("Common quant tools:")
    for name in common_quant_tool_names():
        print("- " + name)
    print()

    try:
        model_name = args.model
        if args.thinking_mode and model_name == "deepseek-chat":
            model_name = "deepseek-reasoner"
        config = load_model_config(
            model_name=model_name,
            base_url=args.base_url,
            timeout_seconds=args.timeout,
        )
        model = build_chat_model(config)
        observation_model = None if args.local_observation else model
        environment = build_mock_quant_environment(observation_model=observation_model)
        agent = ReActAgent(
            model,
            environment,
            max_steps=args.max_steps,
        )
        result = agent.run(args.task, max_tokens=args.max_tokens)
    except (ModelConfigError, ModelError, ReActAgentError, ValueError) as exc:
        print("FAILED: {0}".format(exc))
        if isinstance(exc, ReActAgentError) and exc.trace:
            print()
            _print_trace(exc.trace)
        return 1

    print("Trace:")
    _print_trace(result.trace)
    print("\nFinal:\n{0}".format(result.final))
    return 0


def _print_trace(trace):
    for item in trace:
        if item["type"] == "assistant":
            print("\nAssistant:\n{0}".format(item["content"]))
            if item.get("reasoning_content"):
                print("Reasoning:")
                print(item["reasoning_content"])
            if item.get("tool_calls"):
                print("Tool calls:")
                print(json.dumps(item["tool_calls"], ensure_ascii=False, indent=2))
        else:
            print("\nTool {0}:\n{1}".format(item["name"], json.dumps(item["output"], ensure_ascii=False, indent=2)))


def _parse_args():
    parser = argparse.ArgumentParser(description="Run a live ReAct flow with mocked quant tools.")
    parser.add_argument("task", nargs="?", default=DEFAULT_TASK)
    parser.add_argument("--model", default="deepseek-chat", help="model name")
    parser.add_argument("--base-url", help="provider base URL")
    parser.add_argument("--timeout", type=float, default=120, help="request timeout seconds")
    parser.add_argument("--max-tokens", type=int, default=700, help="per-step completion token limit")
    parser.add_argument("--max-steps", type=int, default=4, help="maximum ReAct tool iterations")
    parser.add_argument(
        "--thinking-mode",
        action="store_true",
        help="use deepseek-reasoner when the selected model is deepseek-chat",
    )
    parser.add_argument(
        "--local-observation",
        action="store_true",
        help="use deterministic local observations instead of DeepSeek-simulated observations",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
