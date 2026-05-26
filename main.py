#!/usr/bin/env python3
"""A股短线推荐系统 v2.0 - 主程序入口

多维度选股：技术指标 + 资金流向 + 市场情绪 + 板块概念
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from stock_picker.config import load_config, get_output_dir
from stock_picker.data_fetcher import get_all_a_stocks, filter_stocks, batch_get_history
from stock_picker.indicators import calc_all_indicators
from stock_picker.strategy import calc_composite_score, generate_reasons, calc_stop_loss
from stock_picker.report import format_report, save_report_text, save_report_csv
from stock_picker.capital_flow import get_capital_flow_rank, get_north_flow
from stock_picker.market_sentiment import calc_market_sentiment, get_index_quotes
from stock_picker.sector import get_hot_sectors


def print_progress(current: int, total: int, code: str) -> None:
    pct = current / total * 100
    bar_len = 30
    filled = int(bar_len * current // total)
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r  获取数据 |{bar}| {pct:.0f}% ({current}/{total}) {code}  ", end="", flush=True)


def run(config_path: str | None = None, top_n: int | None = None) -> list[dict]:
    """运行选股流程"""
    print("\n  A股短线推荐系统 v2.0")
    print("=" * 50)

    # 1. 加载配置
    print("\n[1/7] 加载配置...")
    config = load_config(config_path)
    if top_n:
        config.setdefault("selection", {})["top_n"] = top_n
    final_top_n = config.get("selection", {}).get("top_n", 5)
    print(f"  推荐数量: {final_top_n}")

    # 2. 获取市场概览
    print("\n[2/7] 获取市场概览...")
    market_context = {}
    try:
        indices = get_index_quotes()
        market_context["indices"] = indices
        if indices:
            for name, info in list(indices.items())[:3]:
                pct = info.get("pct_change", 0)
                sign = "+" if pct >= 0 else ""
                print(f"  {name}: {sign}{pct:.2f}%")
    except Exception as e:
        print(f"  获取指数数据失败: {e}")

    try:
        north = get_north_flow()
        market_context["north_flow"] = north
        if north.get("total", 0) != 0:
            total = north["total"]
            sign = "+" if total >= 0 else ""
            print(f"  北向资金: {sign}{total / 1e4:.2f}亿")
    except Exception:
        pass

    # 3. 获取股票列表
    print("\n[3/7] 获取A股实时行情...")
    all_stocks = get_all_a_stocks()
    print(f"  获取到 {len(all_stocks)} 只股票")

    # 计算市场情绪
    try:
        sentiment = calc_market_sentiment(all_stocks)
        market_context["sentiment"] = sentiment
        print(f"  上涨: {sentiment['up_count']}  下跌: {sentiment['down_count']}  "
              f"涨停: {sentiment['limit_up_count']}  跌停: {sentiment['limit_down_count']}")
    except Exception:
        pass

    # 4. 获取热门板块
    print("\n[4/7] 获取热门板块...")
    try:
        hot_sectors = get_hot_sectors(top_n=5)
        market_context["hot_sectors"] = hot_sectors
        for s in hot_sectors[:3]:
            pct = s.get("pct_change", 0)
            sign = "+" if pct >= 0 else ""
            print(f"  [{s.get('type', '')}] {s.get('name', '')} {sign}{pct:.2f}%  龙头: {s.get('leader_name', '')}")
    except Exception as e:
        print(f"  获取板块数据失败: {e}")

    # 5. 获取资金流向排行
    print("\n[5/7] 获取资金流向...")
    capital_flow_df = None
    try:
        capital_flow_df = get_capital_flow_rank()
        if not capital_flow_df.empty:
            print(f"  获取到 {len(capital_flow_df)} 只股票的资金流向数据")
        else:
            print("  资金流向数据暂不可用")
    except Exception as e:
        print(f"  获取资金流向失败: {e}")

    # 6. 初步筛选
    print("\n[6/7] 初步筛选...")
    filtered = filter_stocks(all_stocks, config)
    print(f"  筛选后剩余 {len(filtered)} 只股票")

    # 按量比和涨跌幅预筛选活跃股
    pre_candidates = filtered.copy()
    if "volume_ratio" in pre_candidates.columns:
        vr = pre_candidates["volume_ratio"]
        if vr.notna().any():
            pre_candidates = pre_candidates[vr.fillna(1.0) > 0.8]
    if "pct_change" in pre_candidates.columns:
        pct = pre_candidates["pct_change"]
        if pct.notna().any():
            pre_candidates = pre_candidates[
                (pct.fillna(0) > -3) & (pct.fillna(0) < 7)
            ]

    # 按量比排序取前100只
    if "volume_ratio" in pre_candidates.columns and pre_candidates["volume_ratio"].notna().any():
        pre_candidates = pre_candidates.sort_values("volume_ratio", ascending=False, na_position="last")
    elif "pct_change" in pre_candidates.columns:
        pre_candidates = pre_candidates.sort_values("pct_change", ascending=False, na_position="last")
    candidate_codes = pre_candidates["code"].head(100).tolist()
    print(f"  预筛选 {len(candidate_codes)} 只活跃股进行详细分析")

    # 7. 获取历史数据 + 计算指标 + 综合评分
    print("\n[7/7] 获取历史数据并分析...")
    data_config = config.get("data", {})
    history_data = batch_get_history(
        candidate_codes,
        days=data_config.get("history_days", 120),
        retry_times=data_config.get("retry_times", 3),
        interval=data_config.get("request_interval", 0.5),
        progress_callback=print_progress,
    )
    print(f"\n  成功获取 {len(history_data)} 只股票的历史数据")

    # 建立资金流向映射
    capital_map = {}
    if capital_flow_df is not None and not capital_flow_df.empty:
        for _, row in capital_flow_df.iterrows():
            capital_map[row["code"]] = {
                "main_net_inflow": row.get("main_net_inflow", 0),
                "super_large_net": row.get("super_large_net", 0),
                "large_net": row.get("large_net", 0),
                "main_net_pct": row.get("main_net_pct", 0),
            }

    print("  计算技术指标和综合评分...")
    results = []
    code_to_name = dict(zip(filtered["code"], filtered["name"]))
    code_to_info = {row["code"]: row for _, row in filtered.iterrows()}

    for code, hist_df in history_data.items():
        hist_df = calc_all_indicators(hist_df, config)
        score_result = calc_composite_score(hist_df, config)
        stop_loss = calc_stop_loss(hist_df)
        reasons = generate_reasons(score_result["details"])

        info = code_to_info.get(code, {})
        close_val = info.get("close", hist_df.iloc[-1]["close"]) if isinstance(info, dict) else hist_df.iloc[-1]["close"]
        pct_val = info.get("pct_change", 0) if isinstance(info, dict) else 0

        # 资金流向加分
        total_score = score_result["total_score"]
        cf = capital_map.get(code)
        if cf:
            main_net = cf.get("main_net_inflow", 0)
            if main_net and main_net > 0:
                total_score += min(main_net / 1e8 * 5, 10)
                reasons.append(f"  主力资金净流入 {main_net / 1e4:.0f}万")

        results.append({
            "code": code,
            "name": code_to_name.get(code, "未知"),
            "close": float(close_val) if close_val is not None else 0,
            "pct_change": float(pct_val) if pct_val is not None else 0,
            "score": total_score,
            "score_details": score_result["details"],
            "reasons": reasons,
            "stop_loss_info": stop_loss,
            "capital_flow": cf,
            "sector_info": "",
        })

    # 按综合评分排序
    results.sort(key=lambda x: x["score"], reverse=True)
    recommendations = results[:final_top_n]

    # 生成报告
    date_str = datetime.now().strftime("%Y-%m-%d")
    report = format_report(recommendations, date_str, market_context=market_context)
    print("\n" + report)

    # 保存报告
    report_config = config.get("report", {})
    if report_config.get("save_to_file", True):
        output_dir = get_output_dir(config)
        text_path = save_report_text(report, output_dir, date_str)
        print(f"\n  报告已保存: {text_path}")

        if report_config.get("output_format") == "csv":
            csv_path = save_report_csv(recommendations, output_dir, date_str)
            print(f"  CSV已保存: {csv_path}")

    return recommendations


def main() -> None:
    """CLI入口"""
    parser = argparse.ArgumentParser(
        description="A股短线推荐系统 v2.0 - 多维度综合选股",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                    # 使用默认配置运行
  python main.py -n 3               # 推荐3只股票
  python main.py -c my_config.yaml  # 使用自定义配置
  python main.py --csv              # 同时输出CSV文件
        """,
    )
    parser.add_argument("-c", "--config", type=str, default=None, help="配置文件路径（默认: config.yaml）")
    parser.add_argument("-n", "--top-n", type=int, default=None, help="推荐股票数量（默认: 5）")
    parser.add_argument("--csv", action="store_true", help="同时输出CSV格式报告")

    args = parser.parse_args()

    if args.csv:
        config = load_config(args.config)
        config.setdefault("report", {})["output_format"] = "csv"

    try:
        run(config_path=args.config, top_n=args.top_n)
    except KeyboardInterrupt:
        print("\n\n已取消运行。")
        sys.exit(0)
    except Exception as e:
        print(f"\n  运行出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
