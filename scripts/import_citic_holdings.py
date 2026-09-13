"""读取中信 Mac 导出的 XLS；默认仅打印条数，--json 显式输出持仓白名单字段。"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.trading.holdings_import import load_citic_holdings, HoldingsImportError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", action="store_true", help="将持仓字段输出到终端；不包含账号列")
    args = parser.parse_args()
    try:
        result = load_citic_holdings(args.path)
    except HoldingsImportError as exc:
        print("导入失败：" + str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("读取成功：{0} 条持仓，{1} 条字段提示。账号列未输出，源文件未修改。".format(len(result["positions"]), len(result["warnings"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
