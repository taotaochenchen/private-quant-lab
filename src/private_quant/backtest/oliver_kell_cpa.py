from dataclasses import dataclass
from datetime import date
import math
import statistics
from typing import Optional, Sequence


@dataclass(frozen=True)
class ExecutionRules:
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    stamp_duty_rate: float = 0.0005
    slippage_bps: float = 10.0
    board_lot: int = 100


@dataclass(frozen=True)
class MarketState:
    ticker: str
    date: date
    reference_price: float
    is_suspended: bool
    buy_blocked_by_limit: bool
    sell_blocked_by_limit: bool


@dataclass(frozen=True)
class OrderIntent:
    ticker: str
    date: date
    side: str
    quantity: int
    reference_price: float


@dataclass(frozen=True)
class Fill:
    ticker: str
    date: date
    side: str
    quantity: int
    price: float
    fees: float
    notional: float


@dataclass(frozen=True)
class Position:
    ticker: str
    quantity: int
    average_price: float
    acquired_date: date


@dataclass(frozen=True)
class PortfolioSnapshot:
    date: date
    cash: float
    equity: float
    positions_value: float


@dataclass(frozen=True)
class BacktestMetrics:
    total_return: float
    cagr: float
    max_drawdown: float
    sharpe: float
    calmar: float
    win_rate: float
    profit_factor: float
    average_winner: float
    average_loser: float
    trades_per_year: float
    turnover: float
    benchmark_return: float
    excess_return: float


def _round_to_lot(quantity: int, board_lot: int) -> int:
    if quantity <= 0 or board_lot <= 0:
        return 0
    return (quantity // board_lot) * board_lot


def simulate_order(
    order: OrderIntent,
    market: MarketState,
    rules: ExecutionRules,
    cash: float,
    position: Optional[Position],
) -> Optional[Fill]:
    side = order.side.upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    if order.ticker != market.ticker or order.date != market.date:
        return None
    if market.is_suspended or market.reference_price <= 0:
        return None

    quantity = _round_to_lot(order.quantity, rules.board_lot)
    if quantity <= 0:
        return None
    slip = rules.slippage_bps / 10_000.0

    if side == "BUY":
        if market.buy_blocked_by_limit:
            return None
        price = market.reference_price * (1.0 + slip)
        notional = price * quantity
        fees = max(rules.minimum_commission, notional * rules.commission_rate)
        while quantity > 0 and notional + fees > cash:
            quantity -= rules.board_lot
            if quantity <= 0:
                return None
            notional = price * quantity
            fees = max(rules.minimum_commission, notional * rules.commission_rate)
        return Fill(order.ticker, order.date, side, quantity, price, fees, notional)

    if position is None or position.ticker != order.ticker or position.quantity <= 0:
        return None
    if position.acquired_date >= order.date:
        return None
    if market.sell_blocked_by_limit:
        return None
    quantity = min(quantity, _round_to_lot(position.quantity, rules.board_lot))
    if quantity <= 0:
        return None
    price = market.reference_price * (1.0 - slip)
    notional = price * quantity
    fees = max(rules.minimum_commission, notional * rules.commission_rate) + notional * rules.stamp_duty_rate
    return Fill(order.ticker, order.date, side, quantity, price, fees, notional)


def compute_backtest_metrics(
    *,
    equity_curve: Sequence[float],
    trade_returns: Sequence[float],
    annualization_periods: int = 252,
    periods_per_year: int = 252,
    turnover: float = 0.0,
    benchmark_start: float = 0.0,
    benchmark_end: float = 0.0,
) -> BacktestMetrics:
    if not equity_curve or equity_curve[0] <= 0:
        raise ValueError("equity_curve must start with a positive value")
    total_return = equity_curve[-1] / equity_curve[0] - 1.0
    years = max((len(equity_curve) - 1) / float(annualization_periods), 1.0 / annualization_periods)
    cagr = (equity_curve[-1] / equity_curve[0]) ** (1.0 / years) - 1.0 if equity_curve[-1] > 0 else -1.0

    peak = equity_curve[0]
    max_drawdown = 0.0
    period_returns = []
    for previous, current in zip(equity_curve, equity_curve[1:]):
        if previous > 0:
            period_returns.append(current / previous - 1.0)
        peak = max(peak, current)
        if peak > 0:
            max_drawdown = min(max_drawdown, current / peak - 1.0)

    if len(period_returns) >= 2:
        std = statistics.stdev(period_returns)
        sharpe = (statistics.mean(period_returns) / std) * math.sqrt(periods_per_year) if std > 0 else 0.0
    else:
        sharpe = 0.0
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0 else 0.0

    winners = [value for value in trade_returns if value > 0]
    losers = [value for value in trade_returns if value < 0]
    win_rate = len(winners) / len(trade_returns) if trade_returns else 0.0
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit > 0 else 0.0)
    average_winner = statistics.mean(winners) if winners else 0.0
    average_loser = statistics.mean(losers) if losers else 0.0
    trades_per_year = len(trade_returns) / years
    benchmark_return = benchmark_end / benchmark_start - 1.0 if benchmark_start > 0 else 0.0

    return BacktestMetrics(
        total_return=total_return,
        cagr=cagr,
        max_drawdown=max_drawdown,
        sharpe=sharpe,
        calmar=calmar,
        win_rate=win_rate,
        profit_factor=profit_factor,
        average_winner=average_winner,
        average_loser=average_loser,
        trades_per_year=trades_per_year,
        turnover=turnover,
        benchmark_return=benchmark_return,
        excess_return=total_return - benchmark_return,
    )
