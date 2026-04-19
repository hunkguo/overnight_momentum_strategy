"""实时扫描编排：粗筛 → 批量拉日 K → 精筛 → 返回候选。

数据层用 TdxQuant（本地通达信终端），不再有 akshare 网络限流问题；
日 K 一次性批量拉，分时小规模逐股拉。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd
from tqdm import tqdm

from src import tdx_data
from src.filters import (
    filter_basic_coarse,
    filter_intraday_strength,
    filter_ma_bullish,
    filter_pullback_to_vwap,
    filter_volume_pattern,
)
from src.utils import setup_logger

logger = setup_logger()


def scan(
    stage: str = "full",
    today: Optional[str] = None,
    top: Optional[int] = None,
) -> pd.DataFrame:
    """运行扫描。

    stage:
      - "coarse":      仅跑 filter 1-4（离线/验证用）
      - "no-intraday": 跑到 filter 6（非交易时段或无分时数据）
      - "full":        跑全 8 步（默认）
    """
    if today is None:
        today = datetime.now().strftime("%Y%m%d")

    tdx_data.init_tq()

    spot = tdx_data.get_spot(today)
    coarse = filter_basic_coarse(spot)
    logger.info("粗筛后剩余 %d 只（from %d）", len(coarse), len(spot))

    if stage == "coarse" or coarse.empty:
        result = coarse[
            ["code", "name", "change_pct", "volume_ratio", "turnover", "float_mv"]
        ].copy()
        result["float_mv_billion"] = (result["float_mv"] / 1e8).round(2)
        result = result.drop(columns=["float_mv"])
        if top:
            result = result.head(top)
        return result.reset_index(drop=True)

    # Filter 5-6：批量拉日 K，本地精筛
    codes = coarse["code"].tolist()
    daily = tdx_data.get_daily_batch(codes, end_date=today)

    mid: list[dict] = []
    for _, row in coarse.iterrows():
        code = row["code"]
        kline = daily.get(code)
        if kline is None or kline.empty:
            continue
        vol_res = filter_volume_pattern(kline)
        if not vol_res.passed:
            continue
        ma_res = filter_ma_bullish(kline)
        if not ma_res.passed:
            continue
        mid.append({
            **row.to_dict(),
            "volume_pattern": vol_res.reason,
            "ma_bullish": ma_res.reason,
        })
    logger.info("filter 5-6 后剩余 %d 只", len(mid))

    if stage == "no-intraday" or not mid:
        df = pd.DataFrame(mid)
        if not df.empty:
            df["float_mv_billion"] = (df["float_mv"] / 1e8).round(2)
            df = df.drop(columns=["float_mv"])
            df["intraday"] = "(skipped)"
            df["pullback"] = "(skipped)"
            df = df.sort_values("change_pct", ascending=False)
        if top:
            df = df.head(top)
        return df.reset_index(drop=True)

    # Filter 7-8：逐股拉分时
    try:
        index_min = tdx_data.get_index_minute(date=today)
    except Exception as exc:
        logger.warning("拉取指数分时失败，filter 7 降级为无大盘对比：%s", exc)
        index_min = None

    candidates: list[dict] = []
    for row in tqdm(mid, desc="分时精筛", ncols=80):
        code = row["code"]
        try:
            minute = tdx_data.get_minute(code, date=today)
        except Exception as exc:
            logger.warning("拉取 %s 分时失败：%s", code, exc)
            continue
        if minute.empty:
            continue

        intra_res = filter_intraday_strength(minute, index_min)
        if not intra_res.passed:
            continue
        pb_res = filter_pullback_to_vwap(minute)
        if not pb_res.passed:
            continue

        candidates.append({
            "code": code,
            "name": row.get("name", ""),
            "close": row.get("close"),
            "change_pct": row.get("change_pct"),
            "volume_ratio": row.get("volume_ratio"),
            "turnover": row.get("turnover"),
            "float_mv_billion": round(float(row.get("float_mv", 0)) / 1e8, 2),
            "volume_pattern": row.get("volume_pattern", ""),
            "ma_bullish": row.get("ma_bullish", ""),
            "intraday": intra_res.reason,
            "pullback": pb_res.reason,
        })

    if not candidates:
        return pd.DataFrame()

    df = pd.DataFrame(candidates).sort_values("change_pct", ascending=False)
    if top:
        df = df.head(top)
    return df.reset_index(drop=True)
