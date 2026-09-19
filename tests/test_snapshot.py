"""最小决策快照模块单元测试：保存/加载/损坏/非对象。"""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.web import snapshot as snapshot_module


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.path = self.dir / "latest.json"
        self.patcher = patch.object(snapshot_module, "SNAPSHOT_DIR", self.dir)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        patcher_path = patch.object(snapshot_module, "SNAPSHOT_PATH", self.path)
        patcher_path.start()
        self.addCleanup(patcher_path.stop)

    def test_round_trip(self):
        report = {"report_date": "2026-09-11", "trade_plan": [{"symbol": "600000.SH"}]}
        self.assertTrue(snapshot_module.save_latest_report(report))
        self.assertEqual(snapshot_module.load_latest_report(), report)

    def test_load_missing_returns_none(self):
        self.assertIsNone(snapshot_module.load_latest_report())

    def test_load_corrupt_returns_none(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(snapshot_module.load_latest_report())

    def test_save_rejects_non_dict(self):
        with self.assertRaises(ValueError):
            snapshot_module.save_latest_report("not a dict")

    def test_save_overwrites_previous(self):
        snapshot_module.save_latest_report({"report_date": "2026-09-11"})
        snapshot_module.save_latest_report({"report_date": "2026-09-14"})
        self.assertEqual(snapshot_module.load_latest_report()["report_date"], "2026-09-14")


if __name__ == "__main__":
    unittest.main()
