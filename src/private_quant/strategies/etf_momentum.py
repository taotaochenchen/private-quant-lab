"""Simple monthly ETF momentum ranking with a long-term trend filter."""

from dataclasses import dataclass
from datetime import date
from collections.abc import Mapping, Sequence

from private_quant.data import PriceBar


@dataclass(frozen=True, slots=True)
class MomentumConfig:
    """Parameters for the V1 ETF momentum strategy.

    Defaults approximate 6 months, 12 months and a 200-trading-day trend filter.
    """

    lookback_6m: int = 126
    lookback_12m: int = 252
    trend_window: int = 200
    top_n: int = 3

    def __post_init__(self) -> None:
        if min(self.lookback_6m, self.lookback_12m, self.trend_window, self.top_n) <= 0:
            raise ValueError("momentum configuration values must be positive")
        if self.lookback_6m >= self.lookback_12m:
            raise ValueError("6-month lookback must be shorter than 12-month lookback")


@dataclass(frozen=True, slots=True)
class MomentumCandidate:
    symbol: str
    score: float
    return_6m: float
    return_12m: float
    trend_average: float
    latest_price: float


def _bars_available_as_of(bars: Sequence[PriceBar], as_of: date) -> list[PriceBar]:
    return sorted(
        (bar for bar in bars if bar.trading_date <= as_of),
        key=lambda bar: bar.trading_date,
    )


def select_etfs(
    histories: Mapping[str, Sequence[PriceBar]],
    *,
    as_of: date,
    config: MomentumConfig | None = None,
) -> tuple[MomentumCandidate, ...]:
    """Rank eligible ETFs using only prices available on or before ``as_of``.

    Score is the equal-weight average of 6-month and 12-month total return.
    An ETF is eligible only when its latest adjusted close is above its trend
    moving average. Ties are deterministic by symbol.
    """

    cfg = config or MomentumConfig()
    required_points = max(cfg.lookback_12m + 1, cfg.trend_window)
    candidates: list[MomentumCandidate] = []

    for raw_symbol, raw_bars in histories.items():
        symbol = raw_symbol.strip().upper()
        if not symbol:
            continue
        bars = _bars_available_as_of(raw_bars, as_of)
        if len(bars) < required_points:
            continue

        latest = bars[-1].adjusted_close
        price_6m = bars[-1 - cfg.lookback_6m].adjusted_close
        price_12m = bars[-1 - cfg.lookback_12m].adjusted_close
        trend_average = sum(bar.adjusted_close for bar in bars[-cfg.trend_window :]) / cfg.trend_window

        if latest <= trend_average:
            continue

        return_6m = latest / price_6m - 1.0
        return_12m = latest / price_12m - 1.0
        score = (return_6m + return_12m) / 2.0
        candidates.append(
            MomentumCandidate(
                symbol=symbol,
                score=score,
                return_6m=return_6m,
                return_12m=return_12m,
                trend_average=trend_average,
                latest_price=latest,
            )
        )

    candidates.sort(key=lambda item: (-item.score, item.symbol))
    return tuple(candidates[: cfg.top_n])
