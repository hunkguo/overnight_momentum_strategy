"""历史回测引擎 — TdxQuant 版。

关键思路：一次性批量拉取全股票池 + 足够回溯的日 K 线；本地向量化
计算 filter 1/2/5/6；filter 3（换手率）/ filter 4（流通市值）用当期
快照近似（TdxQuant 财务历史需要额外公式，首版暂用近似）；filter 7/8
（分时）不入回测。

每个信号：T 日收盘买入，T+1 日按指定卖点（open/close/high）卖出。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

import pandas as pd
from tqdm import tqdm

from config import (
    CHANGE_HIGH,
    CHANGE_LOW,
    FLOAT_MV_HIGH,
    FLOAT_MV_LOW,
    KLINE_DAYS,
    VOLUME_RATIO_MIN,
)
from src import tdx_data
from src.filters import filter_ma_bullish, filter_volume_pattern
from src.utils import setup_logger

logger = setup_logger()

SellPoint = Literal["open", "close", "high"]


def _universe_with_mv(spot: pd.DataFrame) -> list[str]:
    """按当期流通市值粗筛回测股票池。"""
    u = spot[(spot["float_mv"] >= FLOAT_MV_LOW) & (spot["float_mv"] <= FLOAT_MV_HIGH)]
    return u["code"].tolist()


def backtest(
    start: str,
    end: str,
    sell_point: SellPoint = "close",
    universe_limit: Optional[int] = None,
) -> tuple[pd.DataFrame, dict]:
    """运行回测。

    Args:
        start, end: YYYYMMDD
        sell_point: T+1 卖点
        universe_limit: 仅使用前 N 只（调试）
    Returns:
        (trades_df, summary_dict)
    """
    tdx_data.init_tq()
    logger.info("回测窗口 %s ~ %s，卖点 T+1 %s", start, end, sell_point)

    # 1. 粗筛股票池（流通市值区间）
    spot = tdx_data.get_spot()
    universe = _universe_with_mv(spot)
    if universe_limit:
        universe = universe[:universe_limit]
    logger.info("回测股票池（按当期流通市值粗筛）：%d 只", len(universe))
    if not universe:
        return pd.DataFrame(), {"signals": 0}

    # 2. 批量拉 K 线：start 前再多取 KLINE_DAYS 保证 MA60 有历史
    lookback_days = KLINE_DAYS + 20
    start_dt = datetime.strptime(start, "%Y%m%d")
    # 取前推自然日，保守覆盖
    from datetime import timedelta
    pre_start = (start_dt - timedelta(days=int(lookback_days * 1.8))).strftime("%Y%m%d")
    # end 后多推几天拿 T+1 卖点
    end_plus = (datetime.strptime(end, "%Y%m%d") + timedelta(days=10)).strftime("%Y%m%d")

    # 直接借用 tdx_data 批量接口，但 end_date 要覆盖到 end+10
    daily = tdx_data.get_daily_batch(
        universe,
        end_date=end_plus,
        days=lookback_days + (datetime.strptime(end, "%Y%m%d") - start_dt).days + 20,
    )
    if not daily:
        return pd.DataFrame(), {"signals": 0}

    # 3. 交易日集合：从任一个 K 线的 date 列推断
    first_df = next(iter(daily.values()))
    trading_days = first_df["date"][
        (first_df["date"] >= pd.Timestamp(start_dt))
        & (first_df["date"] <= pd.Timestamp(end_plus))
    ].tolist()
    trading_days = [d for d in trading_days if d <= pd.Timestamp(end)]
    logger.info("区间共 %d 个交易日", len(trading_days))
    if not trading_days:
        return pd.DataFrame(), {"signals": 0}

    # 4. 按股票循环（每只一次性拿到完整历史，避免 IO）
    mv_map = dict(zip(spot["code"], spot["float_mv"]))
    trades: list[dict] = []

    for code in tqdm(universe, desc="回测", ncols=80):
        k = daily.get(code)
        if k is None or len(k) < 30:
            continue
        # 预计算涨跌幅、量比（近 5 日均成交量比）
        k = k.copy()
        k["change_pct"] = (k["close"] / k["close"].shift(1) - 1) * 100
        k["vol5"] = k["volume"].rolling(5).mean().shift(1)
        k["volume_ratio"] = k["volume"] / k["vol5"]

        for td in trading_days:
            mask_today = k["date"] == td
            if not mask_today.any():
                continue
            idx = k.index[mask_today][0]
            if idx < 25:
                continue
            today = k.iloc[idx]

            # filter 1
            cp = today["change_pct"]
            if pd.isna(cp) or not (CHANGE_LOW <= float(cp) <= CHANGE_HIGH):
                continue
            # filter 2
            vr = today["volume_ratio"]
            if pd.isna(vr) or float(vr) <= VOLUME_RATIO_MIN:
                continue
            # filter 3: 换手率 — 回测期无历史快照，跳过（已在 README 标注）
            # filter 4: 流通市值 — 用当期快照近似
            float_mv = float(mv_map.get(code, 0.0))
            if not (FLOAT_MV_LOW <= float_mv <= FLOAT_MV_HIGH):
                continue

            # filter 5/6
            hist = k.iloc[: idx + 1]
            if not filter_volume_pattern(hist).passed:
                continue
            if not filter_ma_bullish(hist).passed:
                continue

            if idx + 1 >= len(k):
                continue
            nxt = k.iloc[idx + 1]
            buy_price = float(today["close"])
            sell_price = float(nxt[sell_point])
            if buy_price <= 0:
                continue
            ret = (sell_price - buy_price) / buy_price * 100

            trades.append({
                "trade_date": td.strftime("%Y-%m-%d"),
                "code": code,
                "buy_price": round(buy_price, 2),
                "sell_price": round(sell_price, 2),
                "return_pct": round(ret, 3),
                "change_pct_today": round(float(cp), 2),
                "volume_ratio": round(float(vr), 2),
            })

    if not trades:
        return pd.DataFrame(), {"signals": 0, "trading_days": len(trading_days)}

    df = pd.DataFrame(trades).sort_values(
        ["trade_date", "return_pct"], ascending=[True, False]
    )
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
