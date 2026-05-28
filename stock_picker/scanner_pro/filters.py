"""Pro Scanner 硬性筛选层（方案 §2.2）。

候选股必须同时满足：
- 严格主板（沪 60xxxx / 深 000xxx-003xxx），剔除 ST / 退市风险
- 流通市值 30 亿 – 300 亿
- 股价 3 – 50 元
- 日成交额 >= 1 亿（保证流动性）
- 换手率 >= 阈值（默认 3%，盘中扫描可放宽到 2%）
- 距 60 日均线 ±15% 以内（避开高位与下跌趋势）
- 当日涨跌幅 < +9.5%（剔除已封板，避免追涨停）
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from stock_picker.scanner_pro.data import is_main_board_code


def apply_hard_filters(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    """按 §2.2 条件硬性筛选候选池。

    返回筛选后的 DataFrame；如果某列缺失则跳过对应过滤。
    """
    if df.empty:
        return df

    pro = config.get("scanner_pro", {})

    out = df.copy()

    # 1) 严格主板
    out = out[out["code"].apply(is_main_board_code)].copy()

    # 2) 剔除 ST / 退市风险
    if "name" in out.columns:
        bad = out["name"].str.contains("ST|退", case=False, na=False, regex=True)
        out = out[~bad].copy()

    # 3) 剔除当日已收盘价为零或停牌
    if "close" in out.columns:
        out = out[out["close"].fillna(0) > 0].copy()

    # 4) 流通市值范围（元）
    cap_min = pro.get("circ_mcap_min_yi", 30) * 1e8
    cap_max = pro.get("circ_mcap_max_yi", 300) * 1e8
    if "circulating_market_cap" in out.columns:
        cmc = out["circulating_market_cap"]
        # 当东财返回缺失时保留，避免过度剔除
        out = out[cmc.isna() | ((cmc >= cap_min) & (cmc <= cap_max))].copy()

    # 5) 股价范围
    price_min = pro.get("price_min", 3.0)
    price_max = pro.get("price_max", 50.0)
    if "close" in out.columns:
        out = out[(out["close"] >= price_min) & (out["close"] <= price_max)].copy()

    # 6) 日成交额下限（元）
    amount_min = pro.get("amount_min_yi", 1.0) * 1e8
    if "amount" in out.columns:
        out = out[out["amount"].fillna(0) >= amount_min].copy()

    # 7) 换手率下限（%）
    turnover_min = pro.get("turnover_rate_min", 3.0)
    if "turnover_rate" in out.columns:
        tr = out["turnover_rate"]
        out = out[tr.isna() | (tr >= turnover_min)].copy()

    # 8) 当日涨跌幅上限（剔除已封板的 +10%）
    pct_max = pro.get("pct_change_max", 9.5)
    if "pct_change" in out.columns:
        pct = out["pct_change"]
        out = out[pct.isna() | (pct < pct_max)].copy()

    # 9) 当日涨跌幅下限（剔除大跌票，方案偏强势思路）
    pct_min = pro.get("pct_change_min", -4.0)
    if "pct_change" in out.columns:
        pct = out["pct_change"]
        out = out[pct.isna() | (pct >= pct_min)].copy()

    return out.reset_index(drop=True)


def apply_history_filters(
    hist_df: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """对单只股票的历史 K 线做二次硬性筛选。

    返回 (pass_or_not, info_dict)。info_dict 含可用于打分的中间量。
    """
    pro = config.get("scanner_pro", {})
    info: dict[str, Any] = {}

    if hist_df is None or len(hist_df) < 30:
        return False, {"reason": "history_too_short"}

    last = hist_df.iloc[-1]
    close_now = float(last["close"])
    info["close"] = close_now

    # 距 60 日均线偏离
    if "ma60" in hist_df.columns and pd.notna(last.get("ma60")):
        ma60 = float(last["ma60"])
        dist = (close_now - ma60) / ma60 * 100 if ma60 > 0 else 0
        info["dist_to_ma60_pct"] = dist
        max_dist = pro.get("max_dist_to_ma60_pct", 15.0)
        if abs(dist) > max_dist:
            return False, {**info, "reason": "too_far_from_ma60"}
    elif len(hist_df) >= 60:
        # 历史够长但没算出 ma60，跳过该过滤
        info["dist_to_ma60_pct"] = None
    else:
        info["dist_to_ma60_pct"] = None

    # ATR / 股价 比率（弹性，方案要求 >= 3%）
    if "atr" in hist_df.columns and pd.notna(last.get("atr")):
        atr = float(last["atr"])
        atr_ratio = atr / close_now * 100 if close_now > 0 else 0
        info["atr_pct"] = atr_ratio
        min_atr = pro.get("min_atr_pct", 3.0)
        if atr_ratio < min_atr:
            return False, {**info, "reason": "atr_too_low"}

    # 近 5 日均成交额（元）
    if "amount" in hist_df.columns and len(hist_df) >= 5:
        avg_amt_5d = float(hist_df["amount"].iloc[-5:].mean())
        info["avg_amount_5d"] = avg_amt_5d
        min_avg = pro.get("avg_amount_min_yi", 0.8) * 1e8
        if avg_amt_5d < min_avg:
            return False, {**info, "reason": "avg_amount_too_low"}

    # 近 60 日累计涨幅过大（>= 80%）则剔除（防止追高接盘）
    if len(hist_df) >= 60:
        cum_pct = (close_now / float(hist_df["close"].iloc[-60]) - 1) * 100
        info["cum_pct_60d"] = cum_pct
        max_cum = pro.get("max_cum_pct_60d", 80.0)
        if cum_pct > max_cum:
            return False, {**info, "reason": "overheated_60d"}

    return True, info
