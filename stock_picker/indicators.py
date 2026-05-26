"""技术指标计算模块

包含趋势类、动量类、量价类指标。
"""

import numpy as np
import pandas as pd


# ========== 趋势类指标 ==========

def calc_ma(df: pd.DataFrame, periods: list[int]) -> pd.DataFrame:
    """计算移动平均线"""
    for p in periods:
        df[f"ma{p}"] = df["close"].rolling(window=p).mean()
    return df


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """计算指数移动平均"""
    return series.ewm(span=period, adjust=False).mean()


def calc_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """计算MACD指标"""
    ema_fast = calc_ema(df["close"], fast)
    ema_slow = calc_ema(df["close"], slow)
    df["macd_dif"] = ema_fast - ema_slow
    df["macd_dea"] = calc_ema(df["macd_dif"], signal)
    df["macd_hist"] = 2 * (df["macd_dif"] - df["macd_dea"])
    return df


def calc_bollinger(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """计算布林带"""
    df["boll_mid"] = df["close"].rolling(window=period).mean()
    rolling_std = df["close"].rolling(window=period).std()
    df["boll_upper"] = df["boll_mid"] + std_dev * rolling_std
    df["boll_lower"] = df["boll_mid"] - std_dev * rolling_std
    return df


def calc_sar(df: pd.DataFrame, af_start: float = 0.02, af_step: float = 0.02, af_max: float = 0.2) -> pd.DataFrame:
    """计算SAR（抛物线转向指标）"""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)
    sar = np.zeros(n)
    trend = np.ones(n)  # 1=上升, -1=下降
    af = af_start
    ep = high[0]
    sar[0] = low[0]

    for i in range(1, n):
        if trend[i - 1] == 1:
            sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
            sar[i] = min(sar[i], low[i - 1], low[max(0, i - 2)])
            if low[i] < sar[i]:
                trend[i] = -1
                sar[i] = ep
                ep = low[i]
                af = af_start
            else:
                trend[i] = 1
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + af_step, af_max)
        else:
            sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
            sar[i] = max(sar[i], high[i - 1], high[max(0, i - 2)])
            if high[i] > sar[i]:
                trend[i] = 1
                sar[i] = ep
                ep = high[i]
                af = af_start
            else:
                trend[i] = -1
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + af_step, af_max)

    df["sar"] = sar
    df["sar_trend"] = trend
    return df


# ========== 动量类指标 ==========

def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """计算RSI指标"""
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def calc_kdj(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
    """计算KDJ指标"""
    low_n = df["low"].rolling(window=n).min()
    high_n = df["high"].rolling(window=n).max()
    rsv = (df["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100

    k = np.zeros(len(df))
    d = np.zeros(len(df))
    k[0] = 50
    d[0] = 50
    rsv_vals = rsv.fillna(50).values

    for i in range(1, len(df)):
        k[i] = (m1 - 1) / m1 * k[i - 1] + 1 / m1 * rsv_vals[i]
        d[i] = (m2 - 1) / m2 * d[i - 1] + 1 / m2 * k[i]

    df["kdj_k"] = k
    df["kdj_d"] = d
    df["kdj_j"] = 3 * k - 2 * d
    return df


def calc_roc(df: pd.DataFrame, period: int = 12) -> pd.DataFrame:
    """计算ROC（变动率指标）"""
    df["roc"] = (df["close"] / df["close"].shift(period) - 1) * 100
    return df


def calc_price_speed(df: pd.DataFrame) -> pd.DataFrame:
    """计算涨速（近N分钟/日涨幅加速度）"""
    df["speed_1d"] = df["close"].pct_change() * 100
    df["speed_3d"] = (df["close"] / df["close"].shift(3) - 1) * 100
    df["speed_5d"] = (df["close"] / df["close"].shift(5) - 1) * 100
    return df


# ========== 量价类指标 ==========

def calc_volume_ma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """计算成交量均线"""
    df["volume_ma"] = df["volume"].rolling(window=period).mean()
    df["volume_ma5"] = df["volume"].rolling(window=5).mean()
    df["volume_ratio_calc"] = df["volume"] / df["volume_ma"].replace(0, np.nan)
    return df


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """计算ATR（平均真实波幅）"""
    high_low = df["high"] - df["low"]
    high_prev_close = (df["high"] - df["close"].shift(1)).abs()
    low_prev_close = (df["low"] - df["close"].shift(1)).abs()
    true_range = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
    df["atr"] = true_range.rolling(window=period).mean()
    return df


def calc_obv(df: pd.DataFrame) -> pd.DataFrame:
    """计算OBV（能量潮指标）"""
    direction = np.sign(df["close"].diff())
    direction.iloc[0] = 0
    df["obv"] = (direction * df["volume"]).cumsum()
    df["obv_ma"] = df["obv"].rolling(window=20).mean()
    return df


def calc_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """计算VWAP（成交量加权平均价）- 基于日线的滚动VWAP"""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cum_tp_vol = (typical_price * df["volume"]).rolling(window=20).sum()
    cum_vol = df["volume"].rolling(window=20).sum()
    df["vwap"] = cum_tp_vol / cum_vol.replace(0, np.nan)
    return df


def calc_volume_breakout(df: pd.DataFrame) -> pd.DataFrame:
    """计算放量突破和缩量回踩信号"""
    df["vol_break"] = 0
    df["vol_pullback"] = 0

    if len(df) < 20:
        return df

    vol_ratio = df["volume_ratio_calc"]
    pct = df["close"].pct_change() * 100

    # 放量突破：量比>1.5 且 涨幅>1%
    df.loc[(vol_ratio > 1.5) & (pct > 1), "vol_break"] = 1
    # 缩量回踩：量比<0.8 且 回调<-0.5% 且 在上升趋势中
    if "ma20" in df.columns:
        in_uptrend = df["close"] > df["ma20"]
        df.loc[(vol_ratio < 0.8) & (pct < -0.5) & (pct > -3) & in_uptrend, "vol_pullback"] = 1

    return df


def calc_amount_avg(df: pd.DataFrame) -> pd.DataFrame:
    """计算成交额均值（过滤流动性差的票）"""
    if "amount" in df.columns:
        df["amount_ma5"] = df["amount"].rolling(window=5).mean()
        df["amount_ma20"] = df["amount"].rolling(window=20).mean()
    return df


# ========== 统一入口 ==========

def calc_all_indicators(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """计算所有技术指标"""
    ind_config = config.get("indicators", {})

    # 趋势类
    df = calc_ma(df, ind_config.get("ma_periods", [5, 10, 20, 60]))
    df = calc_macd(
        df,
        fast=ind_config.get("macd_fast", 12),
        slow=ind_config.get("macd_slow", 26),
        signal=ind_config.get("macd_signal", 9),
    )
    df = calc_bollinger(df)
    df = calc_sar(df)

    # 动量类
    df = calc_rsi(df, period=ind_config.get("rsi_period", 14))
    df = calc_kdj(df)
    df = calc_roc(df)
    df = calc_price_speed(df)

    # 量价类
    df = calc_volume_ma(df)
    df = calc_atr(df)
    df = calc_obv(df)
    df = calc_vwap(df)
    df = calc_volume_breakout(df)
    df = calc_amount_avg(df)

    return df
