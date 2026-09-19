"""生成每日盘前决策 + 复盘摘要，输出纯文本，供定时任务发送到手机。

用法：
    python scripts/daily_report.py                 # 生成今日决策 + 复盘
    python scripts/daily_report.py --real-data     # 市场快照/宽度用真实 akshare 数据
    python scripts/daily_report.py --model deepseek-chat
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.domain import get_trading_calendar
from private_quant_lab.models import ModelConfigError, ModelError, build_chat_model, load_model_config
from private_quant_lab.tools import build_mock_quant_environment
from private_quant_lab.web.snapshot import load_latest_report, save_latest_report
from private_quant_lab.workflows import PreMarketWorkflow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None, help="模型名，默认用 .env 的 MODEL_NAME")
    parser.add_argument("--real-data", action="store_true", help="市场快照/宽度使用真实 akshare 数据")
    args = parser.parse_args()
    try:
        config = load_model_config(model_name=args.model) if args.model else load_model_config()
        model = build_chat_model(config)
        environment = build_mock_quant_environment(real_data=args.real_data)

        snapshot = load_latest_report()
        previous_report = None
        previous_trade_date = None
        if snapshot and snapshot.get("report_date") and snapshot["report_date"] < date.today().isoformat():
            previous_report = snapshot
            previous_trade_date = snapshot["report_date"]

        workflow = PreMarketWorkflow(model, environment, max_steps=8)
        result = workflow.run(
            manual_advice=True,
            previous_report=previous_report,
            previous_trade_date=previous_trade_date,
            calendar=get_trading_calendar(),
            model_extra_body={"response_format": {"type": "json_object"}},
        )
        report = result.report
        save_latest_report(report)
        print(format_summary(report))
        return 0
    except (ModelError, ModelConfigError, ValueError, KeyError) as exc:
        print("每日报告生成失败：" + str(exc), file=sys.stderr)
        return 1


def format_summary(report):
    """把盘前报告 + 策略修订（复盘）压缩成适合手机阅读的纯文本。"""
    lines = []
    market = report.get("market_state") or {}
    direction = _cn(market.get("direction"), {"bullish": "看多", "bearish": "看空", "neutral": "中性", "unknown": "未知"})
    mode = _cn(market.get("trading_mode"), {"attack": "进攻", "defense": "防守", "rotation": "轮动", "observe": "观察"})
    sentiment = market.get("sentiment_score")
    lines.append("📊 盘前决策 {0}".format(report.get("report_date", "")))
    lines.append("市场：{0} · {1}｜情绪 {2}".format(
        direction, mode, sentiment if sentiment is not None else "—"))

    plans = report.get("trade_plan") or []
    lines.append("")
    lines.append("【今日建议】")
    if plans:
        for plan in plans:
            side = _cn(plan.get("side"), {"buy": "买", "sell": "卖", "hold": "持有", "avoid": "回避"})
            lines.append("- {0} {1} {2} {3}".format(
                plan.get("symbol", "?"), plan.get("name", ""), side,
                plan.get("first_position") or plan.get("max_position") or ""))
    else:
        lines.append("无（观察 / 风控暂停）")

    revision = report.get("strategy_revision")
    if revision:
        changes = revision.get("changes") or []
        lines.append("")
        lines.append("【复盘 vs {0}】".format(revision.get("previous_trade_date", "昨日")))
        counts = {}
        for item in changes:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        status_cn = {"retained": "保留", "adjusted": "调整", "withdrawn": "撤回",
                     "suspended": "暂停", "added": "新增", "initial": "首次"}
        parts = ["{0} {1}".format(status_cn.get(key, key), value) for key, value in sorted(counts.items())]
        lines.append(" · ".join(parts) if parts else "无变化")
        for item in changes:
            if item["status"] in ("adjusted", "withdrawn", "added"):
                exe = _cn(item.get("execution_status"),
                          {"executed": "已执行", "partial": "部分", "skipped": "未执行", "unknown": "未反馈"})
                lines.append("- {0} {1}（{2}）".format(
                    item["symbol"], status_cn.get(item["status"], item["status"]), exe))
    else:
        lines.append("")
        lines.append("【复盘】首次分析，无 T-1 基线")

    lines.append("")
    lines.append("仅供研究参考，不构成投资建议；实际持仓与成交请人工核验。")
    return "\n".join(lines)


def _cn(value, mapping):
    return mapping.get(value, str(value or "—"))


if __name__ == "__main__":
    raise SystemExit(main())
