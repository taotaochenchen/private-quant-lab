import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from private_quant.research.oliver_kell.fundamentals import FundamentalRecord
from private_quant.research.oliver_kell.price_action import DailyBar
from private_quant.research.oliver_kell.universe import SecurityState
from private_quant.strategies.oliver_kell_cpa import OliverKellCnConfig, evaluate_symbol, load_default_config


class StrategyCompositionTests(unittest.TestCase):
    def _bars(self):
        closes = [10.0, 9.7, 9.5, 9.6, 9.8, 10.0, 10.4]
        volumes = [100, 100, 100, 100, 100, 100, 180]
        start = date(2024, 1, 1)
        return [DailyBar("600001.SH", start + timedelta(days=i), c * 0.99, c * 1.01, c * 0.98, c, v) for i, (c, v) in enumerate(zip(closes, volumes))]

    def _fundamental(self, eligible=True):
        return FundamentalRecord(
            ticker="600001.SH", report_period=date(2023, 9, 30), announcement_date=date(2023, 10, 30),
            available_from=date(2023, 10, 30), revenue_yoy=35.0 if eligible else 5.0,
            net_profit_yoy=40.0, roe=10.0, eps=0.5, float_market_cap_rmb=10_000_000_000.0,
        )

    def _state(self):
        return SecurityState("600001.SH", date(2024, 1, 7), date(2010, 1, 1), False, False, 50_000_000.0)

    def test_default_variant_requires_fundamentals(self):
        cfg = OliverKellCnConfig(wedge_lookback=3, fast_ema_period=3)
        signals = evaluate_symbol(self._bars(), [self._fundamental(False)], self._state(), date(2024, 1, 7), cfg)
        self.assertEqual(signals, [])

    def test_technical_only_bypasses_fundamental_screen(self):
        cfg = OliverKellCnConfig(variant="technical_only", wedge_lookback=3, fast_ema_period=3)
        signals = evaluate_symbol(self._bars(), [self._fundamental(False)], self._state(), date(2024, 1, 7), cfg)
        self.assertTrue(any(signal.signal_type == "WEDGE_POP" for signal in signals))

    def test_market_regime_is_not_a_v1_config_option(self):
        self.assertNotIn("market_regime", OliverKellCnConfig.__dataclass_fields__)

    def test_config_loader_reads_frozen_json(self):
        payload = {"variant": "fundamental_plus_cpa", "max_positions": 10, "development_start": "2015-01-01", "development_end": "2021-12-31", "oos_start": "2022-01-01"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            cfg = load_default_config(path)
        self.assertEqual(cfg.max_positions, 10)
        self.assertEqual(cfg.oos_start, date(2022, 1, 1))


if __name__ == "__main__":
    unittest.main()
