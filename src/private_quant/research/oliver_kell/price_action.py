from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class DailyBar:
    ticker: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class CpaSignal:
    ticker: str
    date: date
    signal_type: str
    signal_price: float
    stop_price: float
    reason: str


def sma(values: Sequence[float], period: int) -> list[Optional[float]]:
    if period <= 0:
        raise ValueError("period must be positive")
    result: list[Optional[float]] = []
    for i in range(len(values)):
        if i + 1 < period:
            result.append(None)
        else:
            window = values[i + 1 - period : i + 1]
            result.append(sum(window) / period)
    return result


def ema(values: Sequence[float], period: int) -> list[Optional[float]]:
    if period <= 0:
        raise ValueError("period must be positive")
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    result: list[Optional[float]] = [float(values[0])]
    for value in values[1:]:
        previous = result[-1]
        assert previous is not None
        result.append(alpha * float(value) + (1.0 - alpha) * previous)
    return result


def relative_strength(close: Sequence[float], benchmark_close: Sequence[float]) -> list[Optional[float]]:
    if len(close) != len(benchmark_close):
        raise ValueError("close and benchmark_close must have equal length")
    result: list[Optional[float]] = []
    for stock, benchmark in zip(close, benchmark_close):
        result.append(None if benchmark <= 0 else float(stock) / float(benchmark))
    return result


def _average(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def detect_wedge_pop(
    bars: Sequence[DailyBar],
    *,
    lookback: int = 5,
    ema_period: int = 10,
    volume_multiplier: float = 1.2,
) -> Optional[CpaSignal]:
    if len(bars) < max(lookback + 1, ema_period + 1):
        return None
    prior = bars[-lookback - 1 : -1]
    current = bars[-1]
    closes = [bar.close for bar in bars]
    current_ema = ema(closes, ema_period)[-1]
    if current_ema is None:
        return None
    breakout = current.close > max(bar.high for bar in prior)
    above_ema = current.close > current_ema
    volume_ok = current.volume >= _average(bar.volume for bar in prior) * volume_multiplier
    recent_low = min(bar.low for bar in prior)
    had_pullback = recent_low < max(bar.high for bar in prior[:-1] or prior)
    if breakout and above_ema and volume_ok and had_pullback:
        return CpaSignal(
            ticker=current.ticker,
            date=current.date,
            signal_type="WEDGE_POP",
            signal_price=current.close,
            stop_price=recent_low,
            reason=f"close broke {lookback}-bar high above EMA{ema_period} with volume confirmation",
        )
    return None


def detect_ema_crossback(
    bars: Sequence[DailyBar],
    *,
    ema_period: int = 10,
    tolerance: float = 0.02,
    volume_multiplier: float = 1.0,
) -> Optional[CpaSignal]:
    if len(bars) < max(ema_period + 2, 3):
        return None
    closes = [bar.close for bar in bars]
    ema_values = ema(closes, ema_period)
    previous_ema = ema_values[-2]
    current_ema = ema_values[-1]
    assert previous_ema is not None and current_ema is not None
    previous = bars[-2]
    current = bars[-1]
    prior_volume = _average(bar.volume for bar in bars[-6:-1])
    near_ema = previous.low <= previous_ema * (1.0 + tolerance) and previous.close >= previous_ema * (1.0 - tolerance)
    reclaimed = current.close > current_ema and current.close > previous.close
    trend_ok = current_ema >= previous_ema
    volume_ok = prior_volume <= 0 or current.volume >= prior_volume * volume_multiplier
    if near_ema and reclaimed and trend_ok and volume_ok:
        return CpaSignal(
            ticker=current.ticker,
            date=current.date,
            signal_type="EMA_CROSSBACK",
            signal_price=current.close,
            stop_price=min(previous.low, current.low),
            reason=f"pullback held near EMA{ema_period} and price reclaimed it with confirmation",
        )
    return None


def detect_base_n_break(
    bars: Sequence[DailyBar],
    *,
    base_lookback: int = 10,
    max_base_range_pct: float = 0.08,
    volume_multiplier: float = 1.2,
) -> Optional[CpaSignal]:
    if len(bars) < base_lookback + 1:
        return None
    base = bars[-base_lookback - 1 : -1]
    current = bars[-1]
    base_high = max(bar.high for bar in base)
    base_low = min(bar.low for bar in base)
    if base_low <= 0:
        return None
    base_range_pct = (base_high - base_low) / base_low
    volume_ok = current.volume >= _average(bar.volume for bar in base) * volume_multiplier
    if base_range_pct <= max_base_range_pct and current.close > base_high and volume_ok:
        return CpaSignal(
            ticker=current.ticker,
            date=current.date,
            signal_type="BASE_N_BREAK",
            signal_price=current.close,
            stop_price=base_low,
            reason=f"close broke a {base_lookback}-bar base with volume confirmation",
        )
    return None
