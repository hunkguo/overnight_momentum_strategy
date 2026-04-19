"""TdxQuant (tqcenter) 数据层封装。

替代原 akshare 数据层。核心接口：
  - init_tq()                        一次性初始化，追加 sys.path 并连接本地终端
  - get_universe()                   取股票池（按 config.UNIVERSE_MODE）
  - get_spot(today=None)             实时快照（涨跌幅/量比/换手率/流通市值）
  - get_daily_batch(codes, end_date) 批量日 K 线（复权）
  - get_minute(code, date)           单股当日 1 分钟分时
  - get_index_minute(date)           指数当日 1 分钟分时
  - send_to_block(df)                把候选股写入自定义板块
  - send_message(text)               推送到 TQ 策略管理器

说明：
  - 股票代码内部维护"6 位数字"形式；对 TDX 调用时临时转成 `XXXXXX.SH/SZ/BJ`。
  - spot 完全从 `tq.get_market_data` 日 K 线 + `tq.get_stock_info` 静态信息本地算出，
    不再依赖任何 TDX 公式。静态信息（流通股本 / 名称）缓存在 output/tdx_stock_info.json，
    24 小时自动刷新。
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
from tqdm import tqdm

from config import (
    INDEX_SYMBOL,
    KLINE_DAYS,
    OUTPUT_DIR,
    PUSH_BLOCK_CODE,
    PUSH_BLOCK_NAME,
    TDX_USER_PATH,
    UNIVERSE_MARKET,
    UNIVERSE_MODE,
    UNIVERSE_SECTOR,
)
from src.utils import ensure_dirs, normalize_symbol, setup_logger, to_tdx_code

logger = setup_logger()

_tq = None        # 全局 tqcenter 对象，由 init_tq() 填充

_STOCK_INFO_CACHE_FILE = Path(OUTPUT_DIR) / "tdx_stock_info.json"
_STOCK_INFO_TTL_SEC = 24 * 3600


# ----------------------------------------------------------------------
# 初始化
# ----------------------------------------------------------------------

def init_tq() -> None:
    """追加 TDX PYPlugins 路径并调用 tq.initialize。幂等。"""
    global _tq
    if _tq is not None:
        return
    if TDX_USER_PATH not in sys.path:
        sys.path.append(TDX_USER_PATH)
    try:
        from tqcenter import tq  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            f"无法 import tqcenter。请检查：\n"
            f"  1) 通达信金融终端已安装且支持 TQ 策略\n"
            f"  2) config.TDX_USER_PATH 指向正确的 PYPlugins/user 目录\n"
            f"     当前值：{TDX_USER_PATH}\n"
            f"原始错误：{exc}"
        ) from exc

    try:
        tq.initialize(__file__)
    except Exception as exc:
        raise RuntimeError(
            f"tq.initialize 失败。请确认：\n"
            f"  1) 通达信终端正在运行\n"
            f"  2) 终端菜单栏已出现「TQ 策略」且其状态为就绪\n"
            f"  3) 杀毒软件未拦截 tdxrpcx64.dll / TPythClient.dll\n"
            f"原始错误：{exc}"
        ) from exc

    _tq = tq
    logger.info("tqcenter 初始化完成（PYPlugins=%s）", TDX_USER_PATH)


def _tq_or_raise():
    if _tq is None:
        raise RuntimeError("请先调用 init_tq() 初始化 tqcenter")
    return _tq


# ----------------------------------------------------------------------
# 股票池
# ----------------------------------------------------------------------

def get_universe() -> list[str]:
    """按配置取股票池，返回 6 位数字代码列表（内部统一格式）。"""
    tq = _tq_or_raise()
    if UNIVERSE_MODE == "sector":
        raw = tq.get_stock_list_in_sector(UNIVERSE_SECTOR)
    else:
        raw = tq.get_stock_list(market=UNIVERSE_MARKET)
    codes = [normalize_symbol(x) for x in (raw or [])]
    logger.info("拉取股票池（mode=%s）：%d 只", UNIVERSE_MODE, len(codes))
    return codes


# ----------------------------------------------------------------------
# 静态信息缓存：流通股本 / 名称 / 是否指数 / 板块类型
# ----------------------------------------------------------------------

def _load_stock_info_cache() -> Optional[dict]:
    if not _STOCK_INFO_CACHE_FILE.exists():
        return None
    try:
        data = json.loads(_STOCK_INFO_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("stock_info 缓存读取失败（将重建）：%s", exc)
        return None
    if time.time() - data.get("ts", 0) > _STOCK_INFO_TTL_SEC:
        return None
    return data.get("items")


def _save_stock_info_cache(items: dict[str, dict]) -> None:
    ensure_dirs()
    payload = {"ts": time.time(), "items": items}
    _STOCK_INFO_CACHE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def get_stock_info_batch(codes: list[str], refresh: bool = False) -> dict[str, dict]:
    """逐股拉取 {code -> {name, active_capital(万股), is_index, stock_kind}}，结果缓存 24h。"""
    tq = _tq_or_raise()
    cache = None if refresh else _load_stock_info_cache()
    if cache is not None and all(c in cache for c in codes):
        return {c: cache[c] for c in codes}

    out: dict[str, dict] = dict(cache or {})
    missing = [c for c in codes if c not in out]
    if not missing:
        return out

    logger.info("拉取 stock_info：%d 只（缓存命中 %d）", len(missing), len(out))
    for code in tqdm(missing, desc="stock_info", ncols=80):
        try:
            info = tq.get_stock_info(to_tdx_code(code))
        except Exception as exc:
            logger.debug("get_stock_info %s 失败：%s", code, exc)
            continue
        if not isinstance(info, dict):
            continue
        try:
            out[code] = {
                "name": str(info.get("Name", "") or ""),
                "active_capital": float(info.get("ActiveCapital") or 0.0),  # 万股
                "is_index": str(info.get("IsZS", "0")) == "1",
                "stock_kind": str(info.get("HSStockKind", "") or ""),
            }
        except (TypeError, ValueError):
            continue

    _save_stock_info_cache(out)
    return {c: out[c] for c in codes if c in out}


# ----------------------------------------------------------------------
# 实时快照（从日 K + 静态信息本地算出）
# ----------------------------------------------------------------------

def get_spot(today: Optional[str] = None) -> pd.DataFrame:
    """批量取实时快照。返回 DataFrame，列：
    code, name, change_pct, volume_ratio, turnover, float_mv, close
    """
    tq = _tq_or_raise()
    if today is None:
        today = datetime.now().strftime("%Y%m%d")

    codes = get_universe()
    if not codes:
        return pd.DataFrame(
            columns=["code", "name", "change_pct", "volume_ratio",
                     "turnover", "float_mv", "close"]
        )

    info_map = get_stock_info_batch(codes)
    # 剔除指数 / 无流通股本
    tradable = [
        c for c in codes
        if c in info_map
        and not info_map[c].get("is_index")
        and info_map[c].get("active_capital", 0) > 0
    ]
    # 过滤掉 ST（名称里含 ST）
    tradable = [c for c in tradable if "ST" not in info_map[c].get("name", "").upper()]
    logger.info("可交易池（剔除指数/ST/无股本）：%d 只", len(tradable))

    tdx_codes = [to_tdx_code(c) for c in tradable]

    # 取近 10 个交易日日 K：需要 T 日收盘、T-1 日收盘、前 5 日均量
    data = tq.get_market_data(
        field_list=["Close", "Volume"],
        stock_list=tdx_codes,
        period="1d",
        count=10,
        dividend_type="none",   # 计算涨跌幅要用实际价
    )
    close_wide = data.get("Close")
    vol_wide = data.get("Volume")
    if close_wide is None or close_wide.empty:
        raise RuntimeError(
            "get_market_data 返回空。检查终端是否已下载盘后数据（TQ 策略 → TQ 数据设置 → 盘后数据下载）"
        )

    # 取最后两行做 T / T-1
    if len(close_wide) < 2:
        raise RuntimeError(f"K 线不足 2 根，无法算涨跌幅：shape={close_wide.shape}")

    # 数据完整性校验：最后两根 K 的日期间隔必须接近（排除因历史数据缺失导致的跨月对比）
    last_dates = list(close_wide.index[-2:])
    gap_days = (pd.Timestamp(last_dates[1]) - pd.Timestamp(last_dates[0])).days
    if gap_days > 5:
        raise RuntimeError(
            f"最近两根日 K 相距 {gap_days} 天（{last_dates[0].date()} → {last_dates[1].date()}），"
            f"本地历史数据不完整。请在通达信终端：\n"
            f"  TQ 策略 → TQ 数据设置 → 盘后数据下载 → 日线数据，\n"
            f"  选择至少近 30 天的日期范围后重试。"
        )

    latest_close = close_wide.iloc[-1]
    prev_close = close_wide.iloc[-2]
    latest_vol = vol_wide.iloc[-1]
    avg5_vol = vol_wide.iloc[-6:-1].mean()      # 前 5 日均量（不含 T 日）

    rows: list[dict] = []
    for code, tdx_code in zip(tradable, tdx_codes):
        if tdx_code not in close_wide.columns:
            continue
        c0 = prev_close.get(tdx_code)
        c1 = latest_close.get(tdx_code)
        v1 = latest_vol.get(tdx_code)
        v5 = avg5_vol.get(tdx_code)
        if pd.isna(c0) or pd.isna(c1) or c0 <= 0 or c1 <= 0:
            continue
        info = info_map[code]
        active = info["active_capital"]         # 万股

        change_pct = (float(c1) / float(c0) - 1) * 100
        if v5 and not pd.isna(v5) and v5 > 0:
            volume_ratio = float(v1) / float(v5)
        else:
            volume_ratio = float("nan")
        # 换手率(%) = 成交股数 / 流通总股数 × 100
        #   批量 get_market_data 里 Volume 单位是"股"（非手）；ActiveCapital 单位 "万股"
        #   → turnover% = Volume / (ActiveCapital × 10000) × 100 = Volume / ActiveCapital / 100
        turnover = float(v1) / active / 100.0 if active > 0 else float("nan")
        float_mv = float(c1) * active * 10000.0  # 元

        rows.append({
            "code": code,
            "name": info["name"],
            "close": round(float(c1), 3),
            "change_pct": round(change_pct, 3),
            "volume_ratio": round(volume_ratio, 3),
            "turnover": round(turnover, 3),
            "float_mv": float_mv,
        })

    if not rows:
        raise RuntimeError("spot 空结果：K 线可用但所有股票无有效换手率/市值")

    df = pd.DataFrame(rows)
    logger.info("spot 快照：%d 只（最新交易日 %s）",
                len(df), close_wide.index[-1].strftime("%Y-%m-%d"))
    return df


# ----------------------------------------------------------------------
# 日 K 线（批量）
# ----------------------------------------------------------------------

_DEFAULT_FIELDS: tuple[str, ...] = ("Open", "High", "Low", "Close", "Volume", "Amount")


def get_daily_batch(
    codes: list[str],
    end_date: Optional[str] = None,
    days: int = KLINE_DAYS,
    fields: Iterable[str] = _DEFAULT_FIELDS,
    adjust: str = "front",
) -> dict[str, pd.DataFrame]:
    """一次性批量拉日 K 线。

    Args:
        codes:   6 位数字代码列表
        end_date: YYYYMMDD；None 表示今天
        days:    回溯交易日数
        fields:  需要的字段
        adjust:  'front' | 'back' | 'none'

    Returns:
        {code -> DataFrame(date, open, high, low, close, volume, amount)}
    """
    tq = _tq_or_raise()
    if not codes:
        return {}
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    start_date = (
        datetime.strptime(end_date, "%Y%m%d") - timedelta(days=int(days * 1.8))
    ).strftime("%Y%m%d")

    tdx_codes = [to_tdx_code(c) for c in codes]
    field_list = list(fields)
    data = tq.get_market_data(
        field_list=field_list,
        stock_list=tdx_codes,
        start_time=start_date,
        end_time=end_date,
        period="1d",
        dividend_type=adjust,
        fill_data=True,
    )

    any_df = next((v for v in data.values() if hasattr(v, "shape") and not v.empty), None)
    if any_df is None:
        logger.warning("get_daily_batch 全空（codes=%d, %s~%s）",
                       len(codes), start_date, end_date)
        return {}
    index = pd.to_datetime(any_df.index)

    out: dict[str, pd.DataFrame] = {}
    for tdx_code, code in zip(tdx_codes, codes):
        sub = {"date": index}
        has_data = False
        for f in field_list:
            w = data.get(f)
            if w is not None and not w.empty and tdx_code in w.columns:
                col = pd.to_numeric(w[tdx_code].values, errors="coerce")
                sub[f.lower()] = col
                if not all(pd.isna(col)):
                    has_data = True
            else:
                sub[f.lower()] = [float("nan")] * len(index)
        if not has_data:
            continue
        df = pd.DataFrame(sub).sort_values("date").reset_index(drop=True)
        df = df.dropna(subset=["close"])
        if not df.empty:
            out[code] = df

    logger.info(
        "批量日 K：成功 %d / %d 只（%s~%s）",
        len(out), len(codes), start_date, end_date,
    )
    return out


# ----------------------------------------------------------------------
# 分时 1 分钟
# ----------------------------------------------------------------------

def _minute_to_df(data: dict, tdx_code: str) -> pd.DataFrame:
    """把 tq.get_market_data(period='1m') 的返回（宽表字典）转成标准 DataFrame。"""
    cols: dict[str, pd.Series] = {}
    for f in ("Open", "High", "Low", "Close", "Volume", "Amount"):
        w = data.get(f)
        if w is None or w.empty or tdx_code not in w.columns:
            continue
        cols[f.lower()] = pd.to_numeric(w[tdx_code], errors="coerce")
    if "close" not in cols:
        return pd.DataFrame()

    idx = pd.to_datetime(next(iter(cols.values())).index)
    df = pd.DataFrame({"time": idx, **{k: v.values for k, v in cols.items()}})
    df = df.sort_values("time").reset_index(drop=True)
    if "amount" in df.columns and "volume" in df.columns:
        cum_amount = df["amount"].cumsum()
        cum_volume = df["volume"].cumsum().replace(0, pd.NA)
        df["avg_price"] = (cum_amount / cum_volume).astype(float)
    else:
        df["avg_price"] = df["close"]
    return df


def get_minute(code: str, date: Optional[str] = None) -> pd.DataFrame:
    """个股当日 1 分钟分时。"""
    tq = _tq_or_raise()
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    tdx_code = to_tdx_code(code)
    data = tq.get_market_data(
        field_list=["Open", "High", "Low", "Close", "Volume", "Amount"],
        stock_list=[tdx_code],
        start_time=date,
        end_time=date,
        period="1m",
        dividend_type="none",
        fill_data=True,
    )
    return _minute_to_df(data, tdx_code)


def get_index_minute(date: Optional[str] = None, code: str = INDEX_SYMBOL) -> pd.DataFrame:
    """指数当日 1 分钟分时（code 带 .SH/.SZ 后缀）。"""
    tq = _tq_or_raise()
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    data = tq.get_market_data(
        field_list=["Open", "High", "Low", "Close", "Volume", "Amount"],
        stock_list=[code],
        start_time=date,
        end_time=date,
        period="1m",
        dividend_type="none",
        fill_data=True,
    )
    return _minute_to_df(data, code)


# ----------------------------------------------------------------------
# 推送到终端
# ----------------------------------------------------------------------

def send_to_block(
    codes: list[str],
    block_code: str = PUSH_BLOCK_CODE,
    block_name: str = PUSH_BLOCK_NAME,
) -> None:
    """把选股结果写入自定义板块。codes 为 6 位数字列表。"""
    tq = _tq_or_raise()
    tdx_codes = [to_tdx_code(c) for c in codes]
    try:
        tq.create_sector(block_code=block_code, block_name=block_name)
    except Exception as exc:
        logger.debug("create_sector 提示（通常是板块已存在，可忽略）：%s", exc)
    try:
        tq.send_user_block(block_code=block_code, stocks=tdx_codes, show=True)
        logger.info("已推送 %d 只到自定义板块「%s(%s)」", len(tdx_codes), block_name, block_code)
    except Exception as exc:
        logger.warning("send_user_block 失败：%s", exc)


def send_message(text: str) -> None:
    """向 TQ 策略管理器发消息（格式：MSG,<正文>）。"""
    tq = _tq_or_raise()
    payload = text if text.startswith("MSG,") else f"MSG,{text}"
    try:
        tq.send_message(payload)
    except Exception as exc:
        logger.warning("send_message 失败：%s", exc)
