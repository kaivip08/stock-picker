"""选股策略引擎 - 综合评分筛选"""

from typing import Any

import numpy as np
import pandas as pd


def score_volume_breakout(df: pd.DataFrame, config: dict) -> float:
    """放量突破评分
    - 最近一日成交量 > N倍20日均量
    - 价格突破近20日最高价
    """
    if len(df) < 20:
        return 0.0

    threshold = config.get("indicators", {}).get("volume_ratio_threshold", 1.5)
    latest = df.iloc[-1]
    score = 0.0

    vol_ratio = latest.get("volume_ratio_calc", 0)
    if pd.notna(vol_ratio) and vol_ratio > threshold:
        score += min(vol_ratio / threshold, 3.0) * 25

    recent_high = df["high"].iloc[-20:].max()
    if latest["close"] >= recent_high * 0.98:
        score += 25

    return min(score, 100.0)


def score_ma_bullish(df: pd.DataFrame, config: dict) -> float:
    """均线多头排列评分
    - MA5 > MA10 > MA20
    - 价格在均线上方
    """
    if len(df) < 20:
        return 0.0

    latest = df.iloc[-1]
    score = 0.0

    ma5 = latest.get("ma5", np.nan)
    ma10 = latest.get("ma10", np.nan)
    ma20 = latest.get("ma20", np.nan)

    if pd.isna(ma5) or pd.isna(ma10) or pd.isna(ma20):
        return 0.0

    if ma5 > ma10 > ma20:
        score += 50
    elif ma5 > ma10:
        score += 25

    if latest["close"] > ma5:
        score += 25

    # 均线向上发散
    if len(df) >= 5:
        ma5_prev = df["ma5"].iloc[-5]
        if pd.notna(ma5_prev) and ma5 > ma5_prev:
            score += 25

    return min(score, 100.0)


def score_macd_golden_cross(df: pd.DataFrame, config: dict) -> float:
    """MACD金叉评分
    - DIF上穿DEA（金叉）
    - MACD柱状图由负转正
    """
    if len(df) < 5:
        return 0.0

    score = 0.0
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    dif = latest.get("macd_dif", np.nan)
    dea = latest.get("macd_dea", np.nan)
    prev_dif = prev.get("macd_dif", np.nan)
    prev_dea = prev.get("macd_dea", np.nan)

    if pd.isna(dif) or pd.isna(dea) or pd.isna(prev_dif) or pd.isna(prev_dea):
        return 0.0

    # 金叉：DIF从下方穿越DEA
    if prev_dif <= prev_dea and dif > dea:
        score += 60
    elif dif > dea:
        score += 30

    # MACD柱状图由负转正
    hist = latest.get("macd_hist", 0)
    prev_hist = prev.get("macd_hist", 0)
    if prev_hist < 0 and hist > 0:
        score += 40
    elif hist > 0 and hist > prev_hist:
        score += 20

    return min(score, 100.0)


def score_rsi_bounce(df: pd.DataFrame, config: dict) -> float:
    """RSI超卖反弹评分
    - RSI从超卖区域（<30）反弹
    - RSI连续上升
    """
    if len(df) < 5:
        return 0.0

    ind_config = config.get("indicators", {})
    oversold = ind_config.get("rsi_oversold", 30)
    score = 0.0

    latest_rsi = df["rsi"].iloc[-1]
    if pd.isna(latest_rsi):
        return 0.0

    # 近5日内是否有RSI低于超卖线
    recent_rsi = df["rsi"].iloc[-5:]
    min_rsi = recent_rsi.min()

    if min_rsi < oversold and latest_rsi > oversold:
        score += 60
    elif min_rsi < oversold + 10 and latest_rsi > min_rsi:
        score += 30

    # RSI连续上升
    rsi_values = recent_rsi.dropna().values
    if len(rsi_values) >= 3:
        increasing = all(rsi_values[i] < rsi_values[i + 1] for i in range(len(rsi_values) - 3, len(rsi_values) - 1))
        if increasing:
            score += 40

    return min(score, 100.0)


