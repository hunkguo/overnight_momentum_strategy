# 尾盘动量隔夜策略 / Overnight Momentum Strategy (OMS)

[中文](README.md) · [English](README.en.md)

基于 A 股的「当日 14:30 尾盘买入、次日冲高卖出」短线选股程序。核心逻辑是通过 8 条规则筛选出当日动量最强的一批中小市值活跃股，利用隔夜情绪惯性在 T+1 日获利了结。

数据层基于 [**TdxQuant（通达信金融终端 Python 量化框架）**](https://help.tdx.com.cn/quant/)，所有行情直接走本地 DLL，不再依赖任何公网数据源，也不再受限流 / IP 封禁困扰。

策略原文：[`strategy.txt`](strategy.txt)

---

## 功能特性

- **实时扫描**：14:30 盘中一键筛选当日候选股（8 步全流程）
- **批量高效**：`tq.get_market_data` 一次拉完全市场日 K，粗筛后的剩余股票秒级精筛
- **历史回测**：给定日期区间批量测算策略信号 + 胜率 / 平均收益 / 最大盈亏
- **离线自检**：无终端时用合成数据验证 8 个过滤器逻辑
- **终端联动**：可选 `--push-block` 把候选股写入自定义板块，`--notify` 弹出消息
- **结果持久化**：控制台表格 + 每日单份 CSV + 日志文件
- **集中调参**：所有阈值在 `config.py` 统一管理

## 8 步筛选规则

| # | 规则 | 阈值 | 数据来源 |
|---|------|------|---------|
| 1 | 涨跌幅区间 | 3% ~ 5% | `tq.get_market_data` 日线（T / T-1 收盘）|
| 2 | 量比 | > 1 | `tq.get_market_data` 日线（T 日量 / 前 5 日均量）|
| 3 | 换手率区间 | 5% ~ 10% | 日线成交量 / `tq.get_stock_info` 流通股本 |
| 4 | 流通市值区间 | 50 ~ 200 亿 | `tq.get_stock_info` 流通股本 × 收盘价 |
| 5 | 持续放量（台阶式） | 近 5 日均量 > 近 20 日均量 × 1.2 | `tq.get_market_data` 日线 |
| 6 | 均线多头排列 | MA5 > MA10 > MA20 > MA60，收盘 > MA5 | `tq.get_market_data` 日线 |
| 7 | 分时强势 | 全天 ≥80% 时间价 > 均价，且强于上证指数 | `tq.get_market_data` 1m |
| 8 | 回踩均价线不破 | 14:00–14:55 创新高后回踩均价 ±0.5% 未破 | `tq.get_market_data` 1m |

## 前置准备

### 1. 安装通达信金融终端

从 [通达信官网](https://www.tdx.com.cn/soft.html) 下载支持「TQ 策略」功能的版本（专业研究、量化模拟版或期货通等），安装后启动，菜单栏出现「TQ 策略」即表示成功。

### 2. 确认 TDX 路径

默认 `config.py` 里 `TDX_USER_PATH = "D:/new_tdx64/PYPlugins/user"`，如果你的终端装在别处，改成对应路径的 `PYPlugins/user` 目录。

> 无需在公式编辑器建立任何自定义指标 —— 新版 `tdx_data.py` 的 spot 快照完全由 `tq.get_market_data`（日 K）+ `tq.get_stock_info`（流通股本）在本地算出。

## 快速开始

```cmd
git clone <this-repo>
cd overnight_momentum_strategy
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python main.py selftest               # 无终端也能跑，验证代码逻辑
```

终端准备好后（保持常驻）：

```cmd
venv\Scripts\python main.py scan --stage coarse --top 20     # 粗筛
venv\Scripts\python main.py scan                              # 完整 8 步
venv\Scripts\python main.py scan --push-block --notify        # 并推送到终端
venv\Scripts\python main.py backtest --start 20260301 --end 20260418
```

## 命令参考

```cmd
# 实时扫描（建议 14:30 后运行）
python main.py scan                          # 完整 8 步
python main.py scan --stage coarse           # 仅 1-4（盘前盘后验证用）
python main.py scan --stage no-intraday      # 跑到 filter 6（盘外时段）
python main.py scan --top 20 --no-save       # 只看前 20 且不写 CSV
python main.py scan --push-block             # 结果写入 TDX 自定义板块
python main.py scan --notify                 # 向 TQ 策略管理器发通知

# 历史回测
python main.py backtest --start 20260301 --end 20260418
python main.py backtest --start 20260301 --end 20260418 --sell open
python main.py backtest --start 20260301 --end 20260418 --limit 500

# 离线自检（无需通达信运行）
python main.py selftest
```

## 输出

- **控制台**：github 风格候选表格
- **CSV**：`output/scan_YYYYMMDD.csv`（每日一份，同日重复运行覆盖写）
- **回测 CSV**：`output/backtest_<起>_<止>_<卖点>.csv`
- **日志**：`logs/oms_YYYYMMDD.log`
- **TDX 自定义板块**（`--push-block`）：`OMS - 尾盘动量隔夜`，终端里 F3 可直接查看
- **TDX 弹窗消息**（`--notify`）：TQ 策略管理器消息中心

## 自行打包 exe

```cmd
build.bat
```

或手动：

```cmd
venv\Scripts\pyinstaller oms.spec --clean --noconfirm
```

产物：`dist\oms.exe`。运行机器同样需要安装通达信终端（TQ 策略就绪即可，无需自定义公式）。

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
| `TDX_USER_PATH` | 通达信 `PYPlugins/user` 目录 |
| `UNIVERSE_MODE` / `UNIVERSE_MARKET` / `UNIVERSE_SECTOR` | 股票池来源 |
| `PUSH_BLOCK_CODE` / `PUSH_BLOCK_NAME` | 推送板块代码 / 名称 |
| `INDEX_SYMBOL` | filter 7 对比指数，默认 999999.SH |

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
│   ├── tdx_data.py       TdxQuant 封装（spot/日 K/分时/推送到终端）
│   ├── filters.py        8 步过滤器
│   ├── selector.py       实时扫描编排
│   ├── backtest.py       回测引擎
│   ├── selftest.py       离线自检
│   └── utils.py          日志 / 代码标准化 / MA / TDX 代码互转
├── output/               CSV 输出
└── logs/                 日志
```

## 已知限制

1. **依赖通达信终端常驻运行**：所有数据都来自本地 TDX DLL（`TPythClient.dll` / `tdxrpcx64.dll`），脚本运行时终端必须在线。
2. **回测期的换手率 / 流通市值**：目前用「当期快照」近似历史值；换手率直接不过滤；小股本股票误差更大。如需精确历史值，可在 `src/tdx_data.py` 扩展 `tq.formula_process_mul_zb` 调 `FINANCE(7)` 历史。
3. **回测不跑 filter 7/8**：虽然 TdxQuant 历史分时可用，但这两个过滤器依赖「当日下午 2:30 的场景」，放到回测里语义模糊。
4. **ST / 停牌 / 新股**：新股因日线不足 60 根被 filter 6 自动排除；ST 在 `tdx_data.get_spot` 按股票名含 `ST` 过滤，也可在 `config.UNIVERSE_SECTOR` 改用 TDX 板块。
5. **涨停板**：涨跌幅 > 5% 被 filter 1 自然排除。

## 故障排查

### `FileNotFoundError: ... TPythClient.dll`

`TPythClient.dll` 的依赖 `tdxrpcx64.dll` 缺失（通常被杀毒软件误杀）。解决：在 `<TDX>/PYPlugins/` 下检查是否有 `tdxrpcx64.dll`，没有就重装或加白名单。

### `无法 import tqcenter`

检查 `config.TDX_USER_PATH` 是否指向实际安装目录下的 `PYPlugins/user`。

### `tq.initialize 失败` / TQ 策略菜单一直「正在开启」

1. 确认终端版本支持 TQ 策略（专业研究/量化模拟版）；
2. 允许终端访问防火墙；
3. 检查杀毒软件是否拦截 `tdxrpcx64.dll`。

### `spot 空结果` / `get_market_data 返回空`

检查通达信「TQ 策略 → TQ 数据设置 → 盘后数据下载 → 日线数据」，把至少近 30 天的日 K 下载完整；如果最近两根日 K 相距超过 5 天，`tdx_data.get_spot` 会直接抛错提示你补数据。

### 中文乱码

Windows 默认控制台是 GBK。已在 `utils.py` 强制 stdout 为 UTF-8。若仍乱码：

```cmd
chcp 65001
python main.py scan
```

## 免责声明

本项目仅用于量化学习与策略研究。A 股市场高度不确定，历史收益 ≠ 未来表现。实盘前请自行充分验证，据此操作风险自负。

## License

MIT
