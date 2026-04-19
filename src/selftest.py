"""离线自检：用合成数据端到端跑一遍 filters，验证代码逻辑。

由于 akshare 的东方财富端点间歇性限流（见 README 的「已知限制」），当网络访问
被临时阻断时，仍可通过本模块验证过滤器链路正确。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.filters import (
    filter_basic_coarse,
    filter_intraday_strength,
    filter_ma_bullish,
    filter_pullback_to_vwap,
    filter_volume_pattern,
)


def _make_spot_fixture() -> pd.DataFrame:
    """构造 5 只股票的合成 spot。仅 1 只通过粗筛。"""
    rows = [
        # code, change_pct, volume_ratio, turnover, float_mv(元)
        ("000001", "TESTPASS", 4.2, 1.5, 7.0, 100e8),     # 通过所有 1-4
        ("000002", "TOOFAST", 6.5, 2.0, 7.0, 100e8),      # 涨幅超 5%
        ("000003", "LOWVR", 4.0, 0.8, 7.0, 100e8),        # 量比不够
        ("000004", "HIGHTURN", 4.0, 1.5, 15.0, 100e8),    # 换手率过高
        ("000005", "BIGCAP", 4.0, 1.5, 7.0, 500e8),       # 流通市值过大
    ]
    return pd.DataFrame(
        rows,
        columns=["code", "name", "change_pct", "volume_ratio", "turnover", "float_mv"],
    )


def _make_kline_fixture(bullish: bool = True, n: int = 80) -> pd.DataFrame:
    """合成 80 天日 K：bullish=True 时构造均线多头 + 近期放量。"""
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n + 5)[-n:]
    if bullish:
        # 缓慢上涨的趋势 + 最后几天加速
        base = np.linspace(10.0, 13.0, n)
        noise = np.random.default_rng(42).normal(0, 0.05, n)
        close = base + noise
        close[-5:] += np.linspace(0.2, 0.8, 5)
        # 成交量：基线 100 万，近 5 日逐步放大
        volume = np.full(n, 1_000_000.0)
        volume[-5:] = [1_500_000, 1_700_000, 1_900_000, 2_200_000, 2_500_000]
    else:
        close = np.linspace(14.0, 10.0, n) + np.random.default_rng(1).normal(0, 0.1, n)
        volume = np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.05,
            "close": close,
            "high": close + 0.1,
            "low": close - 0.1,
            "volume": volume,
            "amount": close * volume,
            "change_pct": np.zeros(n),
            "turnover": np.full(n, 6.0),
        }
    )


def _make_minute_fixture(strong: bool = True) -> pd.DataFrame:
    """合成分时 09:30–15:00（不含午休简化），strong=True 时构造价>均价 + 14:00 回踩。"""
    date = pd.Timestamp.today().normalize() + pd.Timedelta(hours=9, minutes=30)
    # 09:30~15:00 共 330 分钟（包含午休时段简化处理）
    n = 330
    times = pd.date_range(start=date, periods=n, freq="1min")
    rng = np.random.default_rng(7)
    if strong:
        base = np.linspace(10.0, 10.5, n) + rng.normal(0, 0.01, n)
        # idx=270 对应 14:00；14:00~14:05 创新高，14:10~14:20 回踩，最后几分钟收回均价上方
        idx_1400 = 270
        base[idx_1400: idx_1400 + 5] = 10.7        # 创新高
        base[idx_1400 + 10: idx_1400 + 20] -= 0.2  # 回踩
        base[idx_1400 + 20:] = np.clip(base[idx_1400 + 20:], 10.35, None)  # 守住均价
    else:
        base = np.linspace(10.5, 10.0, n) + rng.normal(0, 0.01, n)
    volume = np.full(n, 10_000.0)
    amount = base * volume
    df = pd.DataFrame(
        {
            "time": times,
            "open": base - 0.01,
            "close": base,
            "high": base + 0.02,
            "low": base - 0.02,
            "volume": volume,
            "amount": amount,
        }
    )
    df["avg_price"] = df["amount"].cumsum() / df["volume"].cumsum()
    return df


def run_selftest() -> dict:
    """跑完整自检，返回各 filter 的结果。抛异常则代码逻辑有问题。"""
    result: dict = {}

    # Filter 1-4
    spot = _make_spot_fixture()
    coarse = filter_basic_coarse(spot)
    assert len(coarse) == 1 and coarse.iloc[0]["code"] == "000001", (
        f"粗筛应仅保留 TESTPASS，实际 {coarse['name'].tolist()}"
    )
    result["coarse"] = "PASS (only TESTPASS through)"

    # Filter 5
    pass_kline = _make_kline_fixture(bullish=True)
    fail_kline = _make_kline_fixture(bullish=False)
    assert filter_volume_pattern(pass_kline).passed, "放量 kline 应通过"
    assert not filter_volume_pattern(fail_kline).passed, "弱势 kline 不应通过"
    result["volume_pattern"] = "PASS"

    # Filter 6
    assert filter_ma_bullish(pass_kline).passed, "多头 kline 应通过"
    assert not filter_ma_bullish(fail_kline).passed, "空头 kline 不应通过"
    result["ma_bullish"] = "PASS"

    # Filter 7
    strong_min = _make_minute_fixture(strong=True)
    weak_min = _make_minute_fixture(strong=False)
    # 不提供 index 时也应 True
    assert filter_intraday_strength(strong_min).passed, "强势分时应通过（无指数）"
    assert not filter_intraday_strength(weak_min).passed, "弱势分时不应通过"
    result["intraday_strength"] = "PASS"

    # Filter 8
    assert filter_pullback_to_vwap(strong_min).passed, "回踩均价不破应通过"
    result["pullback_to_vwap"] = "PASS"

    return result
