"""通用工具：日志、代码标准化、MA 计算、表格打印。"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
from tabulate import tabulate

from config import LOG_DIR, MA_PERIODS, OUTPUT_DIR

_LOGGER_INITIALIZED = False


def _ensure_utf8_console() -> None:
    """Windows 下把 stdout/stderr 强制 UTF-8，避免中文乱码。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def ensure_dirs() -> None:
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)


def setup_logger(name: str = "oms") -> logging.Logger:
    """按日期滚动的文件日志 + 控制台输出。幂等。"""
    global _LOGGER_INITIALIZED
    logger = logging.getLogger(name)
    if _LOGGER_INITIALIZED:
        return logger

    _ensure_utf8_console()
    ensure_dirs()
    logger.setLevel(logging.INFO)
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    log_path = Path(LOG_DIR) / f"oms_{datetime.now():%Y%m%d}.log"
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    _LOGGER_INITIALIZED = True
    return logger


def normalize_symbol(code: str) -> str:
    """把任意形式的股票代码标准化为 6 位纯数字字符串。"""
    code = str(code).strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if code.startswith(prefix):
            code = code[len(prefix):]
    return code.zfill(6)


def infer_market_prefix(code: str) -> str:
    """根据 6 位代码推断市场前缀。科创板/创业板/北交所也覆盖。"""
    code = normalize_symbol(code)
    if code.startswith(("60", "68", "9")):     # 沪市主板 + 科创板 + B 股
        return "sh"
    if code.startswith(("00", "30", "20")):    # 深市主板 + 创业板 + B 股
        return "sz"
    if code.startswith(("4", "8")):
        return "bj"
    return "sh"


def compute_moving_averages(
    close: pd.Series, periods: Iterable[int] = MA_PERIODS
) -> dict[int, pd.Series]:
    return {p: close.rolling(window=p, min_periods=p).mean() for p in periods}


def print_candidates_table(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        print("\n⚠ 无符合条件的候选股票。\n")
        return
    print("\n" + tabulate(df, headers="keys", tablefmt="github", showindex=False) + "\n")


def save_csv(df: pd.DataFrame, filename: str) -> str:
    ensure_dirs()
    path = os.path.join(OUTPUT_DIR, filename)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path
