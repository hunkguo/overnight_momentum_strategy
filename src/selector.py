"""实时扫描编排：粗筛 → 并行拉取个股 → 精筛 → 返回候选。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

import pandas as pd
from tqdm import tqdm

from config import MAX_WORKERS
from src.data import get_index_minute, get_kline, get_minute, get_spot
from src.filters import (
    filter_basic_coarse,
    filter_intraday_strength,
    filter_ma_bullish,
    filter_pullback_to_vwap,
    filter_volume_pattern,
)
from src.utils import setup_logger

logger = setup_logger()


def _evaluate_one(
    row: pd.Series,
    today: str,
    index_min: Optional[pd.DataFrame],
    skip_intraday: bool,
) -> Optional[dict]:
    """对单只股票依次跑 filter 5/6/7/8，返回候选 dict 或 None。"""
    code = row["code"]
    try:
        kline = get_kline(code, end_date=today)
    except Exception as exc:
        logger.warning("拉取 %s 日 K 失败: %s", code, exc)
        return None

    vol_res = filter_volume_pattern(kline)
    if not vol_res.passed:
        return None
    ma_res = filter_ma_bullish(kline)
    if not ma_res.passed:
        return None

    intraday_reason = pullback_reason = "(skipped)"
    if not skip_intraday:
        try:
            minute = get_minute(code, date=today)
        except Exception as exc:
            logger.warning("拉取 %s 分时失败: %s", code, exc)
            return None
        if minute.empty:
            return None
        intra_res = filter_intraday_strength(minute, index_min)
        if not intra_res.passed:
            return None
        pb_res = filter_pullback_to_vwap(minute)
        if not pb_res.passed:
            return None
        intraday_reason = intra_res.reason
        pullback_reason = pb_res.reason

    return {
        "code": code,
        "name": row.get("name", ""),
        "price": row.get("price"),
        "change_pct": row.get("change_pct"),
        "volume_ratio": row.get("volume_ratio"),
        "turnover": row.get("turnover"),
        "float_mv_billion": round(float(row.get("float_mv", 0)) / 1e8, 2),
        "volume_pattern": vol_res.reason,
        "ma_bullish": ma_res.reason,
        "intraday": intraday_reason,
        "pullback": pullback_reason,
    }


def scan(
    stage: str = "full",
    today: Optional[str] = None,
    top: Optional[int] = None,
) -> pd.DataFrame:
    """运行扫描。

    stage:
      - "coarse": 仅跑 filter 1-4（离线/验证用）
      - "full":   跑全部 8 步（默认）
      - "no-intraday": 跳过 filter 7/8（非交易时段用）
    """
    if today is None:
        today = datetime.now().strftime("%Y%m%d")

    spot = get_spot()
    coarse = filter_basic_coarse(spot)
    logger.info("粗筛后剩余 %d 只（from %d）", len(coarse), len(spot))

    if stage == "coarse" or coarse.empty:
        result = coarse[
            ["code", "name", "price", "change_pct", "volume_ratio", "turnover", "float_mv"]
        ].copy()
        result["float_mv_billion"] = (result["float_mv"] / 1e8).round(2)
        result = result.drop(columns=["float_mv"])
        if top:
            result = result.head(top)
        return result

    skip_intraday = stage == "no-intraday"
    index_min: Optional[pd.DataFrame] = None
    if not skip_intraday:
        try:
            index_min = get_index_minute(date=today)
        except Exception as exc:
            logger.warning("拉取指数分时失败，filter 7 降级为无大盘对比：%s", exc)

    candidates: list[dict] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_evaluate_one, row, today, index_min, skip_intraday): row["code"]
            for _, row in coarse.iterrows()
        }
        with tqdm(total=len(futures), desc="精筛", ncols=80) as bar:
            for fut in as_completed(futures):
                result = fut.result()
                if result:
                    candidates.append(result)
                bar.update(1)

    if not candidates:
        return pd.DataFrame()

    df = pd.DataFrame(candidates).sort_values("change_pct", ascending=False)
    if top:
        df = df.head(top)
    return df.reset_index(drop=True)
