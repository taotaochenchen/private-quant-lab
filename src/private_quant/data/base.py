"""Abstract provider interfaces. Vendor adapters implement these contracts."""

from abc import ABC, abstractmethod
from datetime import date
from typing import Sequence

from .models import BalanceSheetSnapshot, PriceBar


class MarketDataProvider(ABC):
    """Contract for historical end-of-day price data."""

    @abstractmethod
    def get_price_history(self, symbol: str, start: date, end: date) -> Sequence[PriceBar]:
        """Return bars ordered from oldest to newest."""


class FundamentalsProvider(ABC):
    """Contract for filing-aware balance-sheet history."""

    @abstractmethod
    def get_balance_sheet_history(self, symbol: str, start: date, end: date) -> Sequence[BalanceSheetSnapshot]:
        """Return snapshots whose filing date is within the requested range."""
