"""Overnight Momentum Strategy — CLI 入口。

基于 TdxQuant（通达信本地终端）获取数据。首次运行前请先：
  1) 启动通达信金融终端并确认「TQ 策略」菜单就绪；
  2) 核对 config.TDX_USER_PATH 指向正确的 PYPlugins/user 目录；
  3) 在「TQ 策略 → TQ 数据设置 → 盘后数据下载」补齐近 30 天日线数据。

用法:
  python main.py scan                              # 实时扫描（8 步全流程）
  python main.py scan --stage coarse               # 仅跑 filter 1-4
  python main.py scan --stage no-intraday          # 跑到 filter 6
  python main.py scan --top 20 --push-block --notify
  python main.py backtest --start 20260301 --end 20260418
  python main.py backtest --start 20260301 --end 20260418 --sell open --limit 500
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from config import PUSH_BLOCK_CODE, PUSH_BLOCK_NAME
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
        if args.notify:
            from src.tdx_data import init_tq, send_message
            init_tq()
            send_message(f"{datetime.now():%H:%M} OMS 扫描无候选")
        return 0
    if not args.no_save:
        fname = f"scan_{datetime.now():%Y%m%d}.csv"
        path = save_csv(df, fname)
        logger.info("已保存 %s（%d 只，同日覆盖写入）", path, len(df))

    if args.push_block:
        from src.tdx_data import init_tq, send_to_block
        init_tq()
        send_to_block(df["code"].tolist(), PUSH_BLOCK_CODE, PUSH_BLOCK_NAME)

    if args.notify:
        from src.tdx_data import init_tq, send_message
        init_tq()
        top3 = ",".join(df["code"].head(3).tolist())
        send_message(
            f"{datetime.now():%H:%M} OMS 命中 {len(df)} 只，前 3：{top3}"
        )
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
    print_candidates_table(df.head(20))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="oms",
        description="Overnight Momentum Strategy 选股程序（A 股 / TdxQuant）",
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
    p_scan.add_argument(
        "--push-block",
        action="store_true",
        help=f"把结果写入 TDX 自定义板块（{PUSH_BLOCK_CODE}/{PUSH_BLOCK_NAME}）",
    )
    p_scan.add_argument(
        "--notify",
        action="store_true",
        help="通过 tq.send_message 向 TQ 策略管理器发消息",
    )
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
