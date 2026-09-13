"""单独运行市场情绪 Agent；会请求模型 API，默认 observation 使用本地 mock。"""

import argparse
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.agents import ReActAgent, ReActAgentError
from private_quant_lab.agents.market_sentiment import MarketSentimentSession
from private_quant_lab.models import build_chat_model, load_model_config, ModelError, ModelConfigError
from private_quant_lab.tools import build_mock_quant_environment
from private_quant_lab.workflows.pre_market import PRE_MARKET_AGENT_NODES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--as-of", default=datetime.now(timezone(timedelta(hours=8))).isoformat())
    parser.add_argument("--llm-observation", action="store_true", help="让 DeepSeek 同时模拟数据工具 observation")
    parser.add_argument("--sp-file", type=Path, help="读取自定义市场情绪 SP")
    args = parser.parse_args()
    try:
        model = build_chat_model(load_model_config(model_name=args.model))
        environment = build_mock_quant_environment(observation_model=model if args.llm_observation else None)
        session = MarketSentimentSession(environment, args.as_of)
        node = PRE_MARKET_AGENT_NODES[0]
        prompt = args.sp_file.read_text(encoding="utf-8") if args.sp_file else node["system_prompt"]
        task = {"scheduled_task": {"name": "daily_pre_market", "market": "CN_A", "as_of": args.as_of,
                "session": "pre_market"}, "current_agent": node["name"], "instruction": node["instruction"], "upstream_results": []}
        def event(name, payload):
            print(json.dumps({"event": name, "data": payload}, ensure_ascii=False), flush=True)
        result = ReActAgent(model, session, max_steps=8).run(json.dumps(task, ensure_ascii=False),
            system_prompt=prompt, max_tokens=2000, model_extra_body={"response_format": {"type": "json_object"}}, on_event=event)
        report = session.validate_final(result.final)
        print(json.dumps({"validated_result": report}, ensure_ascii=False, indent=2))
        return 1 if report["data_missing"] else 0
    except (ModelError, ModelConfigError, ReActAgentError, ValueError, OSError) as exc:
        print("FAILED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
