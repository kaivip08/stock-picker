"""推荐报告生成模块"""

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from tabulate import tabulate


def format_report(
    recommendations: list[dict[str, Any]],
    date_str: str | None = None,
    market_context: dict[str, Any] | None = None,
) -> str:
    """生成文本格式的推荐报告"""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    lines = []
    lines.append("=" * 70)
    lines.append(f"  A股短线推荐报告 - {date_str}")
    lines.append("=" * 70)
    lines.append("")

    # 市场概览
    if market_context:
        _append_market_overview(lines, market_context)

    if not recommendations:
        lines.append("  今日未找到符合条件的推荐股票。")
        lines.append("")
        _append_disclaimer(lines)
        return "\n".join(lines)

    # 汇总表格
    table_data = []
    for i, rec in enumerate(recommendations, 1):
        table_data.append([
            i,
            rec["code"],
            rec["name"],
            f'{rec["close"]:.2f}',
            f'{rec["pct_change"]:+.2f}%',
            f'{rec["score"]:.1f}',
            f'{rec["stop_loss_info"]["stop_loss"]:.2f}',
            f'{rec["stop_loss_info"]["target_1"]:.2f}',
        ])

    headers = ["#", "代码", "名称", "现价", "涨跌幅", "评分", "止损位", "目标价"]
    lines.append(tabulate(table_data, headers=headers, tablefmt="simple", stralign="right"))
    lines.append("")

    # 详细信息
    lines.append("-" * 70)
    lines.append("  详细分析")
    lines.append("-" * 70)

    for i, rec in enumerate(recommendations, 1):
        lines.append("")
        lines.append(f"  [{i}] {rec['name']}（{rec['code']}）")
        lines.append(f"      现价: {rec['close']:.2f}  |  涨跌幅: {rec['pct_change']:+.2f}%  |  综合评分: {rec['score']:.1f}")
        lines.append("")
        lines.append("      推荐理由:")
        for reason in rec["reasons"]:
            lines.append(f"        {reason}")
        lines.append("")

        sl = rec["stop_loss_info"]
        lines.append(f"      建议买入价: {sl['entry_price']:.2f}")
        lines.append(f"      止损位:     {sl['stop_loss']:.2f}（{sl['stop_loss_pct']:+.2f}%）")
        lines.append(f"      目标价1:    {sl['target_1']:.2f}（{sl['target_1_pct']:+.2f}%）")
        lines.append(f"      目标价2:    {sl['target_2']:.2f}（{sl['target_2_pct']:+.2f}%）")

        # 资金流向信息
        if "capital_flow" in rec and rec["capital_flow"]:
            cf = rec["capital_flow"]
            lines.append("")
            lines.append("      资金流向:")
            if "main_net_inflow" in cf:
                net = cf["main_net_inflow"]
                sign = "+" if net >= 0 else ""
                lines.append(f"        主力净流入: {sign}{net / 1e4:.1f}万")
            if "super_large_net" in cf:
                net = cf["super_large_net"]
                sign = "+" if net >= 0 else ""
                lines.append(f"        超大单净流入: {sign}{net / 1e4:.1f}万")

        # 基本面信息
        if "fundamentals" in rec and rec["fundamentals"]:
            fund = rec["fundamentals"]
            fund_parts = []
            roe = fund.get("roe")
            if roe is not None:
                fund_parts.append(f"ROE:{roe:.1f}%")
            rev_yoy = fund.get("revenue_yoy")
            if rev_yoy is not None:
                fund_parts.append(f"营收增长:{rev_yoy:.1f}%")
            profit_yoy = fund.get("profit_yoy")
            if profit_yoy is not None:
                fund_parts.append(f"利润增长:{profit_yoy:.1f}%")
            gross_margin = fund.get("gross_margin")
            if gross_margin is not None:
                fund_parts.append(f"毛利率:{gross_margin:.1f}%")
            if fund_parts:
                lines.append(f"      基本面: {' | '.join(fund_parts)}")

        # 事件标记
        if "event_flags" in rec and rec["event_flags"]:
            lines.append(f"      事件: {', '.join(rec['event_flags'])}")

        # 板块信息
        if "sector_info" in rec and rec["sector_info"]:
            lines.append(f"      所属板块: {rec['sector_info']}")

    lines.append("")

    # 热门板块
    if market_context and market_context.get("hot_sectors"):
        _append_hot_sectors(lines, market_context["hot_sectors"])

    _append_disclaimer(lines)
    return "\n".join(lines)


