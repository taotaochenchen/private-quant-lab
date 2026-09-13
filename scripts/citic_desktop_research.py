"""中信客户端只读标定/单步预览；--execute 仍需终端确认，不操作保存或交易。"""

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.trading.desktop_research import (
    ACTIONS, REFERENCES, DesktopResearchError, PyAutoGUIDesktop, load_reference, run_step,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / ".local/desktop-research")
    commands = parser.add_subparsers(dest="command", required=True)
    position = commands.add_parser("position", help="等待后读取鼠标逻辑坐标，帮助标定，不移动鼠标")
    position.add_argument("--delay", type=int, default=5, choices=range(0, 31), metavar="0..30")
    capture = commands.add_parser("capture", help="仅保存指定区域参考图，不能包含账号或持仓数据")
    capture.add_argument("name", choices=REFERENCES)
    capture.add_argument("--region", nargs=4, type=int, required=True, metavar=("X", "Y", "W", "H"))
    capture.add_argument("--delay", type=int, default=5, choices=range(0, 31), metavar="0..30")
    step = commands.add_parser("step", help="默认只匹配并打印坐标，不移动或点击鼠标")
    step.add_argument("name", choices=ACTIONS)
    step.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "position":
            print("请将鼠标移到待标定区域的角点；{0} 秒后读取坐标。".format(args.delay), flush=True)
            time.sleep(args.delay)
            desktop = PyAutoGUIDesktop(args.directory)
            result = {"point": list(desktop.gui.position()), "screen_size": list(desktop.gui.size())}
        elif args.command == "capture":
            print("请切到客户端，移开鼠标；{0} 秒后只保存指定区域。".format(args.delay), flush=True)
            time.sleep(args.delay)
            result = PyAutoGUIDesktop(args.directory).capture(args.name, args.region)
        else:
            target = load_reference(args.directory, args.name)
            expected = load_reference(args.directory, ACTIONS[args.name])
            guard = load_reference(args.directory, "holdings_view") if args.name == "export_button" else None

            def confirm(name, point):
                if not sys.stdin.isatty():
                    return False
                answer = input("只读点击 {0}，坐标 {1}。输入步骤名确认：".format(name, point))
                if answer.strip() != name:
                    return False
                print("请在 5 秒内切回客户端并移开鼠标；随后重新匹配再点击。", flush=True)
                time.sleep(5)
                return True

            result = run_step(PyAutoGUIDesktop(args.directory), target, expected, guard,
                              execute=args.execute, confirm=confirm)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (DesktopResearchError, OSError, ValueError, EOFError) as exc:
        print("已停止：" + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        return 130
    except Exception as exc:
        # 桌面库错误不回显可能包含账户内容的异常正文。
        print("桌面操作停止（{0}）；请检查权限与页面，不要盲目重试。".format(type(exc).__name__), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
