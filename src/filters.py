"""8 步过滤器实现。与 strategy.txt 的 8 步对应。

- filter_basic_coarse(spot_df)        → 向量化过滤 step 1-4
- filter_volume_pattern(kline_df)     → step 5
- filter_ma_bullish(kline_df)         → step 6
- filter_intraday_strength(...)       → step 7
- filter_pullback_to_vwap(...)        → step 8
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time as dtime
from typing import Optional

import pandas as pd

from config import (
    CHANGE_HIGH,
    CHANGE_LOW,
    FLOAT_MV_HIGH,
    FLOAT_MV_LOW,
    INTRADAY_ABOVE_VWAP_RATIO,
    MA_PERIODS,
    PULLBACK_TOLERANCE,
    PULLBACK_WINDOW_END,
    PULLBACK_WINDOW_START,
    TURNOVER_HIGH,
    TURNOVER_LOW,
    VOLUME_LONG_DAYS,
    VOLUME_RATIO_MIN,
    VOLUME_STACK_DAYS,
    VOLUME_STACK_RATIO,
)
from src.utils import compute_moving_averages


@dataclass(frozen=True)
class FilterResult:
    passed: bool
    reason: str = ""


# ---------- Filter 1-4（向量化，一次过筛全市场）----------

def filter_basic_coarse(spot_df: pd.DataFrame) -> pd.DataFrame:
    """合并 step 1-4 的向量化过滤。"""
    required = {"change_pct", "volume_ratio", "turnover", "float_mv"}
    missing = required - set(spot_df.columns)
    if missing:
        raise KeyError(f"spot 数据缺少字段: {missing}")

    mask = (
        spot_df["change_pct"].between(CHANGE_LOW, CHANGE_HIGH)
        & (spot_df["volume_ratio"] > VOLUME_RATIO_MIN)
        & spot_df["turnover"].between(TURNOVER_LOW, TURNOVER_HIGH)
        & spot_df["float_mv"].between(FLOAT_MV_LOW, FLOAT_MV_HIGH)
    )
    return spot_df.loc[mask].copy()


# ---------- Filter 5：持续放量 ----------

def filter_volume_pattern(kline_df: pd.DataFrame) -> FilterResult:
    """判断近期放量趋势。

    条件：
      1. 近 VOLUME_STACK_DAYS 日均量 > 近 VOLUME_LONG_DAYS 日均量 × VOLUME_STACK_RATIO
      2. 且近 VOLUME_STACK_DAYS 日中至少 60% 的成交量大于前一日（台阶式）
    """
    if kline_df is None or kline_df.empty or len(kline_df) < VOLUME_LONG_DAYS:
        return FilterResult(False, "日线数据不足")

    vol = kline_df["volume"]
    recent_avg = vol.tail(VOLUME_STACK_DAYS).mean()
    long_avg = vol.tail(VOLUME_LONG_DAYS).mean()
    if long_avg <= 0 or recent_avg < long_avg * VOLUME_STACK_RATIO:
        return FilterResult(
            False, f"近期均量 {recent_avg:.0f} < 长期 {long_avg:.0f}×{VOLUME_STACK_RATIO}"
        )

    # 台阶式：近 N 日内有 >=60% 日成交量高于前一日
    last_n = vol.tail(VOLUME_STACK_DAYS + 1).reset_index(drop=True)
    up_days = sum(1 for i in range(1, len(last_n)) if last_n[i] > last_n[i - 1])
    if up_days / VOLUME_STACK_DAYS < 0.6:
        return FilterResult(False, f"台阶式不足：{up_days}/{VOLUME_STACK_DAYS}")

    return FilterResult(True, f"持续放量 近均{recent_avg:.0f}/长均{long_avg:.0f}")


# ---------- Filter 6：均线多头排列 ----------

def filter_ma_bullish(kline_df: pd.DataFrame) -> FilterResult:
    """MA5>MA10>MA20>MA60 且收盘 > MA5。"""
    max_p = max(MA_PERIODS)
    if kline_df is None or kline_df.empty or len(kline_df) < max_p:
        return FilterResult(False, f"日线不足 {max_p} 根")

    mas = compute_moving_averages(kline_df["close"], MA_PERIODS)
    last = {p: float(s.iloc[-1]) for p, s in mas.items()}
    sorted_periods = sorted(MA_PERIODS)   # 5,10,20,60

    # 严格多头：短均线都在长均线之上
    for i in range(len(sorted_periods) - 1):
        short = last[sorted_periods[i]]
        long = last[sorted_periods[i + 1]]
        if short <= long:
            return FilterResult(
                False, f"MA{sorted_periods[i]}({short:.2f}) <= MA{sorted_periods[i+1]}({long:.2f})"
            )

    close = float(kline_df["close"].iloc[-1])
    if close <= last[sorted_periods[0]]:
        return FilterResult(False, f"收盘 {close:.2f} 跌破 MA{sorted_periods[0]}")

    return FilterResult(
        True,
        " > ".join(f"MA{p}:{last[p]:.2f}" for p in sorted_periods),
    )


# ---------- Filter 7：分时强势 ----------

def filter_intraday_strength(
    stock_min: pd.DataFrame,
    index_min: Optional[pd.DataFrame] = None,
) -> FilterResult:
    """全天 ≥80% 时间 股价 > 均价线；且相对指数累计收益 > 0。"""
    if stock_min is None or stock_min.empty:
        return FilterResult(False, "分时数据缺失")
    if "avg_price" not in stock_min.columns:
        return FilterResult(False, "缺少均价列")

    above = (stock_min["close"] > stock_min["avg_price"]).sum()
    total = len(stock_min)
    ratio = above / total if total else 0
    if ratio < INTRADAY_ABOVE_VWAP_RATIO:
        return FilterResult(False, f"价>均价时间占比 {ratio:.2%} < 阈值")

    if index_min is not None and not index_min.empty:
        # 以首分钟收盘为基准计算累计涨幅，股票累计涨幅 > 指数累计涨幅
        s_ret = stock_min["close"].iloc[-1] / stock_min["close"].iloc[0] - 1
        i_ret = index_min["close"].iloc[-1] / index_min["close"].iloc[0] - 1
        if s_ret <= i_ret:
            return FilterResult(
                False, f"相对指数偏弱：股票 {s_ret:.2%} ≤ 指数 {i_ret:.2%}"
            )
        return FilterResult(True, f"价>均价 {ratio:.0%}, 强于指数 {s_ret - i_ret:+.2%}")

    return FilterResult(True, f"价>均价 {ratio:.0%}（无指数对比）")


# ---------- Filter 8：回踩均价线不破 ----------

def _parse_hhmm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def filter_pullback_to_vwap(
    stock_min: pd.DataFrame,
    tolerance: float = PULLBACK_TOLERANCE,
) -> FilterResult:
    """窗口内出现当日新高后，回踩均价线且未跌破（允许 ±tolerance 误差）。"""
    if stock_min is None or stock_min.empty:
        return FilterResult(False, "分时数据缺失")

    ws, we = _parse_hhmm(PULLBACK_WINDOW_START), _parse_hhmm(PULLBACK_WINDOW_END)
    window = stock_min[
        (stock_min["time"].dt.time >= ws) & (stock_min["time"].dt.time <= we)
    ]
    if window.empty:
        return FilterResult(False, f"{PULLBACK_WINDOW_START}~{PULLBACK_WINDOW_END} 无数据")

    # 识别窗口内"创当日新高"的时刻
    day_high_series = stock_min["high"].cummax()
    window = window.copy()
    window["day_high"] = day_high_series.loc[window.index]
    new_high_rows = window[window["high"] >= window["day_high"] - 1e-6]
    if new_high_rows.empty:
        return FilterResult(False, "窗口内无新高")

    first_high_idx = new_high_rows.index[0]
    after_high = stock_min.loc[first_high_idx:]
    # 回踩：存在一分钟最低价 ≤ 均价线 × (1 + tolerance) 且收盘 ≥ 均价线 × (1 - tolerance)
    touched = (after_high["low"] <= after_high["avg_price"] * (1 + tolerance)) & (
        after_high["close"] >= after_high["avg_price"] * (1 - tolerance)
    )
    if not touched.any():
        return FilterResult(False, "新高后未回踩均价线")

    # 最新 bar 收盘需在均价之上（此刻可介入）
    last = stock_min.iloc[-1]
    if last["close"] < last["avg_price"] * (1 - tolerance):
        return FilterResult(False, f"当前价 {last['close']:.2f} 已破均价 {last['avg_price']:.2f}")

    return FilterResult(True, "回踩均价线不破")
