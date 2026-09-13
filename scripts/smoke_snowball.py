"""独立测试 pysnowball 数据接口；凭据仅从本地环境读取，不传给模型。"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.tools.snowball_adapter import load_snowball_settings, run_snowball_tool
from private_quant_lab.tools.snowball_catalog import SPECS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument("--list", action="store_true")
    command.add_argument("--check-config", action="store_true")
    command.add_argument("--function", choices=sorted(SPECS))
    parser.add_argument("--arguments", default="{}", help="JSON 入参，不允许提供 token/cookie")
    args = parser.parse_args()
    try:
        if args.list:
            print(json.dumps([{key: spec[key] for key in ("name", "description", "provider", "requires_token", "example")}
                              for spec in SPECS.values()], ensure_ascii=False, indent=2))
            return 0
        if args.check_config:
            config = load_snowball_settings()
            print(json.dumps({"token_configured": bool(config.get_token()),
                              "content_permission_confirmed": config.content_permission_confirmed,
                              "timeout_seconds": config.timeout_seconds}))
            return 0
        arguments = json.loads(args.arguments)
        result = run_snowball_tool(args.function, arguments)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "ok" else 1
    except ValueError:
        print("参数或配置无效；请查看接口 Schema 和本地配置项。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
