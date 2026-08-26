import importlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class PackageImportTests(unittest.TestCase):
    def test_domain_packages_import(self) -> None:
        for module_name in (
            "private_quant.data",
            "private_quant.strategies",
            "private_quant.backtest",
            "private_quant.risk",
            "private_quant.portfolio",
            "private_quant.broker",
            "private_quant.app",
            "private_quant.research",
            "private_quant.social",
        ):
            with self.subTest(module_name=module_name):
                self.assertIsNotNone(importlib.import_module(module_name))


if __name__ == "__main__":
    unittest.main()
