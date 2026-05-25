"""推荐报告生成模块"""

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from tabulate import tabulate


def format_report(recommendations: list[dict[str, Any]], date_str: str | None = None) -> str:
    """生成文本格式的推荐报告"""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    lines = []
    lines.append("=" * 70)
    lines.append(f"  📈 A股短线推荐报告 - {date_str}")
    lines.append("=" * 70)
    lines.append("")

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
        lines.append(f"  【{i}】{rec['name']}（{rec['code']}）")
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

    lines.append("")
    _append_disclaimer(lines)
    return "\n".join(lines)


def _append_disclaimer(lines: list[str]) -> None:
    """添加风险提示"""
    lines.append("=" * 70)
    lines.append("  ⚠️ 风险提示")
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
