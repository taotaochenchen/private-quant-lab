"""A股交易日历：如实的 T-1 推算，不臆造节假日。

T-1 指上一交易日，不是自然日昨天。本模块提供交易日判断与上一/下一交易日
推算，并如实标注数据来源与是否经过权威节假日数据校验。

默认 ``weekday_only`` 日历只处理周末，不含交易所节假日，因此 ``verified=False``；
只有从权威交易日列表（如 akshare）构造的日历才 ``verified=True``。调用方据此
决定是否把 ``calendar_verified`` 置真，不能把工作日减一当作已接入交易日历。
"""

from datetime import date, datetime, timedelta


def _coerce(value):
    """把 date/datetime/ISO 字符串统一成 date，不吞掉非法输入。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if " " in text:
            text = text.split(" ", 1)[0]
        return date.fromisoformat(text)
    raise TypeError("calendar expects a date, datetime, or ISO date string")


def _as_date(value):
    """宽松地把 akshare 等上游值（date/datetime/字符串/带时间戳文本）转成 date。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if " " in text:
        text = text.split(" ", 1)[0]
    return date.fromisoformat(text)


class TradingCalendar:
    """交易日历。要么持有一份权威交易日集合，要么退化为仅周末规则。"""

    def __init__(self, trading_dates=None, source="unavailable", verified=False, coverage=None):
        self._trading_dates = frozenset(trading_dates) if trading_dates is not None else None
        self.source = source
        self.verified = bool(verified)
        self.coverage = tuple(coverage) if coverage else None

    @classmethod
    def weekday_only(cls):
        """无节假日数据：仅周末视为非交易日，交易所节假日未知，verified=False。"""
        return cls(source="weekday_only_holidays_unknown", verified=False)

    @classmethod
    def from_trading_dates(cls, dates, source="trading_date_list"):
        """从权威交易日列表构造，verified=True，coverage 为列表范围。"""
        normalized = sorted({_as_date(value) for value in dates})
        coverage = (normalized[0], normalized[-1]) if normalized else None
        return cls(trading_dates=set(normalized), source=source, verified=True, coverage=coverage)

    @property
    def has_holiday_data(self):
        return self._trading_dates is not None

    def covers(self, value):
        """查询日期是否落在日历覆盖范围内；无 coverage 的 weekday_only 恒为 True。"""
        if self.coverage is None:
            return True
        return self.coverage[0] <= _coerce(value) <= self.coverage[-1]

    def is_trading_day(self, value):
        d = _coerce(value)
        if self._trading_dates is not None:
            return d in self._trading_dates
        return d.weekday() < 5

    def previous_trading_day(self, value):
        d = _coerce(value)
        if self._trading_dates is not None and self.coverage is not None and d <= self.coverage[0]:
            raise ValueError("交易日在日历覆盖范围之外，无法推算上一交易日")
        cursor = d - timedelta(days=1)
        for _ in range(400):
            if self.is_trading_day(cursor):
                return cursor
            cursor -= timedelta(days=1)
        raise ValueError("无法找到上一交易日")

    def next_trading_day(self, value):
        d = _coerce(value)
        if self._trading_dates is not None and self.coverage is not None and d >= self.coverage[-1]:
            raise ValueError("交易日在日历覆盖范围之外，无法推算下一交易日")
        cursor = d + timedelta(days=1)
        for _ in range(400):
            if self.is_trading_day(cursor):
                return cursor
            cursor += timedelta(days=1)
        raise ValueError("无法找到下一交易日")


def load_akshare_trading_calendar():
    """从 akshare 加载权威 A股交易日列表；不可用时回退 weekday_only。

    仅此函数发起网络请求；模块其余部分不依赖 akshare。加载失败不会抛出，
    而是返回 ``verified=False`` 的 weekday-only 日历，由调用方如实标记。
    """
    try:
        import akshare as ak
    except ImportError:
        return TradingCalendar.weekday_only()
    try:
        frame = ak.tool_trade_date_hist_sina()
        dates = [_as_date(value) for value in frame["trade_date"].tolist()]
        if not dates:
            return TradingCalendar.weekday_only()
        return TradingCalendar.from_trading_dates(dates, source="akshare_tool_trade_date_hist_sina")
    except Exception:
        return TradingCalendar.weekday_only()


_calendar_cache = None


def get_trading_calendar(refresh=False):
    """进程内缓存的日历：首次调用加载 akshare，之后复用，避免每次请求联网。"""
    global _calendar_cache
    if _calendar_cache is None or refresh:
        _calendar_cache = load_akshare_trading_calendar()
    return _calendar_cache
