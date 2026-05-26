"""选股策略引擎 - 多维度综合评分筛选

策略维度：
- 趋势类：均线多头、MACD金叉、SAR趋势
- 动量类：RSI反弹、KDJ金叉、价格动量
- 量价类：放量突破、缩量回踩、OBV趋势
"""

from typing import Any

import numpy as np
import pandas as pd


def score_volume_breakout(df: pd.DataFrame, config: dict) -> float:
    """放量突破评分"""
    if len(df) < 20:
        return 0.0

    threshold = config.get("indicators", {}).get("volume_ratio_threshold", 1.5)
    latest = df.iloc[-1]
    score = 0.0

    vol_ratio = latest.get("volume_ratio_calc", 0)
    if pd.notna(vol_ratio) and vol_ratio > threshold:
        score += min(vol_ratio / threshold, 3.0) * 20

    recent_high = df["high"].iloc[-20:].max()
    if latest["close"] >= recent_high * 0.98:
        score += 20

    # 放量突破信号
    if latest.get("vol_break", 0) == 1:
        score += 20

    # OBV趋势向上
    obv = latest.get("obv", np.nan)
    obv_ma = latest.get("obv_ma", np.nan)
    if pd.notna(obv) and pd.notna(obv_ma) and obv > obv_ma:
        score += 20

    return min(score, 100.0)


def score_ma_bullish(df: pd.DataFrame, config: dict) -> float:
    """均线多头排列评分"""
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
        score += 40
    elif ma5 > ma10:
        score += 20

    if latest["close"] > ma5:
        score += 20

    # 均线向上发散
    if len(df) >= 5:
        ma5_prev = df["ma5"].iloc[-5]
        if pd.notna(ma5_prev) and ma5 > ma5_prev:
            score += 15

    # SAR确认趋势
    sar_trend = latest.get("sar_trend", 0)
    if sar_trend == 1:
        score += 15

    # VWAP上方
    vwap = latest.get("vwap", np.nan)
    if pd.notna(vwap) and latest["close"] > vwap:
        score += 10

    return min(score, 100.0)


def score_macd_golden_cross(df: pd.DataFrame, config: dict) -> float:
    """MACD金叉评分"""
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

    if prev_dif <= prev_dea and dif > dea:
        score += 50
    elif dif > dea:
        score += 25

    hist = latest.get("macd_hist", 0)
    prev_hist = prev.get("macd_hist", 0)
    if prev_hist < 0 and hist > 0:
        score += 30
    elif hist > 0 and hist > prev_hist:
        score += 15

    # ROC正值且上升
    roc = latest.get("roc", np.nan)
    if pd.notna(roc) and roc > 0:
        score += 20

    return min(score, 100.0)


def score_rsi_bounce(df: pd.DataFrame, config: dict) -> float:
    """RSI超卖反弹评分"""
    if len(df) < 5:
        return 0.0

    ind_config = config.get("indicators", {})
    oversold = ind_config.get("rsi_oversold", 30)
    score = 0.0

    latest_rsi = df["rsi"].iloc[-1]
    if pd.isna(latest_rsi):
        return 0.0

    recent_rsi = df["rsi"].iloc[-5:]
    min_rsi = recent_rsi.min()

    if min_rsi < oversold and latest_rsi > oversold:
        score += 40
    elif min_rsi < oversold + 10 and latest_rsi > min_rsi:
        score += 20

    # RSI连续上升
    rsi_values = recent_rsi.dropna().values
    if len(rsi_values) >= 3:
        increasing = all(rsi_values[i] < rsi_values[i + 1] for i in range(len(rsi_values) - 3, len(rsi_values) - 1))
        if increasing:
            score += 20

    # KDJ金叉
    kdj_k = df["kdj_k"].iloc[-1] if "kdj_k" in df.columns else np.nan
    kdj_d = df["kdj_d"].iloc[-1] if "kdj_d" in df.columns else np.nan
    prev_k = df["kdj_k"].iloc[-2] if "kdj_k" in df.columns else np.nan
    prev_d = df["kdj_d"].iloc[-2] if "kdj_d" in df.columns else np.nan

    if pd.notna(kdj_k) and pd.notna(kdj_d):
        if pd.notna(prev_k) and pd.notna(prev_d) and prev_k <= prev_d and kdj_k > kdj_d:
            score += 25  # KDJ金叉
        elif kdj_k > kdj_d:
            score += 10

    # J值超卖反弹
    kdj_j = df["kdj_j"].iloc[-1] if "kdj_j" in df.columns else np.nan
    if pd.notna(kdj_j) and kdj_j < 20:
        score += 15

    return min(score, 100.0)


