"""Backtest engine for the V1 monthly ETF momentum strategy."""

from dataclasses import dataclass
from datetime import date
from collections.abc import Mapping, Sequence
from math import sqrt
from statistics import fmean, pstdev

from private_quant.data import PriceBar
from private_quant.strategies.etf_momentum import MomentumConfig, select_etfs


@dataclass(frozen=True, slots=True)
class EquityPoint:
    trading_date: date
    value: float


@dataclass(frozen=True, slots=True)
class Trade:
    trading_date: date
    symbol: str
    notional_change: float
    transaction_cost: float


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    cagr: float
    max_drawdown: float
    annualized_volatility: float
    sharpe: float


@dataclass(frozen=True, slots=True)
class BacktestResult:
    initial_capital: float
    final_value: float
    total_transaction_cost: float
    turnover: float
    metrics: BacktestMetrics
    equity_curve: tuple[EquityPoint, ...]
    trades: tuple[Trade, ...]


def _build_price_maps(
    histories: Mapping[str, Sequence[PriceBar]],
) -> tuple[list[date], dict[str, dict[date, float]]]:
    all_dates: set[date] = set()
    prices: dict[str, dict[date, float]] = {}
    for raw_symbol, bars in histories.items():
        symbol = raw_symbol.strip().upper()
        if not symbol:
            continue
        symbol_prices: dict[date, float] = {}
        for bar in bars:
            symbol_prices[bar.trading_date] = bar.adjusted_close
            all_dates.add(bar.trading_date)
        prices[symbol] = symbol_prices
    return sorted(all_dates), prices


def _latest_price_on_or_before(
    prices: Mapping[date, float], target_date: date
) -> float | None:
    eligible = [day for day in prices if day <= target_date]
    if not eligible:
        return None
    return prices[max(eligible)]


def _portfolio_value(
    cash: float,
    holdings: Mapping[str, float],
    prices: Mapping[str, Mapping[date, float]],
    trading_date: date,
) -> float:
    value = cash
    for symbol, units in holdings.items():
        price = _latest_price_on_or_before(prices[symbol], trading_date)
        if price is None:
            continue
        value += units * price
    return value


def _metrics(equity_curve: Sequence[EquityPoint]) -> BacktestMetrics:
    if not equity_curve:
        return BacktestMetrics(0.0, 0.0, 0.0, 0.0)

    values = [point.value for point in equity_curve]
    peak = values[0]
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = min(max_drawdown, value / peak - 1.0)

    returns = [values[i] / values[i - 1] - 1.0 for i in range(1, len(values)) if values[i - 1] > 0]
    if len(returns) >= 2:
        daily_vol = pstdev(returns)
        annualized_volatility = daily_vol * sqrt(252.0)
        sharpe = (fmean(returns) / daily_vol * sqrt(252.0)) if daily_vol > 0 else 0.0
    else:
        annualized_volatility = 0.0
        sharpe = 0.0

    elapsed_days = (equity_curve[-1].trading_date - equity_curve[0].trading_date).days
    if elapsed_days > 0 and values[0] > 0 and values[-1] > 0:
        years = elapsed_days / 365.25
        cagr = (values[-1] / values[0]) ** (1.0 / years) - 1.0
    else:
        cagr = 0.0

    return BacktestMetrics(
        cagr=cagr,
        max_drawdown=max_drawdown,
        annualized_volatility=annualized_volatility,
        sharpe=sharpe,
    )


