"""akshare 数据层封装：实时快照、日 K 线、分时、指数分时。

所有接口：
  - 内置指数退避重试
  - 简单进程内缓存（同一次 run 内复用）
  - 代码列标准化
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from functools import lru_cache
from threading import Lock
from typing import Optional

import akshare as ak
import pandas as pd

from config import (
    INDEX_SYMBOL,
    KLINE_DAYS,
    REQUEST_INTERVAL,
    RETRY_BACKOFF,
    RETRY_BASE_DELAY,
    RETRY_TIMES,
)
from src.utils import normalize_symbol, setup_logger

logger = setup_logger()

_rate_lock = Lock()
_last_request_ts: float = 0.0


def _throttle() -> None:
    """确保任意两次请求间隔 ≥ REQUEST_INTERVAL（跨线程安全）。"""
    global _last_request_ts
    with _rate_lock:
        now = time.time()
        wait = REQUEST_INTERVAL - (now - _last_request_ts)
        if wait > 0:
            time.sleep(wait)
        _last_request_ts = time.time()


def _retry(fn, *args, **kwargs):
    """带指数退避的通用重试 wrapper。"""
    last_err: Optional[Exception] = None
    for attempt in range(RETRY_TIMES):
        _throttle()
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_err = exc
            wait = RETRY_BASE_DELAY * (RETRY_BACKOFF ** attempt)
            logger.warning(
                "%s 第 %d/%d 次失败: %s，%.1fs 后重试",
                fn.__name__, attempt + 1, RETRY_TIMES, exc, wait,
            )
            time.sleep(wait)
    raise RuntimeError(f"{fn.__name__} 重试 {RETRY_TIMES} 次仍失败: {last_err}")


# ---------- 实时快照 ----------

_SPOT_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_SPOT_TTL_SEC = 60


def get_spot(use_cache: bool = True) -> pd.DataFrame:
    """全 A 股实时快照。60s 内命中缓存。

    标准化字段：code, name, price, change_pct, volume, amount,
    volume_ratio, turnover, float_mv, total_mv
    """
    now = time.time()
    if use_cache and "all" in _SPOT_CACHE:
        ts, cached = _SPOT_CACHE["all"]
        if now - ts < _SPOT_TTL_SEC:
            return cached

    raw = _retry(ak.stock_zh_a_spot_em)
    df = raw.rename(
        columns={
            "代码": "code",
            "名称": "name",
            "最新价": "price",
            "涨跌幅": "change_pct",
            "涨跌额": "change_amt",
            "成交量": "volume",
            "成交额": "amount",
            "量比": "volume_ratio",
            "换手率": "turnover",
            "流通市值": "float_mv",
            "总市值": "total_mv",
            "今开": "open",
            "昨收": "prev_close",
            "最高": "high",
            "最低": "low",
        }
    )
    df["code"] = df["code"].astype(str).str.zfill(6)
    numeric_cols = [
        "price", "change_pct", "change_amt", "volume", "amount",
        "volume_ratio", "turnover", "float_mv", "total_mv",
        "open", "prev_close", "high", "low",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 过滤停牌（价为空或 0）与 ST
    df = df[(df["price"].notna()) & (df["price"] > 0)].copy()
    df = df[~df["name"].astype(str).str.contains("ST", case=False, na=False)]

    _SPOT_CACHE["all"] = (now, df)
    logger.info("拉取实时快照：%d 只股票（剔除停牌/ST 后）", len(df))
    return df


# ---------- 日 K 线 ----------

@lru_cache(maxsize=4096)
def get_kline(
    symbol: str,
    end_date: Optional[str] = None,
    days: int = KLINE_DAYS,
    adjust: str = "qfq",
) -> pd.DataFrame:
    """获取近 `days` 个交易日的日 K 线（含 `end_date`）。

    end_date: YYYYMMDD；None 表示今天。
    """
    symbol = normalize_symbol(symbol)
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    start_date = (
        datetime.strptime(end_date, "%Y%m%d") - timedelta(days=int(days * 1.8))
    ).strftime("%Y%m%d")

    df = _retry(
        ak.stock_zh_a_hist,
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust=adjust,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(
        columns={
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "change_pct",
            "换手率": "turnover",
        }
    )
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


# ---------- 分时 1 分钟 ----------

@lru_cache(maxsize=2048)
def get_minute(symbol: str, date: Optional[str] = None) -> pd.DataFrame:
    """个股当日 1 分钟 K 线（东方财富）。

    date: YYYYMMDD；None 表示今天。仅近期（~5 交易日）数据可用。
    返回含均价列（vwap_today：根据累计成交额/累计成交量计算）。
    """
    symbol = normalize_symbol(symbol)
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    start_dt = f"{date[:4]}-{date[4:6]}-{date[6:]} 09:30:00"
    end_dt = f"{date[:4]}-{date[4:6]}-{date[6:]} 15:00:00"

    df = _retry(
        ak.stock_zh_a_hist_min_em,
        symbol=symbol,
        start_date=start_dt,
        end_date=end_dt,
        period="1",
        adjust="",
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(
        columns={
            "时间": "time",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "均价": "avg_price",
        }
    )
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)
    # 若接口未返回均价列，自己算一个
    if "avg_price" not in df.columns:
        cum_amount = df["amount"].cumsum()
        cum_volume = df["volume"].cumsum().replace(0, pd.NA)
        df["avg_price"] = (cum_amount / cum_volume).astype(float)
    return df


# ---------- 指数分时 ----------

@lru_cache(maxsize=32)
def get_index_minute(
    date: Optional[str] = None, symbol: str = INDEX_SYMBOL
) -> pd.DataFrame:
    """上证指数（默认）当日 1 分钟分时数据。"""
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    start_dt = f"{date[:4]}-{date[4:6]}-{date[6:]} 09:30:00"
    end_dt = f"{date[:4]}-{date[4:6]}-{date[6:]} 15:00:00"
    df = _retry(
        ak.index_zh_a_hist_min_em,
        symbol=symbol,
        period="1",
        start_date=start_dt,
        end_date=end_dt,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(
        columns={
            "时间": "time",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "均价": "avg_price",
        }
    )
    df["time"] = pd.to_datetime(df["time"])
    return df.sort_values("time").reset_index(drop=True)


def clear_cache() -> None:
    _SPOT_CACHE.clear()
    get_kline.cache_clear()
    get_minute.cache_clear()
    get_index_minute.cache_clear()
