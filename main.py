"""Overnight Momentum Strategy — CLI 入口。

用法:
  python main.py scan                              # 实时扫描（8 步全流程）
  python main.py scan --stage coarse               # 仅跑 filter 1-4（非交易时段验证）
  python main.py scan --stage no-intraday          # 跑到 filter 6 为止
  python main.py scan --top 20 --no-save
  python main.py backtest --start 20260401 --end 20260418
  python main.py backtest --start 20260401 --end 20260418 --sell open --limit 500
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from src.backtest import backtest
from src.selector import scan
from src.selftest import run_selftest
from src.utils import ensure_dirs, print_candidates_table, save_csv, setup_logger


def cmd_scan(args: argparse.Namespace) -> int:
    logger = setup_logger()
    ensure_dirs()
    logger.info("=== 实时扫描开始（stage=%s）===", args.stage)
    df = scan(stage=args.stage, top=args.top)
    print_candidates_table(df)
    if df is None or df.empty:
        logger.info("无候选股票")
        return 0
    if not args.no_save:
        fname = f"scan_{datetime.now():%Y%m%d}.csv"
        path = save_csv(df, fname)
        logger.info("已保存 %s（%d 只，同日覆盖写入）", path, len(df))
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    logger = setup_logger()
    logger.info("=== 离线自检开始（合成数据）===")
    results = run_selftest()
    for k, v in results.items():
        logger.info("  %s: %s", k, v)
    logger.info("全部过滤器逻辑验证通过 ✓")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    logger = setup_logger()
    ensure_dirs()
    logger.info("=== 回测开始 %s ~ %s ===", args.start, args.end)
    df, summary = backtest(
        start=args.start,
        end=args.end,
        sell_point=args.sell,
        universe_limit=args.limit,
    )
    print("\n===== 回测汇总 =====")
    for k, v in summary.items():
        print(f"  {k:20s} : {v}")
    print("====================\n")

    if df is None or df.empty:
        logger.info("回测无信号")
        return 0

    fname = f"backtest_{args.start}_{args.end}_{args.sell}.csv"
    path = save_csv(df, fname)
    logger.info("明细已保存 %s（%d 条）", path, len(df))
    # 前 20 条预览
    print_candidates_table(df.head(20))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="oms",
        description="Overnight Momentum Strategy 选股程序（A 股）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="实时扫描当日候选股")
    p_scan.add_argument(
        "--stage",
        choices=["coarse", "no-intraday", "full"],
        default="full",
        help="coarse=仅 filter 1-4；no-intraday=跑到 filter 6；full=全 8 步（默认）",
    )
    p_scan.add_argument("--top", type=int, default=None, help="仅展示前 N 只")
    p_scan.add_argument("--no-save", action="store_true", help="不保存 CSV")
    p_scan.set_defaults(func=cmd_scan)

    p_bt = sub.add_parser("backtest", help="历史回测")
    p_bt.add_argument("--start", required=True, help="起始日期 YYYYMMDD")
    p_bt.add_argument("--end", required=True, help="结束日期 YYYYMMDD")
    p_bt.add_argument(
        "--sell",
        choices=["open", "close", "high"],
        default="close",
        help="次日卖点，默认 close",
    )
    p_bt.add_argument("--limit", type=int, default=None, help="股票池上限（调试）")
    p_bt.set_defaults(func=cmd_backtest)

    p_st = sub.add_parser("selftest", help="离线自检（合成数据验证过滤器逻辑）")
    p_st.set_defaults(func=cmd_selftest)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
