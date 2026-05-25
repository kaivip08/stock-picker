"""技术指标计算模块"""

import numpy as np
import pandas as pd


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


def calc_volume_ma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """计算成交量均线"""
    df["volume_ma"] = df["volume"].rolling(window=period).mean()
    df["volume_ratio_calc"] = df["volume"] / df["volume_ma"].replace(0, np.nan)
    return df


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """计算ATR（平均真实波幅），用于止损参考"""
    high_low = df["high"] - df["low"]
    high_prev_close = (df["high"] - df["close"].shift(1)).abs()
    low_prev_close = (df["low"] - df["close"].shift(1)).abs()
    true_range = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
    df["atr"] = true_range.rolling(window=period).mean()
    return df


def calc_bollinger(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """计算布林带"""
    df["boll_mid"] = df["close"].rolling(window=period).mean()
    rolling_std = df["close"].rolling(window=period).std()
    df["boll_upper"] = df["boll_mid"] + std_dev * rolling_std
    df["boll_lower"] = df["boll_mid"] - std_dev * rolling_std
    return df


def calc_all_indicators(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """计算所有技术指标"""
    ind_config = config.get("indicators", {})

    df = calc_ma(df, ind_config.get("ma_periods", [5, 10, 20, 60]))
    df = calc_macd(
        df,
        fast=ind_config.get("macd_fast", 12),
        slow=ind_config.get("macd_slow", 26),
        signal=ind_config.get("macd_signal", 9),
    )
    df = calc_rsi(df, period=ind_config.get("rsi_period", 14))
    df = calc_volume_ma(df)
    df = calc_atr(df)
    df = calc_bollinger(df)
    return df
