import unittest
from datetime import date

from private_quant.backtest.oliver_kell_cpa import (
    ExecutionRules,
    MarketState,
    OrderIntent,
    Position,
    compute_backtest_metrics,
    simulate_order,
)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.rules = ExecutionRules(
            commission_rate=0.0003,
            minimum_commission=5.0,
            stamp_duty_rate=0.0005,
            slippage_bps=10.0,
            board_lot=100,
        )
        self.market = MarketState(
            ticker="600001.SH",
            date=date(2024, 1, 2),
            reference_price=10.0,
            is_suspended=False,
            buy_blocked_by_limit=False,
            sell_blocked_by_limit=False,
        )

    def test_buy_rounds_down_to_board_lot(self):
        order = OrderIntent("600001.SH", date(2024, 1, 2), "BUY", 155, 10.0)
        fill = simulate_order(order, self.market, self.rules, cash=10_000.0, position=None)
        self.assertIsNotNone(fill)
        self.assertEqual(fill.quantity, 100)

    def test_buy_is_blocked_when_limit_up_or_suspended(self):
        order = OrderIntent("600001.SH", date(2024, 1, 2), "BUY", 100, 10.0)
        limit_up = MarketState("600001.SH", date(2024, 1, 2), 10.0, False, True, False)
        suspended = MarketState("600001.SH", date(2024, 1, 2), 10.0, True, False, False)
        self.assertIsNone(simulate_order(order, limit_up, self.rules, 10_000.0, None))
        self.assertIsNone(simulate_order(order, suspended, self.rules, 10_000.0, None))

    def test_t_plus_one_blocks_same_day_sell(self):
        position = Position("600001.SH", 100, 10.0, date(2024, 1, 2))
        order = OrderIntent("600001.SH", date(2024, 1, 2), "SELL", 100, 9.5)
        self.assertIsNone(simulate_order(order, self.market, self.rules, 0.0, position))

    def test_sell_is_blocked_when_limit_down(self):
        position = Position("600001.SH", 100, 10.0, date(2024, 1, 1))
        order = OrderIntent("600001.SH", date(2024, 1, 2), "SELL", 100, 9.5)
        limit_down = MarketState("600001.SH", date(2024, 1, 2), 9.5, False, False, True)
        self.assertIsNone(simulate_order(order, limit_down, self.rules, 0.0, position))

    def test_sell_cost_includes_commission_and_stamp_duty(self):
        position = Position("600001.SH", 100, 10.0, date(2024, 1, 1))
        order = OrderIntent("600001.SH", date(2024, 1, 2), "SELL", 100, 10.0)
        fill = simulate_order(order, self.market, self.rules, 0.0, position)
        self.assertIsNotNone(fill)
        self.assertGreater(fill.fees, 5.0)


class MetricsTests(unittest.TestCase):
    def test_metrics_are_deterministic(self):
        metrics = compute_backtest_metrics(
            equity_curve=[100.0, 110.0, 99.0, 120.0],
            trade_returns=[0.10, -0.05, 0.20],
            annualization_periods=252,
            periods_per_year=252,
            turnover=1.5,
            benchmark_start=100.0,
            benchmark_end=110.0,
        )
        self.assertAlmostEqual(metrics.total_return, 0.20)
        self.assertAlmostEqual(metrics.max_drawdown, -0.10)
        self.assertEqual(metrics.win_rate, 2 / 3)
        self.assertGreater(metrics.profit_factor, 0.0)
        self.assertAlmostEqual(metrics.benchmark_return, 0.10)
        self.assertAlmostEqual(metrics.excess_return, 0.10)


if __name__ == "__main__":
    unittest.main()