def _append_market_overview(lines: list[str], ctx: dict[str, Any]) -> None:
    """添加市场概览"""
    lines.append("-" * 70)
    lines.append("  市场概览")
    lines.append("-" * 70)

    # 指数行情
    indices = ctx.get("indices", {})
    if indices:
        idx_parts = []
        for name, info in indices.items():
            pct = info.get("pct_change", 0)
            sign = "+" if pct >= 0 else ""
            idx_parts.append(f"{name} {sign}{pct:.2f}%")
        lines.append("  " + "  |  ".join(idx_parts[:4]))
        if len(idx_parts) > 4:
            lines.append("  " + "  |  ".join(idx_parts[4:]))

    # 市场情绪
    sentiment = ctx.get("sentiment", {})
    if sentiment:
        up = sentiment.get("up_count", 0)
        down = sentiment.get("down_count", 0)
        limit_up = sentiment.get("limit_up_count", 0)
        limit_down = sentiment.get("limit_down_count", 0)
        profit = sentiment.get("profit_ratio", 0)
        lines.append(f"  上涨: {up}  下跌: {down}  涨停: {limit_up}  跌停: {limit_down}  赚钱效应: {profit:.1f}%")
        score = sentiment.get("sentiment_score", 0)
        if score >= 60:
            mood = "偏强"
        elif score >= 40:
            mood = "中性"
        else:
            mood = "偏弱"
        lines.append(f"  情绪评分: {score:.1f}/100（{mood}）")

    # 北向资金
    north = ctx.get("north_flow", {})
    if north and north.get("total", 0) != 0:
        total = north["total"]
        sign = "+" if total >= 0 else ""
        lines.append(f"  北向资金: {sign}{total / 1e4:.2f}亿")

    lines.append("")


def _append_hot_sectors(lines: list[str], sectors: list[dict]) -> None:
    """添加热门板块"""
    lines.append("-" * 70)
    lines.append("  热门板块")
    lines.append("-" * 70)
    for s in sectors[:5]:
        pct = s.get("pct_change", 0)
        sign = "+" if pct >= 0 else ""
        leader = s.get("leader_name", "")
        lines.append(f"  [{s.get('type', '')}] {s.get('name', '')} {sign}{pct:.2f}%  龙头: {leader}")
    lines.append("")


def _append_disclaimer(lines: list[str]) -> None:
    """添加风险提示"""
    lines.append("=" * 70)
    lines.append("  风险提示")
    lines.append("=" * 70)
    lines.append("  1. 本报告仅供参考，不构成投资建议")
    lines.append("  2. 股市有风险，投资需谨慎")
    lines.append("  3. 短线交易风险较高，请严格执行止损纪律")
    lines.append("  4. 请根据自身风险承受能力做出投资决策")
    lines.append("  5. 历史表现不代表未来收益")
    lines.append("=" * 70)


def save_report_text(content: str, output_dir: Path, date_str: str | None = None) -> Path:
    """保存文本报告"""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"recommendation_{date_str}.txt"
    filepath.write_text(content, encoding="utf-8")
    return filepath


def save_report_csv(
    recommendations: list[dict[str, Any]],
    output_dir: Path,
    date_str: str | None = None,
) -> Path:
    """保存CSV报告"""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"recommendation_{date_str}.csv"

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "日期", "代码", "名称", "现价", "涨跌幅", "综合评分",
            "止损位", "目标价1", "目标价2", "推荐理由",
        ])
        for rec in recommendations:
            sl = rec["stop_loss_info"]
            writer.writerow([
                date_str,
                rec["code"],
                rec["name"],
                f'{rec["close"]:.2f}',
                f'{rec["pct_change"]:.2f}%',
                f'{rec["score"]:.1f}',
                f'{sl["stop_loss"]:.2f}',
                f'{sl["target_1"]:.2f}',
                f'{sl["target_2"]:.2f}',
                "; ".join(rec["reasons"]),
            ])

    return filepath
