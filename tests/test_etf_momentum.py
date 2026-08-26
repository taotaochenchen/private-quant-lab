from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.data import PriceBar
from private_quant.strategies.etf_momentum import MomentumConfig, select_etfs
from private_quant.backtest.etf_momentum import (
    run_buy_and_hold_benchmark,
    run_etf_momentum_backtest,
)


def make_bars(symbol: str, closes: list[float], start: date = date(2024, 1, 1)) -> list[PriceBar]:
    bars: list[PriceBar] = []
    current = start
    for close in closes:
        bars.append(
            PriceBar(
                symbol=symbol,
                trading_date=current,
                open=close,
                high=close,
                low=close,
                close=close,
                adjusted_close=close,
                volume=1_000_000,
            )
        )
        current += timedelta(days=1)
    return bars


class MomentumSelectionTests(unittest.TestCase):
    def test_selects_highest_momentum_asset_that_is_above_trend(self) -> None:
        config = MomentumConfig(lookback_6m=3, lookback_12m=5, trend_window=4, top_n=1)
        histories = {
            "AAA": make_bars("AAA", [10, 10, 10, 11, 12, 13]),
            "BBB": make_bars("BBB", [10, 10, 10, 12, 14, 16]),
            "CCC": make_bars("CCC", [10, 10, 10, 9, 8, 7]),
        }

        selected = select_etfs(histories, as_of=date(2024, 1, 6), config=config)

        self.assertEqual([item.symbol for item in selected], ["BBB"])
        self.assertGreater(selected[0].score, 0)

    def test_ignores_prices_after_as_of_date(self) -> None:
        config = MomentumConfig(lookback_6m=2, lookback_12m=3, trend_window=3, top_n=1)
        aaa = make_bars("AAA", [10, 10, 11, 12, 13])
        bbb = make_bars("BBB", [10, 10, 11, 12, 100])
        histories = {"AAA": aaa, "BBB": bbb}

        selected = select_etfs(histories, as_of=date(2024, 1, 4), config=config)

        self.assertEqual([item.symbol for item in selected], ["AAA"])

    def test_returns_cash_when_no_asset_passes_trend_filter(self) -> None:
        config = MomentumConfig(lookback_6m=2, lookback_12m=3, trend_window=3, top_n=2)
        histories = {
            "AAA": make_bars("AAA", [10, 9, 8, 7]),
            "BBB": make_bars("BBB", [20, 18, 16, 14]),
        }

        selected = select_etfs(histories, as_of=date(2024, 1, 4), config=config)

        self.assertEqual(selected, ())


class MomentumBacktestTests(unittest.TestCase):
    def test_backtest_starts_with_requested_virtual_capital_and_preserves_cash_without_history(self) -> None:
        config = MomentumConfig(lookback_6m=3, lookback_12m=5, trend_window=4, top_n=1)
        histories = {"AAA": make_bars("AAA", [10, 11, 12])}

        result = run_etf_momentum_backtest(
            histories,
            initial_capital=100_000.0,
            config=config,
            transaction_cost_bps=5.0,
        )

        self.assertEqual(result.initial_capital, 100_000.0)
        self.assertAlmostEqual(result.final_value, 100_000.0)
        self.assertEqual(result.trades, ())

    def test_transaction_costs_reduce_portfolio_value_on_rebalance(self) -> None:
        config = MomentumConfig(lookback_6m=2, lookback_12m=3, trend_window=3, top_n=1)
        closes = [10, 10, 11, 12, 13, 14, 15, 16]
        histories = {"AAA": make_bars("AAA", closes, start=date(2024, 1, 28))}

        no_cost = run_etf_momentum_backtest(
            histories,
            initial_capital=100_000.0,
            config=config,
            transaction_cost_bps=0.0,
        )
        with_cost = run_etf_momentum_backtest(
            histories,
            initial_capital=100_000.0,
            config=config,
            transaction_cost_bps=10.0,
        )

        self.assertGreater(len(no_cost.trades), 0)
        self.assertLess(with_cost.final_value, no_cost.final_value)
        self.assertGreater(with_cost.total_transaction_cost, 0.0)
        self.assertGreaterEqual(with_cost.turnover, 0.0)

    def test_buy_and_hold_benchmark_tracks_adjusted_price_return(self) -> None:
        bars = make_bars("SPY", [100, 110, 120, 150])

        result = run_buy_and_hold_benchmark(bars, initial_capital=100_000.0)

        self.assertAlmostEqual(result.final_value, 150_000.0)
        self.assertGreater(result.metrics.cagr, 0.0)
        self.assertEqual(result.trades, ())


if __name__ == "__main__":
    unittest.main()