def run_etf_momentum_backtest(
    histories: Mapping[str, Sequence[PriceBar]],
    *,
    initial_capital: float = 100_000.0,
    config: MomentumConfig | None = None,
    transaction_cost_bps: float = 5.0,
) -> BacktestResult:
    """Run a monthly momentum backtest with next-month execution.

    The first price date of a new calendar month is the rebalance execution
    date. Selection uses only data through the previous available date, which
    prevents month-end look-ahead. Fractional units are allowed for research.
    """

    if initial_capital <= 0:
        raise ValueError("initial_capital must be positive")
    if transaction_cost_bps < 0:
        raise ValueError("transaction_cost_bps cannot be negative")

    cfg = config or MomentumConfig()
    dates, prices = _build_price_maps(histories)
    if not dates:
        return BacktestResult(
            initial_capital=initial_capital,
            final_value=initial_capital,
            total_transaction_cost=0.0,
            turnover=0.0,
            metrics=BacktestMetrics(0.0, 0.0, 0.0, 0.0),
            equity_curve=(),
            trades=(),
        )

    cash = initial_capital
    holdings: dict[str, float] = {}
    trades: list[Trade] = []
    equity_curve: list[EquityPoint] = []
    total_transaction_cost = 0.0
    total_traded_notional = 0.0
    cost_rate = transaction_cost_bps / 10_000.0

    previous_date: date | None = None
    for trading_date in dates:
        is_new_month = previous_date is not None and (
            trading_date.year,
            trading_date.month,
        ) != (previous_date.year, previous_date.month)

        if is_new_month:
            selected = select_etfs(histories, as_of=previous_date, config=cfg)
            selected_symbols = [candidate.symbol for candidate in selected]
            executable_symbols = [
                symbol for symbol in selected_symbols if trading_date in prices.get(symbol, {})
            ]

            pre_trade_value = _portfolio_value(cash, holdings, prices, trading_date)
            current_notional = {
                symbol: units * (_latest_price_on_or_before(prices[symbol], trading_date) or 0.0)
                for symbol, units in holdings.items()
            }

            if executable_symbols:
                investable = pre_trade_value
                target_notionals: dict[str, float] = {}
                gross_traded = 0.0
                for _ in range(4):
                    target_each = investable / len(executable_symbols)
                    target_notionals = {symbol: target_each for symbol in executable_symbols}
                    symbols = set(current_notional) | set(target_notionals)
                    gross_traded = sum(
                        abs(target_notionals.get(symbol, 0.0) - current_notional.get(symbol, 0.0))
                        for symbol in symbols
                    )
                    investable = max(0.0, pre_trade_value - gross_traded * cost_rate)
            else:
                target_notionals = {}
                gross_traded = sum(abs(value) for value in current_notional.values())

            transaction_cost = gross_traded * cost_rate
            total_transaction_cost += transaction_cost
            total_traded_notional += gross_traded

            symbols = sorted(set(current_notional) | set(target_notionals))
            new_holdings: dict[str, float] = {}
            for symbol in symbols:
                current_value = current_notional.get(symbol, 0.0)
                target_value = target_notionals.get(symbol, 0.0)
                change = target_value - current_value
                if abs(change) > 1e-9:
                    allocated_cost = (
                        transaction_cost * abs(change) / gross_traded if gross_traded > 0 else 0.0
                    )
                    trades.append(
                        Trade(
                            trading_date=trading_date,
                            symbol=symbol,
                            notional_change=change,
                            transaction_cost=allocated_cost,
                        )
                    )
                if target_value > 0:
                    price = prices[symbol][trading_date]
                    new_holdings[symbol] = target_value / price

            holdings = new_holdings
            cash = pre_trade_value - sum(target_notionals.values()) - transaction_cost
            if abs(cash) < 1e-8:
                cash = 0.0

        equity_curve.append(
            EquityPoint(
                trading_date=trading_date,
                value=_portfolio_value(cash, holdings, prices, trading_date),
            )
        )
        previous_date = trading_date

    final_value = equity_curve[-1].value if equity_curve else initial_capital
    average_equity = fmean(point.value for point in equity_curve) if equity_curve else initial_capital
    turnover = total_traded_notional / average_equity if average_equity > 0 else 0.0

    return BacktestResult(
        initial_capital=initial_capital,
        final_value=final_value,
        total_transaction_cost=total_transaction_cost,
        turnover=turnover,
        metrics=_metrics(equity_curve),
        equity_curve=tuple(equity_curve),
        trades=tuple(trades),
    )


def run_buy_and_hold_benchmark(
    bars: Sequence[PriceBar],
    *,
    initial_capital: float = 100_000.0,
) -> BacktestResult:
    """Return a frictionless adjusted-close buy-and-hold benchmark."""

    if initial_capital <= 0:
        raise ValueError("initial_capital must be positive")
    ordered = sorted(bars, key=lambda bar: bar.trading_date)
    if not ordered:
        return BacktestResult(
            initial_capital=initial_capital,
            final_value=initial_capital,
            total_transaction_cost=0.0,
            turnover=0.0,
            metrics=BacktestMetrics(0.0, 0.0, 0.0, 0.0),
            equity_curve=(),
            trades=(),
        )

    first_price = ordered[0].adjusted_close
    units = initial_capital / first_price
    curve = tuple(
        EquityPoint(bar.trading_date, units * bar.adjusted_close) for bar in ordered
    )
    return BacktestResult(
        initial_capital=initial_capital,
        final_value=curve[-1].value,
        total_transaction_cost=0.0,
        turnover=0.0,
        metrics=_metrics(curve),
        equity_curve=curve,
        trades=(),
    )
