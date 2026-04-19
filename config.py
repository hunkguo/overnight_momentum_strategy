"""Overnight Momentum Strategy 参数配置。

所有可调阈值集中在此处，便于统一调参。各参数对应 strategy.txt 的 8 步筛选。
"""
from __future__ import annotations

# ---- Filter 1: 涨跌幅区间（%）----
CHANGE_LOW: float = 3.0
CHANGE_HIGH: float = 5.0

# ---- Filter 2: 量比下限 ----
VOLUME_RATIO_MIN: float = 1.0

# ---- Filter 3: 换手率区间（%）----
TURNOVER_LOW: float = 5.0
TURNOVER_HIGH: float = 10.0

# ---- Filter 4: 流通市值区间（元）----
FLOAT_MV_LOW: float = 50e8
FLOAT_MV_HIGH: float = 200e8

# ---- Filter 5: 持续放量判断 ----
VOLUME_STACK_DAYS: int = 5          # 近 N 日均量与长期均量对比窗口
VOLUME_LONG_DAYS: int = 20          # 长期均量窗口
VOLUME_STACK_RATIO: float = 1.2     # 近期均量 / 长期均量 > 该阈值视为放量

# ---- Filter 6: 均线多头排列 ----
MA_PERIODS: tuple[int, ...] = (5, 10, 20, 60)

# ---- Filter 7: 分时强势 ----
INTRADAY_ABOVE_VWAP_RATIO: float = 0.8   # 当日 ≥ 该比例时间 股价 > 均价线

# ---- Filter 8: 回踩均价线不破 ----
PULLBACK_TOLERANCE: float = 0.005        # 回踩允许误差 0.5%
PULLBACK_WINDOW_START: str = "14:00"     # 观察窗口起点
PULLBACK_WINDOW_END: str = "14:55"

# ---- TdxQuant 环境 ----
# tqcenter.py 所在目录：<通达信安装目录>/PYPlugins/user
TDX_USER_PATH: str = "D:/new_tdx64/PYPlugins/user"

# ---- 股票池 ----
# 'market' → tq.get_stock_list(market=UNIVERSE_MARKET)
# 'sector' → tq.get_stock_list_in_sector(UNIVERSE_SECTOR)
UNIVERSE_MODE: str = "market"
UNIVERSE_MARKET: str = "5"               # 5 = 沪深 A 股全部
UNIVERSE_SECTOR: str = "沪深A股"          # UNIVERSE_MODE='sector' 时使用

# ---- 自定义板块（--push-block 开启时生效）----
PUSH_BLOCK_CODE: str = "OMS"
PUSH_BLOCK_NAME: str = "尾盘动量隔夜"

# ---- 指数代码（filter 7 对比大盘用）----
# 上证指数：通达信传统代码 999999.SH；若你的版本用新代码可改为 000001.SH
INDEX_SYMBOL: str = "999999.SH"

# ---- 数据拉取 ----
KLINE_DAYS: int = 120                    # 日 K 线回溯天数（覆盖 MA60）

# ---- 输出目录 ----
OUTPUT_DIR: str = "output"
LOG_DIR: str = "logs"
