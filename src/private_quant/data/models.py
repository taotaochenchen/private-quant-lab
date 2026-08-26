"""Internal data models used across provider adapters and strategies."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class PriceBar:
    symbol: str
    trading_date: date
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: int

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if min(self.open, self.high, self.low, self.close, self.adjusted_close) <= 0:
            raise ValueError("price fields must be positive")
        if self.low > self.high:
            raise ValueError("low cannot exceed high")
        if self.volume < 0:
            raise ValueError("volume cannot be negative")


@dataclass(frozen=True, slots=True)
class BalanceSheetSnapshot:
    symbol: str
    period_end: date
    filed_date: date
    total_assets: float
    total_liabilities: float
    total_debt: float | None = None
    currency: str = "USD"

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if self.filed_date < self.period_end:
            raise ValueError("filed_date cannot be before period_end")
        if not self.currency.strip():
            raise ValueError("currency must not be empty")
