"""不需要 API 或账户的模拟交易演示；模拟成交价格由测试明确给定。"""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.trading import PaperAccount


def main():
    account = PaperAccount("10000", "2026-09-14")
    buy = account.submit("demo-buy", "600000.SH", "buy", 100, "10.00")
    print("买入委托:", json.dumps(buy, ensure_ascii=False))
    account.fill(buy["order_id"], "demo-buy-fill", 100, "9.90")
    print("买入成交后:", json.dumps(account.snapshot(), ensure_ascii=False))
    try:
        account.submit("demo-sell-today", "600000.SH", "sell", 100, "10.00")
    except ValueError as exc:
        print("当日卖出被阻止:", str(exc))
    account.settle_to("2026-09-15")
    sell = account.submit("demo-sell", "600000.SH", "sell", 100, "10.00")
    account.fill(sell["order_id"], "demo-sell-fill", 100, "10.10")
    print("下一交易日卖出后:", json.dumps(account.snapshot(), ensure_ascii=False))


if __name__ == "__main__":
    main()
