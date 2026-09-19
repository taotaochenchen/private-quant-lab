"""免费指数日线适配器。真实失败不回退 mock；不将抓取时间当行情时间。"""

from datetime import datetime, time, timedelta, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic

from .market_sentiment import _time


SHANGHAI = timezone(timedelta(hours=8))
INDEX_SYMBOLS = {
    "000001.SH": "sh000001", "000300.SH": "sh000300", "000905.SH": "sh000905",
    "000016.SH": "sh000016", "000852.SH": "sh000852", "399001.SZ": "sz399001",
    "399006.SZ": "sz399006", "899050.BJ": "bj899050",
}


def fetch_index_bars(symbol, start_date, end_date):
    """隔离 AKShare 的阻塞请求，45秒后终止子进程，不修改全局网络设置。"""
    return _run_worker("index", symbol, start_date, end_date)


def fetch_market_activity():
    """获取市场涨跌家数等宽度数据（隔离子进程）。"""
    return _run_worker("market_activity")


def _run_worker(*args):
    env = dict(os.environ)
    source = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = source + os.pathsep + env.get("PYTHONPATH", "")
    try:
        completed = subprocess.run([sys.executable, "-m", "private_quant_lab.tools.real_market", *args],
                                   capture_output=True, text=True, timeout=45, env=env)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("AKShare request timed out after 45 seconds") from exc
    if completed.returncode:
        raise RuntimeError(completed.stdout.strip() or "AKShare worker failed; check market-data dependency")
    return json.loads(completed.stdout)


def real_market_snapshot(arguments, fetcher=None, now=None):
    """输入 market/indices/as_of；输出日线收盘快照及逐标的缺失原因。

    首版统一排除 as_of 当天日线，适用于盘前研究。过去60个自然日内不足两根
    日线时标记缺失；仅按交易日期过滤，不保证历史修订数据的 point-in-time 可用性。
    """
    now = now or datetime.now(SHANGHAI)
    as_of = _time(arguments["as_of"]).astimezone(SHANGHAI)
    if as_of > now:
        raise ValueError("as_of must not be in the future")
    if arguments["market"] != "CN_A":
        raise ValueError("only CN_A is supported")
    symbols = arguments["indices"]
    if not isinstance(symbols, list) or not 1 <= len(symbols) <= 8:
        raise ValueError("real mode supports 1 to 8 indices")
    if any(symbol not in INDEX_SYMBOLS for symbol in symbols) or len(set(symbols)) != len(symbols):
        raise ValueError("unsupported or duplicate indices; supported: " + ", ".join(INDEX_SYMBOLS))
    cutoff = as_of.date() - timedelta(days=1)
    fetcher = fetcher or fetch_index_bars
    quotes, missing, errors = [], [], {}
    started = monotonic()
    for symbol in symbols:
        try:
            if monotonic() - started >= 45:
                raise RuntimeError("request budget exhausted; retry this index separately")
            rows = fetcher(INDEX_SYMBOLS[symbol], (cutoff - timedelta(days=60)).strftime("%Y%m%d"), cutoff.strftime("%Y%m%d"))
            bars = {}
            for row in rows:
                day = datetime.fromisoformat(str(row["date"])[:10]).date()
                if day <= cutoff:
                    if day in bars:
                        raise ValueError("duplicate daily bars")
                    bars[day] = row
            dates = sorted(bars)
            if len(dates) < 2:
                raise ValueError("fewer than two completed daily bars")
            day = dates[-1]
            if (cutoff - day).days > 14:
                raise ValueError("latest bar is more than 14 calendar days old")
            current, previous = bars[day], bars[dates[-2]]
            close, previous_close, amount = float(current["close"]), float(previous["close"]), float(current["amount"])
            if not all(math.isfinite(v) for v in (close, previous_close, amount)) or min(close, previous_close) <= 0 or amount < 0:
                raise ValueError("invalid close or turnover")
            quotes.append({"symbol": symbol, "price": close, "previous_close": previous_close,
                           "change_pct": round((close / previous_close - 1) * 100, 6), "turnover_cny": amount,
                           "session": "closed", "trade_date": day.isoformat(),
                           "source_timestamp": datetime.combine(day, time(15), SHANGHAI).isoformat(),
                           "timestamp_basis": "daily_bar_session_close_not_publication_time"})
        except Exception as exc:
            missing.append(symbol)
            errors[symbol] = str(exc)
    dates = {q["trade_date"] for q in quotes}
    warnings = ["盘前日线模式：排除截止时间当日的日线；非实时行情。",
                "不保证历史修订前版本及精确发布时点，不可直接用作严格 point-in-time 回测。"]
    if len(dates) > 1:
        warnings.append("指数最新交易日期不一致。")
        missing.append("consistent_trade_date")
    return {"data": {"market": "CN_A", "quotes": quotes}, "mock": False, "is_mock": False,
            "source": "akshare:eastmoney:stock_zh_index_daily_em", "data_version": "index-daily-v1",
            "as_of": arguments["as_of"], "fetched_at": datetime.now(SHANGHAI).isoformat(),
            "point_in_time_verified": False, "missing_fields": missing, "errors": errors, "warnings": warnings}


