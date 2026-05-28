"""Pro Scanner 报告输出（Markdown + 控制台）。

输出格式遵循方案 §4.1 个股深度分析模板的核心字段。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd


_DISCLAIMER = (
    "> ⚠️ **本报告仅为符合方案 §2.1–§2.2 筛选条件的候选池**，"
    "不构成投资建议、不保证任何标的明日上涨。\n"
    "> 团队必须按方案 §3 SOP 进行人工复核（题材逻辑、龙虎榜、分时强度），"
    "并按 §5 风控严格执行止损。\n"
)


def _fmt_money(x: float | None) -> str:
    if x is None or pd.isna(x):
        return "-"
    if abs(x) >= 1e8:
        return f"{x/1e8:.2f}亿"
    if abs(x) >= 1e4:
        return f"{x/1e4:.2f}万"
    return f"{x:.0f}"


def _fmt_pct(x: float | None, digits: int = 2) -> str:
    if x is None or pd.isna(x):
        return "-"
    return f"{x:+.{digits}f}%"


def _fmt_num(x: float | None, digits: int = 2) -> str:
    if x is None or pd.isna(x):
        return "-"
    return f"{x:.{digits}f}"


def build_summary_table(candidates: list[dict]) -> str:
    """候选池一览表。"""
    if not candidates:
        return "（无候选股）"
    header = (
        "| # | 代码 | 名称 | 现价 | 涨跌幅 | 换手率 | 量比 | 成交额 | "
        "距MA60 | 综合分 | 技术 | 资金 | 题材 | 核心板块 |"
    )
    sep = "|---|------|------|------|--------|--------|------|--------|--------|--------|------|------|------|-----------|"
    rows = [header, sep]
    for i, c in enumerate(candidates, 1):
        spot = c["spot"]
        comp = c["composite"]
        theme = comp["theme"]
        rows.append(
            f"| {i} "
            f"| {c['code']} | {c['name']} "
            f"| {_fmt_num(spot.get('close'))} "
            f"| {_fmt_pct(spot.get('pct_change'))} "
            f"| {_fmt_pct(spot.get('turnover_rate'))} "
            f"| {_fmt_num(spot.get('volume_ratio'))} "
            f"| {_fmt_money(spot.get('amount'))} "
            f"| {_fmt_pct(c.get('dist_to_ma60_pct'), 1)} "
            f"| **{comp['total']:.1f}** "
            f"| {comp['tech']['score']:.1f} "
            f"| {comp['money']['score']:.1f} "
            f"| {comp['theme']['score']:.1f} "
            f"| {theme.get('best_sector') or '-'} |"
        )
    return "\n".join(rows)


def build_detail_section(c: dict) -> str:
    """单只候选股详情段，对应方案 §4.1 模板的关键字段。"""
    spot = c["spot"]
    comp = c["composite"]
    tech = comp["tech"]
    money = comp["money"]
    theme = comp["theme"]
    flow = c.get("fund_flow") or {}
    sectors = c.get("sectors") or {}
    plan = c.get("trade_plan") or {}

    md: list[str] = []
    md.append(f"### {c['code']} {c['name']}（综合分 **{comp['total']:.1f}**）\n")
    md.append("**一、基本面快照**")
    md.append(
        f"- 现价 {_fmt_num(spot.get('close'))}　涨跌幅 {_fmt_pct(spot.get('pct_change'))}"
        f"　振幅 {_fmt_pct(spot.get('amplitude'))}"
    )
    md.append(
        f"- 流通市值 {_fmt_money(spot.get('circulating_market_cap'))}　"
        f"总市值 {_fmt_money(spot.get('total_market_cap'))}　"
        f"PE {_fmt_num(spot.get('pe_ratio'))}　PB {_fmt_num(spot.get('pb_ratio'))}"
    )
    md.append(
        f"- 换手率 {_fmt_pct(spot.get('turnover_rate'))}　"
        f"量比 {_fmt_num(spot.get('volume_ratio'))}　"
        f"成交额 {_fmt_money(spot.get('amount'))}"
    )

    md.append("\n**二、题材标签（来自东方财富）**")
    industry = sectors.get("industry") or "-"
    region = sectors.get("region") or "-"
    concepts = sectors.get("concepts") or []
    md.append(f"- 行业：{industry}　地域：{region}")
    md.append(f"- 概念：{', '.join(concepts) if concepts else '-'}")
    if theme.get("best_sector"):
        md.append(
            f"- 关联强势板块：**{theme['best_sector']}**（板块强度分 "
            f"{theme['details'].get('best_sector_score', 0):.1f}）"
        )

    md.append("\n**三、技术面**")
    td = tech["details"]
    md.append(
        f"- 量比/放量 {td.get('volume_ratio', 0):.0f}/25　"
        f"突破20日 {td.get('breakout_20d', 0):.0f}/20　"
        f"均线多头 {td.get('ma_bullish', 0):.0f}/20"
    )
    md.append(
        f"- MACD {td.get('macd', 0):.0f}/15　"
        f"动量5日 {td.get('momentum_5d', 0):.0f}/10　"
        f"MA60 位置 {td.get('ma60_position', 0):.0f}/10"
    )
    if c.get("dist_to_ma60_pct") is not None:
        md.append(f"- 距 60 日均线：{_fmt_pct(c['dist_to_ma60_pct'], 1)}")
    if c.get("atr_pct") is not None:
        md.append(f"- ATR/股价（弹性）：{_fmt_pct(c['atr_pct'], 1)}")
    if c.get("cum_pct_60d") is not None:
        md.append(f"- 近 60 日累计涨幅：{_fmt_pct(c['cum_pct_60d'], 1)}")

    md.append("\n**四、资金面**")
    md.append(
        f"- 主力净流入：{_fmt_money(flow.get('main_net_inflow'))}　"
        f"占比 {_fmt_pct(flow.get('main_net_inflow_pct'))}"
    )
    md.append(
        f"- 超大单 {_fmt_money(flow.get('super_large_net_inflow'))}　"
        f"大单 {_fmt_money(flow.get('large_net_inflow'))}　"
        f"中单 {_fmt_money(flow.get('medium_net_inflow'))}　"
        f"小单 {_fmt_money(flow.get('small_net_inflow'))}"
    )

    md.append("\n**五、交易计划（机械生成，供参考）**")
    if plan:
        md.append(f"- 计划买入区间：{plan.get('entry_range', '-')}")
        md.append(f"- 仓位上限：{plan.get('max_position', '-')}")
        md.append(f"- 止损位：{plan.get('stop_loss', '-')}")
        md.append(f"- 止盈目标 T1 / T2：{plan.get('target1', '-')} / {plan.get('target2', '-')}")
        md.append(f"- 计划持有周期：{plan.get('hold_days', '-')} 个交易日")

    md.append("\n**六、风险点（必须人工核验）**")
    md.append("- [ ] 题材逻辑核对（政策/业绩/事件是否真实有效，是否已被透支）")
    md.append("- [ ] 近 30 日是否有大额限售解禁、减持公告、商誉爆雷预警")
    md.append("- [ ] 龙虎榜席位（是否游资 vs 机构 vs 散户接盘）")
    md.append("- [ ] 分时图强度（是否强于大盘、是否多次冲高回落）")
    md.append("- [ ] 同板块同梯队的票表现（避免孤儿股）")

    return "\n".join(md)


def build_market_overview(market: dict) -> str:
    """大盘 / 板块简要复盘段（与方案 §4.2 一致的核心字段）。"""
    md: list[str] = []
    md.append("## 一、大盘速览\n")
    if market.get("indices"):
        md.append("| 指数 | 收盘 | 涨跌幅 |")
        md.append("|------|------|--------|")
        for idx in market["indices"]:
            md.append(
                f"| {idx['name']} | {_fmt_num(idx.get('close'))} | "
                f"{_fmt_pct(idx.get('pct_change'))} |"
            )
        md.append("")

    md.append("## 二、行业板块 Top 10\n")
    industry = market.get("industry_top") or []
    if industry:
        md.append("| # | 板块 | 涨跌幅 | 主力净流入 | 龙头 |")
        md.append("|---|------|--------|------------|------|")
        for i, s in enumerate(industry[:10], 1):
            md.append(
                f"| {i} | {s.get('name', '-')} | {_fmt_pct(s.get('pct_change'))} "
                f"| {_fmt_money(s.get('main_net_inflow'))} | "
                f"{s.get('leader_name') or '-'} |"
            )
    md.append("")

    md.append("## 三、概念板块 Top 10\n")
    concept = market.get("concept_top") or []
    if concept:
        md.append("| # | 概念 | 涨跌幅 | 主力净流入 |")
        md.append("|---|------|--------|------------|")
        for i, s in enumerate(concept[:10], 1):
            md.append(
                f"| {i} | {s.get('name', '-')} | {_fmt_pct(s.get('pct_change'))} "
                f"| {_fmt_money(s.get('main_net_inflow'))} |"
            )
    md.append("")
    return "\n".join(md)


def build_full_report(
    candidates: list[dict],
    market: dict,
    timestamp: datetime,
) -> str:
    """生成完整 Markdown 报告。"""
    md: list[str] = []
    md.append("# A 股主板中短线爆发力 · 候选股扫描报告\n")
    md.append(f"**生成时间**：{timestamp.strftime('%Y-%m-%d %H:%M %Z')}\n")
    md.append(_DISCLAIMER)
    md.append("")
    md.append(build_market_overview(market))
    md.append(f"## 四、候选股池（共 {len(candidates)} 只）\n")
    md.append(build_summary_table(candidates))
    md.append("")
    md.append("## 五、个股详情\n")
    for c in candidates:
        md.append(build_detail_section(c))
        md.append("\n---\n")
    md.append("## 六、下一步\n")
    md.append("1. 操盘手按风控仓位上限挑选 1–3 只进入交易池\n")
    md.append("2. 每只股票按方案 §4.1 模板补全题材逻辑、风险点核验\n")
    md.append("3. 严格按计划价位执行，盘中不改止损\n")
    md.append("4. 收盘后按方案 §3.3 完成复盘并归档\n")
    return "\n".join(md)


def save_report(
    content: str,
    output_dir: str | Path,
    prefix: str = "scanner_pro",
    timestamp: datetime | None = None,
) -> Path:
    """保存报告到指定目录。"""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts_obj = timestamp or datetime.now()
    ts = ts_obj.strftime("%Y%m%d_%H%M")
    path = out_dir / f"{prefix}_{ts}.md"
    path.write_text(content, encoding="utf-8")
    return path
