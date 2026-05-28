#!/usr/bin/env python3
"""A 股主板中短线爆发力 Pro Scanner - CLI 入口。

按"团队炒股方案"§2.1–§2.2 的三共振（题材/资金/技术）逻辑筛选候选股池，
输出 Markdown 报告（含大盘速览、板块热度、候选股一览表、个股深度详情）。

⚠️ 仅作为筛选工具：候选池**不构成投资建议**，明天涨跌仍由市场决定。
所有标的必须按方案 §3 SOP 进行人工复核，并按 §5 风控严格执行止损。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stock_picker.config import get_output_dir, load_config
from stock_picker.scanner_pro.report import build_full_report, save_report
from stock_picker.scanner_pro.runner import run_scanner_pro


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A 股主板中短线爆发力 Pro Scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scan_pro.py                          # 使用默认配置
  python scan_pro.py -n 20                    # 输出 Top 20 候选股
  python scan_pro.py --deep-n 80              # 深度分析前 80 只
  python scan_pro.py -c my_config.yaml        # 自定义配置
  python scan_pro.py -o ./my_reports          # 自定义输出目录
""",
    )
    parser.add_argument("-c", "--config", help="配置文件路径", default=None)
    parser.add_argument(
        "-n", "--top-n", type=int, default=None,
        help="输出候选股数量（默认 15）",
    )
    parser.add_argument(
        "--deep-n", type=int, default=None,
        help="进入深度分析的候选股数量（默认 60，越大越慢）",
    )
    parser.add_argument(
        "-o", "--output-dir", default=None,
        help="报告输出目录（默认 ./reports）",
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="不保存到文件，仅打印",
    )

    args = parser.parse_args()

    config = load_config(args.config)
    config.setdefault("scanner_pro", {})
    if args.top_n is not None:
        config["scanner_pro"]["top_n"] = args.top_n
    if args.deep_n is not None:
        config["scanner_pro"]["deep_analyze_top_n"] = args.deep_n

    try:
        result = run_scanner_pro(config, verbose=True)
    except KeyboardInterrupt:
        print("\n⚠ 已中止")
        sys.exit(130)

    candidates = result["candidates"]
    if not candidates:
        print("\n⚠ 未筛出符合条件的候选股，请调整 scanner_pro 配置后重试。")
        return

    report = build_full_report(
        candidates,
        result["market"],
        result["timestamp"],
    )

    print("\n" + "=" * 70)
    print(f"  候选股 Top {len(candidates)}（综合分排序）")
    print("=" * 70)
    for i, c in enumerate(candidates, 1):
        comp = c["composite"]
        spot = c["spot"]
        sector = comp["theme"].get("best_sector") or "-"
        print(
            f"  {i:>2}. {c['code']} {c['name'][:8]:<8} "
            f"现价 {spot.get('close'):>6.2f}  "
            f"涨跌 {spot.get('pct_change', 0):+.2f}%  "
            f"综合 {comp['total']:>5.1f}  "
            f"技 {comp['tech']['score']:>5.1f}  "
            f"资 {comp['money']['score']:>5.1f}  "
            f"题 {comp['theme']['score']:>5.1f}  "
            f"{sector}"
        )

    if not args.no_save:
        output_dir = args.output_dir or get_output_dir(config)
        path = save_report(
            report, output_dir, prefix="scanner_pro",
            timestamp=result["timestamp"],
        )
        print(f"\n📄 Markdown 报告已保存：{path}")
        print(f"   大小：{path.stat().st_size / 1024:.1f} KB")
    print(
        "\n⚠ 重要提醒：\n"
        "   1. 本报告只是按规则筛出的候选池，不保证任何标的明日上涨\n"
        "   2. 操盘手必须人工复核题材逻辑、龙虎榜席位、分时强度后再决策\n"
        "   3. 必须按方案 §5 风控严格执行止损\n"
    )


if __name__ == "__main__":
    main()
