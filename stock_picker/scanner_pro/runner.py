"""Pro Scanner 主流程：组合数据、过滤、打分、报告。"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

CST = timezone(timedelta(hours=8), name="CST")

from stock_picker.data_fetcher import batch_get_history
from stock_picker.indicators import calc_all_indicators
from stock_picker.scanner_pro.data import (
    fetch_concept_sectors,
    fetch_fund_flow_rank,
    fetch_industry_sectors,
    fetch_main_board_spot,
    fetch_stock_sectors,
)
from stock_picker.scanner_pro.filters import (
    apply_hard_filters,
    apply_history_filters,
)
from stock_picker.scanner_pro.scorers import (
    build_sector_strength_index,
    composite_score,
    score_money,
    score_technical,
    score_theme,
)


def _fetch_indices() -> list[dict]:
    """获取主要指数（上证/深成/创业板/科创50/沪深300/中证500）。

    用 clist 接口批量拉取，避免单独 stock/get 限流。
    """
    from stock_picker.data_fetcher import _session
    order = [
        ("000001", "上证指数"),
        ("399001", "深证成指"),
        ("399006", "创业板指"),
        ("000688", "科创50"),
        ("000300", "沪深300"),
        ("000905", "中证500"),
    ]
    name_by_code = dict(order)
    fs = "i:1.000001,i:0.399001,i:0.399006,i:1.000688,i:1.000300,i:1.000905"
    params = {
        "pn": "1", "pz": "10", "po": "1", "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2", "invt": "2",
        "fid": "f3", "fs": fs,
        "fields": "f2,f3,f12,f14",
        "_": str(int(time.time() * 1000)),
    }
    nodes = [
        "http://82.push2.eastmoney.com/api/qt/clist/get",
        "http://18.push2.eastmoney.com/api/qt/clist/get",
        "http://32.push2.eastmoney.com/api/qt/clist/get",
        "http://push2.eastmoney.com/api/qt/clist/get",
    ]
    raw_by_code: dict[str, dict] = {}
    for url in nodes:
        try:
            r = _session.get(
                url, params=params,
                headers={"Referer": "https://quote.eastmoney.com/"},
                timeout=8,
            )
            if r.status_code != 200 or not r.text.startswith("{"):
                continue
            items = r.json().get("data", {}).get("diff") or []
            for it in items:
                code = str(it.get("f12", ""))
                raw_by_code[code] = it
            if items:
                break
        except Exception:
            continue

    # 腾讯降级
    if not raw_by_code:
        try:
            tencent_map = {
                "000001": "sh000001",
                "399001": "sz399001",
                "399006": "sz399006",
                "000688": "sh000688",
                "000300": "sh000300",
                "000905": "sh000905",
            }
            tc_codes = ",".join(tencent_map.values())
            r = _session.get(f"http://qt.gtimg.cn/q={tc_codes}", timeout=8)
            r.encoding = "gbk"
            for line in r.text.strip().split("\n"):
                line = line.strip()
                import re as _re
                m = _re.search(r'v_s([hz]\d{6})="(.+)"', line)
                if not m:
                    continue
                raw_code = m.group(1)[1:]
                fields = m.group(2).split("~")
                if len(fields) < 33:
                    continue
                try:
                    close_v = float(fields[3])
                    pct_v = float(fields[32]) if fields[32] else None
                    raw_by_code[raw_code] = {"f2": close_v, "f3": pct_v}
                except Exception:
                    pass
        except Exception:
            pass

    indices: list[dict] = []
    for code, name in order:
        it = raw_by_code.get(code)
        if it:
            indices.append({
                "name": name,
                "close": it.get("f2"),
                "pct_change": it.get("f3"),
            })
        else:
            indices.append({"name": name, "close": None, "pct_change": None})
    return indices


def _make_trade_plan(spot_row: pd.Series, atr_pct: float | None) -> dict[str, str]:
    """根据当前价 + ATR 机械生成默认交易计划（仅供参考）。"""
    close = spot_row.get("close")
    if close is None or pd.isna(close):
        return {}
    close_f = float(close)

    # 默认止损：ATR 不可用时按 -5% 严格止损
    if atr_pct and atr_pct > 0:
        stop_pct = max(min(atr_pct * 1.5, 7.0), 3.5)
    else:
        stop_pct = 5.0

    stop_price = close_f * (1 - stop_pct / 100)
    target1 = close_f * 1.08  # T1: +8%
    target2 = close_f * 1.15  # T2: +15%

    return {
        "entry_range": f"{close_f * 0.99:.2f} – {close_f * 1.015:.2f}",
        "max_position": "≤ 20%（按风控总仓位上限）",
        "stop_loss": f"{stop_price:.2f}（-{stop_pct:.1f}%）",
        "target1": f"{target1:.2f}（+8%）",
        "target2": f"{target2:.2f}（+15%）",
        "hold_days": "3 – 7",
    }


def run_scanner_pro(config: dict[str, Any], verbose: bool = True) -> dict[str, Any]:
    """运行 Pro Scanner 主流程，返回 {candidates, market, timestamp}。"""
    pro = config.get("scanner_pro", {})
    top_n_final = pro.get("top_n", 15)
    deep_n = pro.get("deep_analyze_top_n", 60)
    history_days = pro.get("history_days", 120)

    log = print if verbose else (lambda *a, **k: None)

    log("\n=" * 1 + "=" * 60)
    log("中短线主板爆发力 Pro Scanner")
    log("=" * 60)

    # 0) 先拉指数（短请求，放最前避免后续被限流）
    log("\n[0/6] 拉取主要指数 ...")
    indices = _fetch_indices()
    log(f"      {sum(1 for x in indices if x.get('close') is not None)} 个有效")

    # 1) 拉取主板实时行情
    log("\n[1/6] 拉取沪深主板实时行情 ...")
    spot = fetch_main_board_spot()
    log(f"      原始 {len(spot)} 只")
    spot_filtered = apply_hard_filters(spot, config)
    log(f"      硬性筛选后 {len(spot_filtered)} 只")

    if spot_filtered.empty:
        log("      ⚠ 无候选股，返回空结果")
        return {"candidates": [], "market": {}, "timestamp": datetime.now()}

    # 按 (换手率 * 量比) 取活跃 Top N 进入深度分析
    # 若量比缺失（如腾讯降级路径），退化为 换手率 * (成交额 / 1亿)
    tr = pd.to_numeric(spot_filtered["turnover_rate"], errors="coerce").fillna(0)
    vr = pd.to_numeric(spot_filtered.get("volume_ratio"), errors="coerce")
    if vr is None or vr.isna().all():
        amount_yi = pd.to_numeric(spot_filtered.get("amount"), errors="coerce").fillna(0) / 1e8
        spot_filtered["activity"] = tr * (1 + amount_yi)
    else:
        spot_filtered["activity"] = tr * vr.fillna(1.0)
    spot_filtered = spot_filtered.sort_values(
        "activity", ascending=False, na_position="last"
    ).reset_index(drop=True)
    deep_codes = spot_filtered["code"].head(deep_n).tolist()
    log(f"      按活跃度取前 {len(deep_codes)} 只进入深度分析")

    # 2) 拉取资金流排行
    log("\n[2/6] 拉取主力资金流排行 ...")
    try:
        fund_flow = fetch_fund_flow_rank()
        log(f"      {len(fund_flow)} 条记录")
        flow_by_code: dict[str, dict] = {}
        if not fund_flow.empty:
            for _, row in fund_flow.iterrows():
                code = str(row.get("code", ""))
                if code:
                    flow_by_code[code] = row.to_dict()
    except Exception as e:
        log(f"      ⚠ 资金流拉取失败：{e}")
        flow_by_code = {}

    # 3) 拉取板块行情
    log("\n[3/6] 拉取行业 / 概念板块行情 ...")
    try:
        industry_df = fetch_industry_sectors()
    except Exception as e:
        log(f"      ⚠ 行业板块拉取失败：{e}")
        industry_df = pd.DataFrame()
    try:
        concept_df = fetch_concept_sectors()
    except Exception as e:
        log(f"      ⚠ 概念板块拉取失败：{e}")
        concept_df = pd.DataFrame()
    log(f"      行业 {len(industry_df)} / 概念 {len(concept_df)}")
    sector_index = build_sector_strength_index(industry_df, concept_df)

    # 4) 拉历史 K 线 + 计算指标
    log(f"\n[4/6] 拉取历史 K 线（{history_days} 日）...")
    data_config = config.get("data", {})
    history_data = batch_get_history(
        deep_codes,
        days=history_days,
        retry_times=data_config.get("retry_times", 3),
        interval=data_config.get("request_interval", 0.4),
    )
    log(f"      成功获取 {len(history_data)} / {len(deep_codes)} 只")

    # 5) 二次过滤 + 拉板块标签 + 打分
    log("\n[5/6] 计算指标 / 板块标签 / 三共振打分 ...")
    spot_by_code: dict[str, pd.Series] = {
        str(r["code"]): r for _, r in spot_filtered.iterrows()
    }

    candidates: list[dict] = []
    skipped = 0
    for code, hist_df in history_data.items():
        try:
            hist_df = calc_all_indicators(hist_df, config)
        except Exception:
            skipped += 1
            continue
        ok, hist_info = apply_history_filters(hist_df, config)
        if not ok:
            skipped += 1
            continue

        spot_row = spot_by_code.get(code)
        if spot_row is None:
            continue

        # 板块标签（每只单独查，限流）
        sectors = fetch_stock_sectors(code) or {}
        time.sleep(0.2)

        # 三共振打分
        tech = score_technical(hist_df, spot_row, config)
        money = score_money(spot_row, flow_by_code.get(code), config)
        stock_sectors_list = []
        if sectors.get("industry"):
            stock_sectors_list.append(sectors["industry"])
        if sectors.get("concepts"):
            stock_sectors_list.extend(sectors["concepts"])
        theme = score_theme(sector_index, stock_sectors_list)
        comp = composite_score(tech, money, theme, config)

        candidates.append({
            "code": code,
            "name": str(spot_row.get("name", "")),
            "spot": spot_row.to_dict(),
            "fund_flow": flow_by_code.get(code),
            "sectors": sectors,
            "dist_to_ma60_pct": hist_info.get("dist_to_ma60_pct"),
            "atr_pct": hist_info.get("atr_pct"),
            "cum_pct_60d": hist_info.get("cum_pct_60d"),
            "composite": comp,
            "trade_plan": _make_trade_plan(spot_row, hist_info.get("atr_pct")),
        })

    log(f"      通过历史筛选并打分 {len(candidates)} 只，跳过 {skipped} 只")

    # 6) 综合分排序，取 Top N
    candidates.sort(key=lambda x: x["composite"]["total"], reverse=True)
    final = candidates[:top_n_final]

    log(f"\n[6/6] 取综合分 Top {len(final)} 输出报告\n")

    market = {
        "indices": indices,
        "industry_top": industry_df.head(20).to_dict("records") if not industry_df.empty else [],
        "concept_top": concept_df.head(20).to_dict("records") if not concept_df.empty else [],
    }

    return {
        "candidates": final,
        "market": market,
        "timestamp": datetime.now(tz=CST),
    }
