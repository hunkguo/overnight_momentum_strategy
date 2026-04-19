# Overnight Momentum Strategy (OMS) / 尾盘动量隔夜策略

[中文](README.md) · [English](README.en.md)

A short-term stock picker for China A-shares using the **"buy near close, sell next morning"** overnight-momentum playbook. Eight filters select the strongest small-to-mid-cap momentum names at 14:30, holding overnight to capture next-day opening-gap profits.

Data layer is powered by [**TdxQuant** (Tongdaxin's official Python quant framework)](https://help.tdx.com.cn/quant/) — every quote is served directly from the local terminal DLL, eliminating the rate-limits and IP-ban headaches of public HTTP scraping.

Strategy reference: [`strategy.txt`](strategy.txt)

---

## Features

- **Live scan** — one-shot filter of today's candidates at 14:30 (full 8-step pipeline)
- **Batch-efficient** — a single `tq.get_market_data` call streams the entire universe's daily K-lines; post-coarse-filter tickers are processed in seconds
- **Historical backtest** — signals + win rate / mean return / drawdown over any date range
- **Offline selftest** — verify all 8 filters with synthetic data, no terminal needed
- **Terminal integration** — optional `--push-block` writes the picks into a custom sector; `--notify` posts a message
- **Persistent results** — console table + one CSV per day + log file
- **Centralized tuning** — all thresholds live in `config.py`

## The 8 filters

| # | Rule | Threshold | Data |
|---|------|-----------|------|
| 1 | Daily change range | 3% – 5% | `tq.get_market_data` daily K (T / T-1 close) |
| 2 | Volume ratio | > 1 | `tq.get_market_data` daily K (T vol / prior 5-day avg) |
| 3 | Turnover range | 5% – 10% | Daily volume / `tq.get_stock_info` float share |
| 4 | Float market cap range | 5B – 20B CNY | `tq.get_stock_info` float share × close |
| 5 | Sustained volume expansion | 5-day avg vol > 20-day avg × 1.2 | `tq.get_market_data` 1d |
| 6 | Bullish MA alignment | MA5 > MA10 > MA20 > MA60, close > MA5 | `tq.get_market_data` 1d |
| 7 | Intraday strength | ≥80% of day above VWAP AND outperforms SSE index | `tq.get_market_data` 1m |
| 8 | Pullback-to-VWAP hold | New high in 14:00–14:55 then pullback within ±0.5% of VWAP | `tq.get_market_data` 1m |

## Prerequisites

### 1. Install Tongdaxin terminal

Download a TQ-strategy-capable build from the [official site](https://www.tdx.com.cn/soft.html) (e.g. 专业研究 / 量化模拟版 / 期货通). Launch it — if the top menu shows "TQ 策略" you're set.

### 2. Confirm the TDX path

Default in `config.py`: `TDX_USER_PATH = "D:/new_tdx64/PYPlugins/user"`. Point this at your actual installation's `PYPlugins/user` folder.

> No custom formula needs to be saved in the formula editor — the current `tdx_data.py` computes the spot snapshot locally from `tq.get_market_data` (daily K) + `tq.get_stock_info` (float share).

## Quick start

```cmd
git clone <this-repo>
cd overnight_momentum_strategy
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python main.py selftest               # terminal not required
```

With the terminal running:

```cmd
venv\Scripts\python main.py scan --stage coarse --top 20
venv\Scripts\python main.py scan                              # full 8 steps
venv\Scripts\python main.py scan --push-block --notify        # push to terminal
venv\Scripts\python main.py backtest --start 20260301 --end 20260418
```

## Commands

```cmd
# Live scan (best run after 14:30)
python main.py scan                          # Full 8 steps
python main.py scan --stage coarse           # Filters 1-4 only
python main.py scan --stage no-intraday      # Through filter 6
python main.py scan --top 20 --no-save       # Preview top 20 without CSV
python main.py scan --push-block             # Write results into a TDX custom sector
python main.py scan --notify                 # Push a message to TQ strategy manager

# Backtest
python main.py backtest --start 20260301 --end 20260418
python main.py backtest --start 20260301 --end 20260418 --sell open
python main.py backtest --start 20260301 --end 20260418 --limit 500

# Offline selftest (no terminal needed)
python main.py selftest
```

## Output

- **Console** — GitHub-styled candidate table
- **CSV** — `output/scan_YYYYMMDD.csv`, one per day
- **Backtest CSV** — `output/backtest_<start>_<end>_<sell>.csv`
- **Logs** — `logs/oms_YYYYMMDD.log`
- **TDX custom sector** (`--push-block`) — `OMS - 尾盘动量隔夜`, browse with F3 in the terminal
- **TDX popup message** (`--notify`) — TQ strategy-manager message center

## Build the exe yourself

```cmd
build.bat
```

Or manually:

```cmd
venv\Scripts\pyinstaller oms.spec --clean --noconfirm
```

Artifact: `dist\oms.exe`. The target machine still needs Tongdaxin installed (TQ strategy ready — no custom formula required).

## Tuning

Edit [`config.py`](config.py):

| Variable | Meaning |
|----------|---------|
| `CHANGE_LOW` / `CHANGE_HIGH` | Daily change range (%) |
| `VOLUME_RATIO_MIN` | Min volume ratio |
| `TURNOVER_LOW` / `TURNOVER_HIGH` | Turnover range (%) |
| `FLOAT_MV_LOW` / `FLOAT_MV_HIGH` | Float MV range (CNY) |
| `VOLUME_STACK_RATIO` | Volume expansion threshold |
| `INTRADAY_ABOVE_VWAP_RATIO` | Intraday strength threshold |
| `TDX_USER_PATH` | Tongdaxin `PYPlugins/user` directory |
| `UNIVERSE_MODE` / `UNIVERSE_MARKET` / `UNIVERSE_SECTOR` | Universe source |
| `PUSH_BLOCK_CODE` / `PUSH_BLOCK_NAME` | Push-to-sector code / name |
| `INDEX_SYMBOL` | Filter 7 comparison index, default 999999.SH |

Re-run `build.bat` after editing to refresh the exe.

## Project layout

```
overnight_momentum_strategy/
├── strategy.txt          Original strategy notes
├── config.py             All thresholds
├── main.py               CLI entry
├── oms.spec              PyInstaller config
├── build.bat             One-click build
├── requirements.txt      Python deps
├── src/
│   ├── tdx_data.py       TdxQuant wrappers (spot / daily / minute / push)
│   ├── filters.py        The 8 filters
│   ├── selector.py       Live-scan orchestrator
│   ├── backtest.py       Backtest engine
│   ├── selftest.py       Offline self-check
│   └── utils.py          Logging / symbol normalize / MA / TDX code helpers
├── output/               CSV output
└── logs/                 Logs
```

## Known limitations

1. **The Tongdaxin terminal must be running** — all data comes from local DLLs (`TPythClient.dll` / `tdxrpcx64.dll`).
2. **Backtest turnover / float-MV are approximated** using the current snapshot; turnover is skipped entirely in backtest for now. Small caps have larger error. You can extend `src/tdx_data.py` with `tq.formula_process_mul_zb` + `FINANCE(7)` for true historical values.
3. **Backtest does not run filters 7/8** — although historical 1-min data is available in TdxQuant, those filters assume the 14:30 intraday scene, which is semantically ambiguous in a backtest.
4. **ST / suspended / IPO** — new listings with <60 daily bars are auto-excluded by filter 6. ST names are filtered by `tdx_data.get_spot` based on their stock name; alternatively point `config.UNIVERSE_SECTOR` at a TDX sector that already excludes them.
5. **Limit-up boards** — daily change > 5% is naturally excluded by filter 1.

## Troubleshooting

### `FileNotFoundError: ... TPythClient.dll`

Its dependency `tdxrpcx64.dll` is missing (usually quarantined by AV). Check `<TDX>/PYPlugins/` for `tdxrpcx64.dll`; reinstall or whitelist if absent.

### `Cannot import tqcenter`

Check `config.TDX_USER_PATH` — it must point to the actual `PYPlugins/user` inside your Tongdaxin install directory.

### `tq.initialize failed` / `TQ 策略` menu spinner stuck

1. Confirm your Tongdaxin build supports TQ strategies (专业研究 / 量化模拟版);
2. Allow firewall access for the terminal;
3. Check whether AV is blocking `tdxrpcx64.dll`.

### `spot empty` / `get_market_data returned empty`

Open Tongdaxin → **TQ 策略 → TQ 数据设置 → 盘后数据下载 → 日线数据** and download at least the last 30 trading days. If the last two daily K bars are more than 5 days apart, `tdx_data.get_spot` raises with an explicit message asking you to refill history.

### Garbled Chinese in console

Windows defaults to GBK. We force stdout to UTF-8 in `utils.py`. If still garbled:

```cmd
chcp 65001
python main.py scan
```

## Disclaimer

For quantitative research and learning only. Chinese equity markets are highly uncertain; historical results ≠ future performance. Validate thoroughly before live trading. Use at your own risk.

## License

MIT
