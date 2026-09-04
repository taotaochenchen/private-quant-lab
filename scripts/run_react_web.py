"""Run the local ReAct loop test web UI.

Usage:
    python3 scripts/run_react_web.py
    python3 scripts/run_react_web.py --port 8787
"""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.web.server import create_server


def main():
    args = _parse_args()
    server = create_server(host=args.host, port=args.port)
    url = "http://{0}:{1}".format(args.host, args.port)
    print("Private Quant Lab ReAct UI")
    print(url)
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0


def _parse_args():
    parser = argparse.ArgumentParser(description="Run the local ReAct test web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