def score_price_momentum(df: pd.DataFrame, config: dict) -> float:
    """价格动量评分
    - 近期涨幅适中（不是暴涨，有上升趋势）
    - 回调到支撑位附近
    """
    if len(df) < 20:
        return 0.0

    latest = df.iloc[-1]
    score = 0.0

    # 5日涨幅：2%-8%之间最佳
    pct_5d = (latest["close"] / df["close"].iloc[-6] - 1) * 100 if len(df) >= 6 else 0
    if 2 <= pct_5d <= 8:
        score += 40
    elif 0 < pct_5d < 2:
        score += 20
    elif 8 < pct_5d <= 12:
        score += 15

    # 价格在布林带中轨附近或中轨上方
    boll_mid = latest.get("boll_mid", np.nan)
    boll_lower = latest.get("boll_lower", np.nan)
    if pd.notna(boll_mid):
        if latest["close"] >= boll_mid:
            score += 30
        elif pd.notna(boll_lower) and latest["close"] >= boll_lower:
            score += 15

    # 近20日整体趋势向上
    if len(df) >= 20:
        slope = np.polyfit(range(20), df["close"].iloc[-20:].values, 1)[0]
        if slope > 0:
            score += 30

    return min(score, 100.0)


STRATEGY_FUNCTIONS = {
    "volume_breakout": score_volume_breakout,
    "ma_bullish": score_ma_bullish,
    "macd_golden_cross": score_macd_golden_cross,
    "rsi_bounce": score_rsi_bounce,
    "price_momentum": score_price_momentum,
}


def calc_composite_score(df: pd.DataFrame, config: dict) -> dict[str, Any]:
    """计算综合评分"""
    weights = config.get("strategy_weights", {})
    scores = {}
    total_score = 0.0

    for name, func in STRATEGY_FUNCTIONS.items():
        weight = weights.get(name, 0.2)
        raw_score = func(df, config)
        weighted_score = raw_score * weight
        scores[name] = {"raw": round(raw_score, 1), "weighted": round(weighted_score, 1)}
        total_score += weighted_score

    return {
        "total_score": round(total_score, 1),
        "details": scores,
    }


def generate_reasons(score_details: dict[str, Any]) -> list[str]:
    """根据评分生成推荐理由"""
    reasons = []
    labels = {
        "volume_breakout": "放量突破",
        "ma_bullish": "均线多头",
        "macd_golden_cross": "MACD金叉",
        "rsi_bounce": "RSI反弹",
        "price_momentum": "价格动量",
    }

    sorted_details = sorted(
        score_details.items(),
        key=lambda x: x[1]["raw"],
        reverse=True,
    )

    for name, detail in sorted_details:
        if detail["raw"] >= 50:
            reasons.append(f"✦ {labels.get(name, name)}信号强（{detail['raw']}分）")
        elif detail["raw"] >= 30:
            reasons.append(f"◦ {labels.get(name, name)}信号中等（{detail['raw']}分）")

    return reasons if reasons else ["综合指标表现平稳"]


def calc_stop_loss(df: pd.DataFrame) -> dict[str, float]:
    """计算建议止损止盈位"""
    latest = df.iloc[-1]
    atr = latest.get("atr", 0)
    close = latest["close"]

    if pd.isna(atr) or atr == 0:
        atr = close * 0.02

    return {
        "entry_price": round(close, 2),
        "stop_loss": round(close - 2 * atr, 2),
        "target_1": round(close + 2 * atr, 2),
        "target_2": round(close + 3 * atr, 2),
        "stop_loss_pct": round(-2 * atr / close * 100, 2),
        "target_1_pct": round(2 * atr / close * 100, 2),
        "target_2_pct": round(3 * atr / close * 100, 2),
    }
