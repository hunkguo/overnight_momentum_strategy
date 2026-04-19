# 尾盘动量隔夜策略 / Overnight Momentum Strategy (OMS)

[中文](README.md) · [English](README.en.md)

基于 A 股的「当日 14:30 尾盘买入、次日冲高卖出」短线选股程序。核心逻辑是通过 8 条规则筛选出当日动量最强的一批中小市值活跃股，利用隔夜情绪惯性在 T+1 日获利了结。

策略原文：[`strategy.txt`](strategy.txt)

---

## 功能特性

- **实时扫描**：14:30 盘中一键筛选当日候选股（8 步全流程）
- **历史回测**：给定日期区间批量测算策略信号 + 胜率 / 平均收益 / 最大盈亏
- **离线自检**：无网络时用合成数据验证 8 个过滤器逻辑
- **三端交付**：Python 源码、venv 开发、一键打包为单文件 `oms.exe`
- **结果持久化**：控制台表格 + 每日单份 CSV + 日志文件
- **集中调参**：所有阈值在 `config.py` 统一管理

## 8 步筛选规则

| # | 规则 | 阈值 | 数据来源 |
|---|------|------|---------|
| 1 | 涨跌幅区间 | 3% ~ 5% | 实时快照 |
| 2 | 量比 | > 1 | 实时快照 |
| 3 | 换手率区间 | 5% ~ 10% | 实时快照 |
| 4 | 流通市值区间 | 50 ~ 200 亿 | 实时快照 |
| 5 | 持续放量（台阶式） | 近 5 日均量 > 近 20 日均量 × 1.2 | 日 K 线 |
| 6 | 均线多头排列 | MA5 > MA10 > MA20 > MA60，收盘 > MA5 | 日 K 线 |
| 7 | 分时强势 | 全天 ≥80% 时间价 > 均价，且强于上证指数 | 1 分钟分时 |
| 8 | 回踩均价线不破 | 14:00–14:55 创新高后回踩均价 ±0.5% 未破 | 1 分钟分时 |

## 快速开始

### 方式 A：使用预编译 exe（推荐给普通用户）

1. 下载 `oms.exe`（自行构建见下文），放到任意目录
2. 命令行运行：

```cmd
oms.exe selftest
oms.exe scan --stage coarse --top 20
oms.exe scan
oms.exe backtest --start 20260401 --end 20260418
```

首次运行会在同目录创建 `output/` 与 `logs/`。

### 方式 B：从源码运行（推荐给开发者）

```cmd
git clone <this-repo>
cd overnight_momentum_strategy
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python main.py selftest
```

## 命令参考

```cmd
# 实时扫描（建议 14:30 后运行）
oms.exe scan                          # 完整 8 步
oms.exe scan --stage coarse           # 仅 1-4（盘前盘后验证用）
oms.exe scan --stage no-intraday      # 跑到 filter 6（无分时数据时）
oms.exe scan --top 20 --no-save       # 只看前 20 且不写 CSV

# 历史回测
oms.exe backtest --start 20260401 --end 20260418
oms.exe backtest --start 20260401 --end 20260418 --sell open
oms.exe backtest --start 20260401 --end 20260418 --limit 500

# 离线自检（无网络也能跑）
oms.exe selftest
```

## 输出

- **控制台**：github 风格候选表格
- **CSV**：`output/scan_YYYYMMDD.csv` 每日一份（同日重复运行覆盖写）
- **回测 CSV**：`output/backtest_<起>_<止>_<卖点>.csv`
- **日志**：`logs/oms_YYYYMMDD.log`

## 自行打包 exe

```cmd
build.bat
```

或手动：

```cmd
venv\Scripts\pyinstaller oms.spec --clean --noconfirm
```

产物：`dist\oms.exe`（约 80 MB 的单文件，含 Python 运行时与 akshare 完整依赖）。

## 调参

修改 [`config.py`](config.py) 中的阈值：

| 变量 | 说明 |
|------|------|
| `CHANGE_LOW` / `CHANGE_HIGH` | 涨跌幅区间 % |
| `VOLUME_RATIO_MIN` | 量比下限 |
| `TURNOVER_LOW` / `TURNOVER_HIGH` | 换手率区间 % |
| `FLOAT_MV_LOW` / `FLOAT_MV_HIGH` | 流通市值区间（元）|
| `VOLUME_STACK_RATIO` | 放量判定阈值 |
| `INTRADAY_ABOVE_VWAP_RATIO` | 分时强势占比阈值 |
| `MAX_WORKERS` | 并发拉取线程数（限流严重时调小）|
| `REQUEST_INTERVAL` | 请求最小间隔秒 |

改完源码后需要 `build.bat` 重新打包。

## 项目结构

```
overnight_momentum_strategy/
├── strategy.txt          策略原始说明
├── config.py             阈值集中配置
├── main.py               CLI 入口
├── oms.spec              PyInstaller 配置
├── build.bat             一键打包
├── requirements.txt      Python 依赖
├── src/
│   ├── data.py           akshare 封装（缓存 + 限流节流 + 重试）
│   ├── filters.py        8 步过滤器
│   ├── selector.py       实时扫描编排
│   ├── backtest.py       回测引擎
│   ├── selftest.py       离线自检
│   └── utils.py          日志 / 代码标准化 / MA
├── output/               CSV 输出
└── logs/                 日志
```

## 已知限制

1. **分时数据仅近期可用**：`stock_zh_a_hist_min_em` / `index_zh_a_hist_min_em` 只返回最近约 5 个交易日的 1 分钟数据
   - 实时扫描：filter 7/8 正常
   - 回测：filter 7/8 **不可用**，退化为 filter 1-6 的日线近似
2. **流通市值近似**：回测用「当前」流通市值近似历史市值，小股本股票误差更大
3. **ST / 停牌 / 新股**：数据层已过滤 ST 与停牌；新股因日线不足 60 根被 filter 6 自动排除
4. **涨停板**：涨跌幅 > 5% 被 filter 1 自然排除
5. **非交易日**：扫描时分时为空导致 filter 7/8 失败，用 `--stage no-intraday` 回避

## 故障排查

### `RemoteDisconnected` / `Connection aborted`

**原因**：东方财富对高频请求 IP 限流（akshare 长期已知问题，见 [akshare#6986](https://github.com/akfamily/akshare/issues/6986)、[#7011](https://github.com/akfamily/akshare/issues/7011)）。

**对策**（生效从快到慢）：

1. 等 10–60 分钟后自动解除
2. 换 IP / 开 VPN / 切换网络
3. 降低并发：`config.py` 中 `MAX_WORKERS = 1`，`REQUEST_INTERVAL = 1.0`
4. 升级 akshare：`pip install --upgrade akshare`
5. 改用离线模式 `oms selftest` 验证代码正确

### 中文乱码

Windows 默认控制台是 GBK。已在 `utils.py` 强制 stdout 为 UTF-8。若仍乱码：

```cmd
chcp 65001
oms scan
```

## 免责声明

本项目仅用于量化学习与策略研究。A 股市场高度不确定，历史收益 ≠ 未来表现。实盘前请自行充分验证，据此操作风险自负。

## License

MIT
