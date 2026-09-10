from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional


@dataclass(frozen=True)
class FundamentalRecord:
    ticker: str
    report_period: date
    announcement_date: date
    available_from: date
    revenue_yoy: float
    net_profit_yoy: float
    roe: float
    eps: float
    float_market_cap_rmb: float


@dataclass(frozen=True)
class FundamentalThresholds:
    min_revenue_yoy: float = 30.0
    min_net_profit_yoy: float = 30.0
    min_roe: float = 8.0
    min_eps_exclusive: float = 0.0
    min_float_market_cap_rmb: float = 5_000_000_000.0
    max_float_market_cap_rmb: float = 50_000_000_000.0


def latest_available_record(
    records: Iterable[FundamentalRecord], decision_date: date
) -> Optional[FundamentalRecord]:
    visible = [record for record in records if record.available_from <= decision_date]
    if not visible:
        return None
    return max(visible, key=lambda record: (record.available_from, record.report_period))


def passes_fundamental_screen(
    record: FundamentalRecord, thresholds: FundamentalThresholds
) -> bool:
    return (
        record.revenue_yoy >= thresholds.min_revenue_yoy
        and record.net_profit_yoy >= thresholds.min_net_profit_yoy
        and record.roe >= thresholds.min_roe
        and record.eps > thresholds.min_eps_exclusive
        and record.float_market_cap_rmb >= thresholds.min_float_market_cap_rmb
        and record.float_market_cap_rmb <= thresholds.max_float_market_cap_rmb
    )


def is_fundamentally_eligible(
    records: Iterable[FundamentalRecord],
    decision_date: date,
    thresholds: FundamentalThresholds | None = None,
) -> bool:
    thresholds = thresholds or FundamentalThresholds()
    record = latest_available_record(records, decision_date)
    return record is not None and passes_fundamental_screen(record, thresholds)
