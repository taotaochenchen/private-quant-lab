"""最小决策快照：保存/加载最近一份建议报告，用于跨日自动载入 T-1 基线。

只保存结构化报告（PreMarketReport），不保存模型原始日志（trace / tool calls）。
仅在用户明确允许"保存最小决策快照"后启用；文件落在项目 .local 目录且已加入 gitignore。
"""

import json
from pathlib import Path


SNAPSHOT_DIR = Path(".local/decision-snapshots")
SNAPSHOT_PATH = SNAPSHOT_DIR / "latest.json"


def save_latest_report(report):
    """原子地保存最近一份建议报告；覆盖旧快照，不追加历史。"""
    if not isinstance(report, dict):
        raise ValueError("report must be an object")
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SNAPSHOT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(SNAPSHOT_PATH)
    return True


def load_latest_report():
    """读取最近一份建议报告；不存在或损坏时返回 None。"""
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None
