"""Pro Scanner 三共振打分（方案 §2.1）。

总分 = 技术(0-100) * w_tech + 资金(0-100) * w_money + 题材(0-100) * w_theme
默认权重 40 / 35 / 25。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


# ---------- 技术共振 ----------

def score_technical(hist_df: pd.DataFrame, spot_row: pd.Series, config: dict) -> dict:
    """技术面打分（0-100）：放量、突破、均线、动量、缩量回踩。"""
    sub: dict[str, float] = {}
    if hist_df is None or len(hist_df) < 30:
        return {"score": 0.0, "details": sub}

    last = hist_df.iloc[-1]
    close = float(last["close"])

    # 1) 量比 / 量能放大（满分 25）
    vol_ratio = spot_row.get("volume_ratio")
    vr_calc = last.get("volume_ratio_calc")
    vr = vol_ratio if pd.notna(vol_ratio) else (vr_calc if pd.notna(vr_calc) else 1.0)
    vol_score = 0.0
    if pd.notna(vr):
        if vr >= 3.0:
            vol_score = 25.0
        elif vr >= 2.0:
            vol_score = 20.0
        elif vr >= 1.5:
            vol_score = 15.0
        elif vr >= 1.2:
            vol_score = 8.0
    sub["volume_ratio"] = float(vol_score)

    # 2) 突破前高（满分 20）
    breakout_score = 0.0
    if len(hist_df) >= 21:
        recent_high_20 = float(hist_df["high"].iloc[-21:-1].max())
        if recent_high_20 > 0:
            ratio = close / recent_high_20
            if ratio >= 1.0:
                breakout_score = 20.0
            elif ratio >= 0.97:
                breakout_score = 12.0
            elif ratio >= 0.93:
                breakout_score = 5.0
    sub["breakout_20d"] = float(breakout_score)

    # 3) 均线多头排列（满分 20）
    ma_score = 0.0
    ma5 = last.get("ma5")
    ma10 = last.get("ma10")
    ma20 = last.get("ma20")
    ma60 = last.get("ma60")
    if all(pd.notna(x) for x in [ma5, ma10, ma20]):
        if ma5 > ma10 > ma20:
            ma_score += 12.0
        elif ma5 > ma10:
            ma_score += 6.0
        if pd.notna(ma60) and close > ma60:
            ma_score += 4.0
        if close > ma5:
            ma_score += 4.0
    sub["ma_bullish"] = float(min(ma_score, 20.0))

    # 4) MACD 状态（满分 15）
    macd_score = 0.0
    if len(hist_df) >= 5:
        prev = hist_df.iloc[-2]
        dif = last.get("macd_dif")
        dea = last.get("macd_dea")
        prev_dif = prev.get("macd_dif")
        prev_dea = prev.get("macd_dea")
        hist_val = last.get("macd_hist")
        prev_hist = prev.get("macd_hist")
        if all(pd.notna(x) for x in [dif, dea, prev_dif, prev_dea]):
            if prev_dif <= prev_dea and dif > dea:
                macd_score += 10.0  # 金叉
            elif dif > dea:
                macd_score += 5.0
        if pd.notna(hist_val) and pd.notna(prev_hist):
            if prev_hist < 0 < hist_val:
                macd_score += 5.0
            elif hist_val > prev_hist > 0:
                macd_score += 3.0
    sub["macd"] = float(min(macd_score, 15.0))

    # 5) 价格动量（满分 10）：5 日涨幅在 0–10%
    momo_score = 0.0
    if len(hist_df) >= 6:
        pct_5d = (close / float(hist_df["close"].iloc[-6]) - 1) * 100
        if 2 <= pct_5d <= 8:
            momo_score = 10.0
        elif 0 <= pct_5d < 2:
            momo_score = 6.0
        elif 8 < pct_5d <= 12:
            momo_score = 5.0
    sub["momentum_5d"] = float(momo_score)

    # 6) 处在 60 日均线附近（满分 10）：方案偏好"距 60 日均线 ±15%"且趋势温和
    pos_score = 0.0
    if pd.notna(ma60) and ma60 > 0:
        dist = (close - ma60) / ma60 * 100
        if -5 <= dist <= 8:
            pos_score = 10.0
        elif -10 <= dist <= 12:
            pos_score = 6.0
        elif -15 <= dist <= 15:
            pos_score = 3.0
    sub["ma60_position"] = float(pos_score)

    total = sum(sub.values())
    return {"score": round(min(total, 100.0), 1), "details": sub}


# ---------- 资金共振 ----------

def score_money(spot_row: pd.Series, fund_flow_row: dict | None, config: dict) -> dict:
    """资金面打分（0-100）：主力净流入、占比、超大单。"""
    sub: dict[str, float] = {}
    pro = config.get("scanner_pro", {})

    # 1) 当日换手率（满分 20）
    tr = spot_row.get("turnover_rate")
    tr_score = 0.0
    if pd.notna(tr):
        if 8 <= tr <= 25:
            tr_score = 20.0
        elif 5 <= tr < 8 or 25 < tr <= 35:
            tr_score = 14.0
        elif 3 <= tr < 5:
            tr_score = 8.0
    sub["turnover_rate"] = float(tr_score)

    # 2) 当日成交额绝对水位（满分 15）
    amt = spot_row.get("amount") or 0
    amt_score = 0.0
    if amt >= 10e8:
        amt_score = 15.0
    elif amt >= 5e8:
        amt_score = 12.0
    elif amt >= 3e8:
        amt_score = 9.0
    elif amt >= 1e8:
        amt_score = 5.0
    sub["amount_level"] = float(amt_score)

    # 3) 主力净流入（满分 25）
    main_score = 0.0
    main_in = None
    if fund_flow_row:
        main_in = fund_flow_row.get("main_net_inflow")
    if pd.notna(main_in) and main_in is not None:
        if main_in >= 3e8:
            main_score = 25.0
        elif main_in >= 1.5e8:
            main_score = 20.0
        elif main_in >= 0.5e8:
            main_score = 14.0
        elif main_in >= 0.1e8:
            main_score = 8.0
        elif main_in > 0:
            main_score = 4.0
        elif main_in < -1.5e8:
            main_score = -10.0  # 主力大幅出逃，扣分
    sub["main_inflow"] = float(main_score)

    # 4) 主力净流入占比（满分 20）
    pct_score = 0.0
    main_pct = None
    if fund_flow_row:
        main_pct = fund_flow_row.get("main_net_inflow_pct")
    if pd.notna(main_pct) and main_pct is not None:
        if main_pct >= 10:
            pct_score = 20.0
        elif main_pct >= 5:
            pct_score = 15.0
        elif main_pct >= 2:
            pct_score = 10.0
        elif main_pct >= 0:
            pct_score = 4.0
        elif main_pct < -5:
            pct_score = -8.0
    sub["main_inflow_pct"] = float(pct_score)

    # 5) 超大单净流入（满分 20）
    super_score = 0.0
    super_in = None
    if fund_flow_row:
        super_in = fund_flow_row.get("super_large_net_inflow")
    if pd.notna(super_in) and super_in is not None:
        if super_in >= 1.5e8:
            super_score = 20.0
        elif super_in >= 0.5e8:
            super_score = 14.0
        elif super_in >= 0.1e8:
            super_score = 7.0
        elif super_in > 0:
            super_score = 3.0
    sub["super_large_inflow"] = float(super_score)

    total = sum(sub.values())
    return {"score": round(max(0.0, min(total, 100.0)), 1), "details": sub}


# ---------- 题材共振 ----------

def build_sector_strength_index(
    industry_df: pd.DataFrame,
    concept_df: pd.DataFrame,
) -> dict[str, float]:
    """构造一个简单的板块强度索引：板块名 -> 综合强度分（0–100）。

    强度 = (涨跌幅 + 主力资金流强度) 的归一化打分。
    """
    index: dict[str, float] = {}
    for df in (industry_df, concept_df):
        if df is None or df.empty:
            continue
        if "name" not in df.columns or "pct_change" not in df.columns:
            continue
        pct = df["pct_change"].fillna(0.0)
        flow = df.get("main_net_inflow")
        # 涨跌幅打分（-3% -> 0, +3% -> 80, +5%+ -> 95）
        pct_score = pct.clip(-3, 5).apply(
            lambda x: max(0.0, min(95.0, (x + 3) / 8 * 95))
        )
        # 资金流打分（-3 亿 -> 0, +3 亿 -> 满分 20）
        if flow is not None:
            flow_score = flow.fillna(0).clip(-3e8, 3e8).apply(
                lambda x: max(0.0, min(20.0, (x + 3e8) / 6e8 * 20))
            )
        else:
            flow_score = pd.Series(0.0, index=df.index)
        total = (pct_score + flow_score).round(1)
        for name, score in zip(df["name"].fillna(""), total):
            if not name:
                continue
            # 同一板块出现多次时取更高分
            if score > index.get(name, 0.0):
                index[name] = float(score)
    return index


def score_theme(
    sector_index: dict[str, float],
    stock_sectors: list[str],
) -> dict:
    """题材面打分（0-100）：取关联板块中最高强度。"""
    sub: dict[str, float] = {}
    if not stock_sectors or not sector_index:
        sub["best_sector_score"] = 0.0
        return {"score": 0.0, "details": sub, "best_sector": None}

    best_name = None
    best_score = 0.0
    for sec in stock_sectors:
        sc = sector_index.get(sec, 0.0)
        if sc > best_score:
            best_score = sc
            best_name = sec

    sub["best_sector_score"] = float(best_score)
    return {"score": round(min(best_score, 100.0), 1), "details": sub, "best_sector": best_name}


# ---------- 综合 ----------

def composite_score(tech: dict, money: dict, theme: dict, config: dict) -> dict:
    """三共振加权综合分。"""
    pro = config.get("scanner_pro", {})
    w_tech = pro.get("weight_tech", 0.40)
    w_money = pro.get("weight_money", 0.35)
    w_theme = pro.get("weight_theme", 0.25)

    total = (
        tech["score"] * w_tech
        + money["score"] * w_money
        + theme["score"] * w_theme
    )
    return {
        "total": round(total, 1),
        "tech": tech,
        "money": money,
        "theme": theme,
    }
