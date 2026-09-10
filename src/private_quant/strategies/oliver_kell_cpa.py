from dataclasses import dataclass, fields
from datetime import date
import json
from pathlib import Path
from typing import Iterable, Sequence

from private_quant.research.oliver_kell.fundamentals import (
    FundamentalRecord,
    FundamentalThresholds,
    is_fundamentally_eligible,
)
from private_quant.research.oliver_kell.price_action import (
    CpaSignal,
    DailyBar,
    detect_base_n_break,
    detect_ema_crossback,
    detect_wedge_pop,
)
from private_quant.research.oliver_kell.universe import SecurityState, UniverseRules, is_universe_eligible


@dataclass(frozen=True)
class OliverKellCnConfig:
    variant: str = "fundamental_plus_cpa"
    min_revenue_yoy: float = 30.0
    min_net_profit_yoy: float = 30.0
    min_roe: float = 8.0
    min_eps_exclusive: float = 0.0
    min_float_market_cap_rmb: float = 5_000_000_000.0
    max_float_market_cap_rmb: float = 50_000_000_000.0
    ipo_seasoning_days: int = 60
    min_average_daily_turnover_rmb: float = 20_000_000.0
    fast_ema_period: int = 10
    slow_ema_period: int = 20
    sma_50_period: int = 50
    sma_200_period: int = 200
    wedge_lookback: int = 5
    base_lookback: int = 10
    volume_multiplier: float = 1.2
    enable_base_n_break: bool = False
    max_positions: int = 10
    development_start: date = date(2015, 1, 1)
    development_end: date = date(2021, 12, 31)
    oos_start: date = date(2022, 1, 1)


def _thresholds(config: OliverKellCnConfig) -> FundamentalThresholds:
    return FundamentalThresholds(
        min_revenue_yoy=config.min_revenue_yoy,
        min_net_profit_yoy=config.min_net_profit_yoy,
        min_roe=config.min_roe,
        min_eps_exclusive=config.min_eps_exclusive,
        min_float_market_cap_rmb=config.min_float_market_cap_rmb,
        max_float_market_cap_rmb=config.max_float_market_cap_rmb,
    )


def _universe_rules(config: OliverKellCnConfig) -> UniverseRules:
    return UniverseRules(
        ipo_seasoning_days=config.ipo_seasoning_days,
        min_average_daily_turnover_rmb=config.min_average_daily_turnover_rmb,
    )


def evaluate_symbol(
    bars: Sequence[DailyBar],
    fundamental_records: Iterable[FundamentalRecord],
    security_state: SecurityState,
    decision_date: date,
    config: OliverKellCnConfig | None = None,
) -> list[CpaSignal]:
    config = config or OliverKellCnConfig()
    if not bars or bars[-1].date > decision_date:
        return []
    if not is_universe_eligible(security_state, decision_date, _universe_rules(config)):
        return []
    if config.variant != "technical_only" and not is_fundamentally_eligible(
        fundamental_records, decision_date, _thresholds(config)
    ):
        return []

    signals: list[CpaSignal] = []
    wedge = detect_wedge_pop(
        bars,
        lookback=config.wedge_lookback,
        ema_period=config.fast_ema_period,
        volume_multiplier=config.volume_multiplier,
    )
    if wedge:
        signals.append(wedge)
    crossback = detect_ema_crossback(
        bars,
        ema_period=config.fast_ema_period,
        volume_multiplier=1.0,
    )
    if crossback:
        signals.append(crossback)
    if config.enable_base_n_break:
        base_break = detect_base_n_break(
            bars,
            base_lookback=config.base_lookback,
            volume_multiplier=config.volume_multiplier,
        )
        if base_break:
            signals.append(base_break)
    return signals


def load_default_config(path: str | Path) -> OliverKellCnConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    date_fields = {"development_start", "development_end", "oos_start"}
    allowed = {field.name for field in fields(OliverKellCnConfig)}
    kwargs = {key: value for key, value in raw.items() if key in allowed}
    for key in date_fields & kwargs.keys():
        kwargs[key] = date.fromisoformat(kwargs[key])
    return OliverKellCnConfig(**kwargs)
