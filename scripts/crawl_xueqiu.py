"""单页雪球采集器。默认只检查访问规则；不绕过登录/验证码，不接入 Agent。"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.tools.xueqiu_crawler import CrawlError, crawl_xueqiu


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://xueqiu.com/")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--permission-confirmed", action="store_true",
                        help="仅当已取得网站针对本项目内容使用的许可时使用；不是授权申请或绕过开关")
    args = parser.parse_args()
    try:
        result = crawl_xueqiu(args.url, args.limit, args.permission_confirmed)
    except CrawlError as exc:
        print(json.dumps({"status": exc.code, "is_mock": False, "data_missing": True}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
