# Overnight Momentum Strategy (OMS) / 尾盘动量隔夜策略

[中文](README.md) · [English](README.en.md)

A short-term stock picker for China A-shares using the **"buy near close, sell next morning"** overnight-momentum playbook. Eight filters select the strongest small-to-mid-cap momentum names at 14:30, holding overnight to capture next-day opening-gap profits.

Strategy reference: [`strategy.txt`](strategy.txt)

---

## Features

- **Live scan** — one-shot filter of today's candidates at 14:30 (full 8-step pipeline)
- **Historical backtest** — given a date range, compute signals + win rate / mean return / drawdown
- **Offline selftest** — verify all 8 filters with synthetic data, no network needed
- **Three delivery modes** — Python source, venv dev, single-file `oms.exe`
- **Persistent results** — console table + one CSV per day + log file
- **Centralized tuning** — all thresholds live in `config.py`

## The 8 filters

| # | Rule | Threshold | Data |
|---|------|-----------|------|
| 1 | Daily change range | 3% – 5% | Live snapshot |
| 2 | Volume ratio | > 1 | Live snapshot |
| 3 | Turnover range | 5% – 10% | Live snapshot |
| 4 | Float market cap range | 5B – 20B CNY | Live snapshot |
| 5 | Sustained volume expansion | 5-day avg vol > 20-day avg × 1.2 | Daily K-line |
| 6 | Bullish MA alignment | MA5 > MA10 > MA20 > MA60, close > MA5 | Daily K-line |
| 7 | Intraday strength | ≥80% of day above VWAP AND outperforms SSE index | 1-min bars |
| 8 | Pullback-to-VWAP hold | New high in 14:00–14:55 then pullback within ±0.5% of VWAP | 1-min bars |

## Quick start

### Option A: Prebuilt exe (end users)

1. Grab `oms.exe` (build instructions below) and drop it anywhere.
2. Run from terminal:

```cmd
oms.exe selftest
oms.exe scan --stage coarse --top 20
oms.exe scan
oms.exe backtest --start 20260401 --end 20260418
```

First run auto-creates `output/` and `logs/` next to the binary.

### Option B: Run from source (developers)

```cmd
git clone <this-repo>
cd overnight_momentum_strategy
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python main.py selftest
```

## Commands

```cmd
# Live scan (best run after 14:30)
oms.exe scan                          # Full 8 steps
oms.exe scan --stage coarse           # Filters 1-4 only (pre/post-market sanity)
oms.exe scan --stage no-intraday      # Through filter 6 (if intraday data unavailable)
oms.exe scan --top 20 --no-save       # Preview top 20 without writing CSV

# Backtest
oms.exe backtest --start 20260401 --end 20260418
oms.exe backtest --start 20260401 --end 20260418 --sell open
oms.exe backtest --start 20260401 --end 20260418 --limit 500

# Offline selftest
oms.exe selftest
```

## Output

- **Console** — GitHub-styled candidate table
- **CSV** — `output/scan_YYYYMMDD.csv`, one per day (re-runs on the same day overwrite)
- **Backtest CSV** — `output/backtest_<start>_<end>_<sell>.csv`
- **Logs** — `logs/oms_YYYYMMDD.log`

## Build the exe yourself

```cmd
build.bat
```

Or manually:

```cmd
venv\Scripts\pyinstaller oms.spec --clean --noconfirm
```

Artifact: `dist\oms.exe` (~80 MB single-file with Python runtime + full akshare deps).

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
| `MAX_WORKERS` | Concurrent fetch threads (lower if rate-limited) |
| `REQUEST_INTERVAL` | Min seconds between requests |

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
│   ├── data.py           akshare wrappers (cache + throttle + retry)
│   ├── filters.py        The 8 filters
│   ├── selector.py       Live-scan orchestrator
│   ├── backtest.py       Backtest engine
│   ├── selftest.py       Offline self-check
│   └── utils.py          Logging / symbol normalize / MA
├── output/               CSV output
└── logs/                 Logs
```

## Known limitations

1. **Intraday data covers recent ~5 trading days only** — `stock_zh_a_hist_min_em` / `index_zh_a_hist_min_em` do not return far history
   - Live scan: filters 7/8 work normally
   - Backtest: filters 7/8 **unavailable**, degrades to daily-line approximation of 1-6
2. **Float MV approximation** — backtest uses *current* float MV as a proxy for historical values; error grows for volatile small caps
3. **ST / suspended / IPO** — data layer filters ST names and suspended tickers; new listings with <60 daily bars are auto-excluded by filter 6
4. **Limit-up boards** — daily change > 5% is naturally excluded by filter 1
5. **Non-trading days** — intraday data is empty, causing filters 7/8 to fail; use `--stage no-intraday` to bypass

## Troubleshooting

### `RemoteDisconnected` / `Connection aborted`

**Cause**: Eastmoney rate-limits scraping IPs. This is a long-standing akshare issue ([#6986](https://github.com/akfamily/akshare/issues/6986), [#7011](https://github.com/akfamily/akshare/issues/7011)), not a bug in this project.

**Fixes** (fastest to slowest):

1. Wait 10–60 min — rate limits usually auto-release
2. Change network / VPN / IP
3. Lower concurrency: set `MAX_WORKERS = 1` and `REQUEST_INTERVAL = 1.0` in `config.py`
4. Upgrade akshare: `pip install --upgrade akshare`
5. Use offline mode `oms selftest` to verify logic correctness

### Garbled Chinese in console

Windows defaults to GBK. We force stdout to UTF-8 in `utils.py`. If still garbled:

```cmd
chcp 65001
oms scan
```

## Disclaimer

For quantitative research and learning only. Chinese equity markets are highly uncertain; historical results ≠ future performance. Validate thoroughly before live trading. Use at your own risk.

## License

MIT
