from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SecurityState:
    ticker: str
    as_of: date
    listing_date: date
    is_st: bool
    is_suspended: bool
    average_daily_turnover_rmb: float


@dataclass(frozen=True)
class UniverseRules:
    ipo_seasoning_days: int = 60
    min_average_daily_turnover_rmb: float = 20_000_000.0


def is_universe_eligible(state: SecurityState, decision_date: date, rules: UniverseRules) -> bool:
    if state.as_of > decision_date:
        return False
    if state.is_st or state.is_suspended:
        return False
    if (decision_date - state.listing_date).days < rules.ipo_seasoning_days:
        return False
    if state.average_daily_turnover_rmb < rules.min_average_daily_turnover_rmb:
        return False
    return True
