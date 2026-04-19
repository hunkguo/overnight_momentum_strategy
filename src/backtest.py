"""历史回测引擎。

由于 akshare 分时数据仅近期可用（约 5 个交易日），filter 7/8 在早期日期不可回溯；
因此回测在每个交易日仅执行 filter 1-6 的"日线近似"版本：
  - filter 1（涨跌幅 3-5%）: 用 T 日收盘价涨跌幅
  - filter 2（量比 >1）: 用 T 日成交量 / 近 5 日均成交量
  - filter 3（换手率 5-10%）: 用 T 日日线换手率
  - filter 4（流通市值 50-200亿）: 用最新快照（回溯近似）
  - filter 5-6: 用 T 日之前的日 K 线

每个信号：T 日收盘买入，T+1 日按指定卖点（open/close/high）卖出，记录收益。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Literal, Optional

import pandas as pd
from tqdm import tqdm

from config import (
    CHANGE_HIGH,
    CHANGE_LOW,
    FLOAT_MV_HIGH,
    FLOAT_MV_LOW,
    KLINE_DAYS,
    MAX_WORKERS,
    TURNOVER_HIGH,
    TURNOVER_LOW,
    VOLUME_RATIO_MIN,
)
from src.data import get_kline, get_spot
from src.filters import filter_ma_bullish, filter_volume_pattern
from src.utils import setup_logger

logger = setup_logger()

SellPoint = Literal["open", "close", "high"]


def _trading_days_in_range(start: str, end: str) -> list[pd.Timestamp]:
    """用上证指数 000001 的日线推断交易日（调用方只需传日期区间）。"""
    # 借用任意常驻大盘股的日线来确定交易日集合
    probe = get_kline("000001", end_date=end, days=KLINE_DAYS)
    if probe.empty:
        return []
    s = pd.Timestamp(datetime.strptime(start, "%Y%m%d"))
    e = pd.Timestamp(datetime.strptime(end, "%Y%m%d"))
    days = probe[(probe["date"] >= s) & (probe["date"] <= e)]["date"]
    return list(days)


def _evaluate_day_for_stock(
    code: str,
    name: str,
    float_mv: float,
    trade_day: pd.Timestamp,
    sell_point: SellPoint,
) -> Optional[dict]:
    """对单只股票在给定交易日评估策略，命中则返回 {code, return_pct, ...}。"""
    # 拿到覆盖 trade_day 及之前 KLINE_DAYS 的 K 线，同时多拿一天用于次日卖点
    end_date = (trade_day + timedelta(days=10)).strftime("%Y%m%d")
    try:
        kline = get_kline(code, end_date=end_date, days=KLINE_DAYS + 15)
    except Exception as exc:
        logger.debug("拉 %s K 线失败: %s", code, exc)
        return None
    if kline.empty:
        return None

    kline = kline.sort_values("date").reset_index(drop=True)
    mask_today = kline["date"] == trade_day
    if not mask_today.any():
        return None
    idx = kline.index[mask_today][0]
    if idx < 25:     # 需要足够历史
        return None
    today = kline.iloc[idx]

    # ---- filter 1：涨跌幅 3-5% ----
    if not (CHANGE_LOW <= float(today["change_pct"]) <= CHANGE_HIGH):
        return None

    # ---- filter 2：量比 >1（用 T 日成交量/近 5 日均）----
    prev5 = kline.iloc[max(0, idx - 5):idx]["volume"].mean()
    if prev5 <= 0:
        return None
    volume_ratio = float(today["volume"]) / prev5
    if volume_ratio <= VOLUME_RATIO_MIN:
        return None

    # ---- filter 3：换手率 5-10% ----
    turn = today.get("turnover")
    if pd.isna(turn) or not (TURNOVER_LOW <= float(turn) <= TURNOVER_HIGH):
        return None

    # ---- filter 4：流通市值 50-200亿（近似：当前快照）----
    if not (FLOAT_MV_LOW <= float_mv <= FLOAT_MV_HIGH):
        return None

    # ---- filter 5-6：使用 T 日及之前的数据 ----
    hist = kline.iloc[: idx + 1].copy()
    if not filter_volume_pattern(hist).passed:
        return None
    if not filter_ma_bullish(hist).passed:
        return None

    # ---- 成交 ----
    if idx + 1 >= len(kline):
        return None
    next_day = kline.iloc[idx + 1]
    buy_price = float(today["close"])
    sell_price = float(next_day[sell_point])
    ret = (sell_price - buy_price) / buy_price * 100

    return {
        "trade_date": trade_day.strftime("%Y-%m-%d"),
        "code": code,
        "name": name,
        "buy_price": round(buy_price, 2),
        "sell_price": round(sell_price, 2),
        "return_pct": round(ret, 3),
        "volume_ratio": round(volume_ratio, 2),
        "turnover": round(float(turn), 2),
        "change_pct_today": round(float(today["change_pct"]), 2),
    }


def backtest(
    start: str,
    end: str,
    sell_point: SellPoint = "close",
    universe_limit: Optional[int] = None,
) -> tuple[pd.DataFrame, dict]:
    """运行回测。

    由于遍历全市场按日还要跑 filter 5/6（每股都要取 K 线），成本较高。策略本身的
    选股空间先由流通市值 50-200亿 粗筛（靠当前快照近似），再对每个交易日评估。

    Args:
        start, end: YYYYMMDD
        sell_point: next-day 卖点
        universe_limit: 仅用前 N 只股票（调试）
    Returns:
        (trades_df, summary_dict)
    """
    logger.info("回测窗口 %s ~ %s，卖点 T+1 %s", start, end, sell_point)
    trading_days = _trading_days_in_range(start, end)
    if not trading_days:
        raise RuntimeError("未能推断交易日，检查日期区间或 akshare 连通性")
    logger.info("区间共 %d 个交易日", len(trading_days))

    spot = get_spot()
    universe = spot[(spot["float_mv"] >= FLOAT_MV_LOW) & (spot["float_mv"] <= FLOAT_MV_HIGH)]
    if universe_limit:
        universe = universe.head(universe_limit)
    logger.info("回测股票池（按流通市值粗筛）：%d 只", len(universe))

    trades: list[dict] = []
    total_jobs = len(universe) * len(trading_days)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = []
        for _, row in universe.iterrows():
            for td in trading_days:
                futures.append(
                    pool.submit(
                        _evaluate_day_for_stock,
                        row["code"],
                        row.get("name", ""),
                        float(row["float_mv"]),
                        td,
                        sell_point,
                    )
                )
        with tqdm(total=total_jobs, desc="回测", ncols=80) as bar:
            for fut in as_completed(futures):
                r = fut.result()
                if r:
                    trades.append(r)
                bar.update(1)

    if not trades:
        return pd.DataFrame(), {"signals": 0}

    df = pd.DataFrame(trades).sort_values(["trade_date", "return_pct"], ascending=[True, False])
    rets = df["return_pct"]
    summary = {
        "signals": len(df),
        "trading_days": len(trading_days),
        "avg_return_pct": round(rets.mean(), 3),
        "median_return_pct": round(rets.median(), 3),
        "win_rate": round((rets > 0).mean(), 3),
        "max_gain": round(rets.max(), 3),
        "max_loss": round(rets.min(), 3),
        "std_return_pct": round(rets.std(), 3),
    }
    logger.info("回测完成：%s", summary)
    return df.reset_index(drop=True), summary
