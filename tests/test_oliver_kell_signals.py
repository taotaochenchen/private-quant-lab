import unittest
from datetime import date, timedelta

from private_quant.research.oliver_kell.price_action import (
    DailyBar,
    detect_base_n_break,
    detect_ema_crossback,
    detect_wedge_pop,
    ema,
    sma,
)


def make_bars(closes, volumes=None):
    start = date(2024, 1, 1)
    volumes = volumes or [1_000_000.0] * len(closes)
    bars = []
    for i, (close, volume) in enumerate(zip(closes, volumes)):
        bars.append(
            DailyBar(
                ticker="600001.SH",
                date=start + timedelta(days=i),
                open=close * 0.99,
                high=close * 1.01,
                low=close * 0.98,
                close=float(close),
                volume=float(volume),
            )
        )
    return bars


class IndicatorTests(unittest.TestCase):
    def test_sma_waits_for_full_window(self):
        self.assertEqual(sma([1, 2, 3, 4], 3), [None, None, 2.0, 3.0])

    def test_ema_is_seeded_from_first_value(self):
        values = ema([10, 12, 14], 2)
        self.assertEqual(values[0], 10.0)
        self.assertAlmostEqual(values[1], 11.3333333333, places=6)
        self.assertAlmostEqual(values[2], 13.1111111111, places=6)


class SignalTests(unittest.TestCase):
    def test_wedge_pop_emits_on_breakout_with_volume(self):
        closes = [10.0, 9.7, 9.5, 9.6, 9.8, 10.0, 10.4]
        volumes = [100, 100, 100, 100, 100, 100, 180]
        signal = detect_wedge_pop(make_bars(closes, volumes), lookback=3, ema_period=3, volume_multiplier=1.2)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.signal_type, "WEDGE_POP")
        self.assertEqual(signal.date, make_bars(closes, volumes)[-1].date)

    def test_wedge_pop_ignores_future_bars(self):
        prefix = make_bars([10.0, 9.7, 9.5, 9.6, 9.8, 10.0, 10.4], [100, 100, 100, 100, 100, 100, 180])
        with_future = prefix + make_bars([30.0], [9999])
        # Rewrite the extra bar date so sequence remains strictly increasing.
        with_future[-1] = DailyBar(
            ticker="600001.SH",
            date=prefix[-1].date + timedelta(days=1),
            open=29.0,
            high=31.0,
            low=28.0,
            close=30.0,
            volume=9999.0,
        )
        signal_prefix = detect_wedge_pop(prefix, lookback=3, ema_period=3, volume_multiplier=1.2)
        signal_as_of_prefix = detect_wedge_pop(with_future[:-1], lookback=3, ema_period=3, volume_multiplier=1.2)
        self.assertEqual(signal_prefix, signal_as_of_prefix)

    def test_ema_crossback_requires_pullback_then_reclaim(self):
        bars = make_bars([10.0, 10.5, 11.0, 11.5, 11.2, 11.6], [100, 110, 120, 130, 100, 150])
        signal = detect_ema_crossback(bars, ema_period=3, tolerance=0.03, volume_multiplier=1.0)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.signal_type, "EMA_CROSSBACK")

    def test_base_n_break_breaks_recent_range(self):
        bars = make_bars([10.0, 10.2, 10.1, 10.15, 10.05, 10.2, 10.8], [100, 100, 100, 100, 100, 100, 170])
        signal = detect_base_n_break(bars, base_lookback=5, max_base_range_pct=0.05, volume_multiplier=1.2)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.signal_type, "BASE_N_BREAK")


if __name__ == "__main__":
    unittest.main()
