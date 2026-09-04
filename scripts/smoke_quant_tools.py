"""Local smoke runner for mocked quant tools.

Usage:
    python3 scripts/smoke_quant_tools.py --list
    python3 scripts/smoke_quant_tools.py market_snapshot '{"symbol": "NVDA"}'
    python3 scripts/smoke_quant_tools.py technical_indicators '{"symbol": "SPY"}'
    python3 scripts/smoke_quant_tools.py --llm-observation web_search '{"query": "NVDA AI demand", "limit": 3}'
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.models import ModelConfigError, ModelError, build_chat_model, load_model_config
from private_quant_lab.tools import build_mock_quant_environment


def main():
    args = _parse_args()
    try:
        observation_model = _build_observation_model(args)
    except (ModelConfigError, ModelError, ValueError) as exc:
        print("FAILED: {0}".format(exc))
        return 1

    environment = build_mock_quant_environment(observation_model=observation_model)

    if args.list:
        print(environment.describe())
        return 0

    if not args.tool:
        print("Use --list or provide a tool name.")
        return 2

    try:
        arguments = json.loads(args.arguments)
    except ValueError as exc:
        print("Arguments must be valid JSON: {0}".format(exc))
        return 2

    try:
        result = environment.run(args.tool, arguments)
    except ValueError as exc:
        print("FAILED: {0}".format(exc))
        return 1

    print(json.dumps(result.output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _parse_args():
    parser = argparse.ArgumentParser(description="Run a mocked quant tool locally.")
    parser.add_argument("tool", nargs="?", help="tool name")
    parser.add_argument("arguments", nargs="?", default="{}", help="tool arguments as JSON")
    parser.add_argument("--list", action="store_true", help="list available tools and schemas")
    parser.add_argument(
        "--llm-observation",
        action="store_true",
        help="use the configured chat model to simulate tool observation JSON",
    )
    parser.add_argument("--model", default="deepseek-chat", help="observation model name")
    parser.add_argument("--base-url", help="provider base URL")
    parser.add_argument("--timeout", type=float, default=120, help="request timeout seconds")
    return parser.parse_args()


def _build_observation_model(args):
    if not args.llm_observation:
        return None
    config = load_model_config(
        model_name=args.model,
        base_url=args.base_url,
        timeout_seconds=args.timeout,
    )
    return build_chat_model(config)


if __name__ == "__main__":
    raise SystemExit(main())