BREADTH_ITEM_KEYS = {"上涨": "advancers", "下跌": "decliners", "平盘": "unchanged",
                     "涨停": "limit_up", "跌停": "limit_down", "停牌": "suspended"}


def real_market_breadth(arguments, fetcher=None, now=None):
    """输入 market/lookback_days/as_of；输出真实涨跌家数与涨跌停家数。

    真实失败不回退 mock；不含成交额比、波动率、站上均线比例，这些字段明确缺失。
    统计日期取最近一个交易日，不把抓取时间当行情时间。
    """
    now = now or datetime.now(SHANGHAI)
    as_of = _time(arguments["as_of"]).astimezone(SHANGHAI)
    if as_of > now:
        raise ValueError("as_of must not be in the future")
    if arguments["market"] != "CN_A":
        raise ValueError("only CN_A is supported")
    fetcher = fetcher or fetch_market_activity
    try:
        rows = fetcher()
    except Exception as exc:
        return {"data": {}, "mock": False, "is_mock": False,
                "source": "akshare:legu:stock_market_activity_legu", "data_version": "breadth-v1",
                "as_of": arguments["as_of"], "fetched_at": datetime.now(SHANGHAI).isoformat(),
                "point_in_time_verified": False, "missing_fields": ["data"],
                "errors": {"data": str(exc)}, "warnings": ["真实市场宽度获取失败，未回退 mock。"]}
    parsed = {}
    for row in rows:
        if isinstance(row, dict):
            item = str(row.get("item", "")).strip()
            if item:
                parsed[item] = row.get("value")
    data = {"market": "CN_A", "lookback_days": arguments.get("lookback_days")}
    missing = []
    for item, key in BREADTH_ITEM_KEYS.items():
        value = _as_int(parsed.get(item))
        if value is None:
            missing.append(key)
        else:
            data[key] = value
    data["source_timestamp"] = _activity_timestamp(parsed.get("统计日期"))
    missing.extend(["turnover_ratio", "annualized_volatility_pct", "above_ma20_ratio"])
    return {"data": data, "mock": False, "is_mock": False,
            "source": "akshare:legu:stock_market_activity_legu", "data_version": "breadth-v1",
            "as_of": arguments["as_of"], "fetched_at": datetime.now(SHANGHAI).isoformat(),
            "point_in_time_verified": False, "missing_fields": missing, "errors": {},
            "warnings": ["真实市场宽度不含成交额比/波动率/站上均线比例，需另行接入。",
                         "统计日期为最近一个交易日，非实时行情。"]}


def _as_int(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(str(value).replace("%", "").replace(",", "")))
    except (ValueError, TypeError):
        return None


def _activity_timestamp(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=SHANGHAI).isoformat()
    except ValueError:
        return text


def _worker():
    mode = sys.argv[1] if len(sys.argv) > 1 else "index"
    try:
        import akshare as ak
        if mode == "market_activity":
            frame = ak.stock_market_activity_legu()
        else:
            frame = ak.stock_zh_index_daily_em(symbol=sys.argv[2], start_date=sys.argv[3], end_date=sys.argv[4])
        print(frame.to_json(orient="records", date_format="iso"))
        return 0
    except ImportError:
        print("Missing AKShare: install project with pip install -e '.[market-data]'")
    except Exception as exc:
        print("AKShare fetch failed: " + type(exc).__name__)
    return 1


if __name__ == "__main__":
    raise SystemExit(_worker())