def score_price_momentum(df: pd.DataFrame, config: dict) -> float:
    """价格动量评分"""
    if len(df) < 20:
        return 0.0

    latest = df.iloc[-1]
    score = 0.0

    # 5日涨幅：2%-8%之间最佳
    pct_5d = (latest["close"] / df["close"].iloc[-6] - 1) * 100 if len(df) >= 6 else 0
    if 2 <= pct_5d <= 8:
        score += 30
    elif 0 < pct_5d < 2:
        score += 15
    elif 8 < pct_5d <= 12:
        score += 10

    # 价格在布林带中轨附近或中轨上方
    boll_mid = latest.get("boll_mid", np.nan)
    boll_lower = latest.get("boll_lower", np.nan)
    if pd.notna(boll_mid):
        if latest["close"] >= boll_mid:
            score += 20
        elif pd.notna(boll_lower) and latest["close"] >= boll_lower:
            score += 10

    # 近20日整体趋势向上
    if len(df) >= 20:
        slope = np.polyfit(range(20), df["close"].iloc[-20:].values, 1)[0]
        if slope > 0:
            score += 20

    # 涨速加速
    speed_3d = latest.get("speed_3d", np.nan)
    speed_5d = latest.get("speed_5d", np.nan)
    if pd.notna(speed_3d) and pd.notna(speed_5d) and speed_3d > speed_5d > 0:
        score += 15

    # 缩量回踩信号（低吸）
    if latest.get("vol_pullback", 0) == 1:
        score += 15

    return min(score, 100.0)


def score_kdj_signal(df: pd.DataFrame, config: dict) -> float:
    """KDJ信号评分"""
    if len(df) < 9 or "kdj_k" not in df.columns:
        return 0.0

    score = 0.0
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    k = latest.get("kdj_k", np.nan)
    d = latest.get("kdj_d", np.nan)
    j = latest.get("kdj_j", np.nan)
    prev_k = prev.get("kdj_k", np.nan)
    prev_d = prev.get("kdj_d", np.nan)

    if pd.isna(k) or pd.isna(d):
        return 0.0

    # KDJ金叉
    if pd.notna(prev_k) and pd.notna(prev_d):
        if prev_k <= prev_d and k > d:
            score += 50
        elif k > d:
            score += 25

    # J值从低位反弹
    if pd.notna(j):
        if j < 0:
            score += 30
        elif j < 20:
            score += 20

    # K值在合理区间（20-80）
    if 20 < k < 50:
        score += 20

    return min(score, 100.0)


def score_obv_trend(df: pd.DataFrame, config: dict) -> float:
    """OBV资金趋势评分"""
    if "obv" not in df.columns or len(df) < 20:
        return 0.0

    score = 0.0
    latest = df.iloc[-1]

    obv = latest.get("obv", np.nan)
    obv_ma = latest.get("obv_ma", np.nan)

    if pd.notna(obv) and pd.notna(obv_ma):
        # OBV在均线上方
        if obv > obv_ma:
            score += 40

        # OBV趋势向上
        obv_5 = df["obv"].iloc[-5:]
        if len(obv_5.dropna()) >= 5:
            obv_slope = np.polyfit(range(5), obv_5.values, 1)[0]
            if obv_slope > 0:
                score += 30

    # 量价配合：价涨量增
    if len(df) >= 5:
        price_up = df["close"].iloc[-1] > df["close"].iloc[-5]
        vol_up = df["volume"].iloc[-1] > df["volume_ma"].iloc[-1] if "volume_ma" in df.columns else False
        if price_up and vol_up:
            score += 30

    return min(score, 100.0)


STRATEGY_FUNCTIONS = {
    "volume_breakout": score_volume_breakout,
    "ma_bullish": score_ma_bullish,
    "macd_golden_cross": score_macd_golden_cross,
    "rsi_bounce": score_rsi_bounce,
    "price_momentum": score_price_momentum,
    "kdj_signal": score_kdj_signal,
    "obv_trend": score_obv_trend,
}


def calc_composite_score(df: pd.DataFrame, config: dict) -> dict[str, Any]:
    """计算综合评分"""
    weights = config.get("strategy_weights", {})
    scores = {}
    total_score = 0.0

    for name, func in STRATEGY_FUNCTIONS.items():
        weight = weights.get(name, 1.0 / len(STRATEGY_FUNCTIONS))
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
        "kdj_signal": "KDJ信号",
        "obv_trend": "OBV资金趋势",
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

    # SAR作为止损参考
    sar = latest.get("sar", np.nan)
    sar_stop = float(sar) if pd.notna(sar) and sar < close else close - 2 * atr

    return {
        "entry_price": round(close, 2),
        "stop_loss": round(max(sar_stop, close - 2 * atr), 2),
        "target_1": round(close + 2 * atr, 2),
        "target_2": round(close + 3 * atr, 2),
        "stop_loss_pct": round((max(sar_stop, close - 2 * atr) - close) / close * 100, 2),
        "target_1_pct": round(2 * atr / close * 100, 2),
        "target_2_pct": round(3 * atr / close * 100, 2),
    }
