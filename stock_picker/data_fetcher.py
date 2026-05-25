"""数据获取模块 - 使用AKShare获取A股行情数据"""

import time
from datetime import datetime, timedelta
from typing import Any

import akshare as ak
import pandas as pd


def get_all_a_stocks() -> pd.DataFrame:
    """获取所有A股股票列表"""
    df = ak.stock_zh_a_spot_em()
    df = df.rename(columns={
        "代码": "code",
        "名称": "name",
        "最新价": "close",
        "涨跌幅": "pct_change",
        "涨跌额": "change",
        "成交量": "volume",
        "成交额": "amount",
        "振幅": "amplitude",
        "最高": "high",
        "最低": "low",
        "今开": "open",
        "昨收": "pre_close",
        "量比": "volume_ratio",
        "换手率": "turnover_rate",
        "市盈率-动态": "pe_ratio",
        "市净率": "pb_ratio",
        "总市值": "total_market_cap",
        "流通市值": "circulating_market_cap",
    })
    return df


def filter_stocks(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    """根据配置过滤股票"""
    selection = config.get("selection", {})

    # 过滤无效数据
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0].copy()

    # 排除ST股
    if selection.get("exclude_st", True):
        df = df[~df["name"].str.contains("ST", case=False, na=False)]

    # 排除科创板（688开头）
    if selection.get("exclude_kcb", False):
        df = df[~df["code"].str.startswith("688")]

    # 排除北交所（8开头）
    if selection.get("exclude_bse", True):
        df = df[~df["code"].str.startswith("8")]

    # 过滤最小流通市值
    min_cap = selection.get("min_market_cap", 30)
    if "circulating_market_cap" in df.columns:
        df = df[df["circulating_market_cap"] >= min_cap * 1e8]

    # 排除涨停/跌停的股票（无法买入）
    df = df[df["pct_change"].abs() < 9.9]

    return df.reset_index(drop=True)


def get_stock_history(
    code: str,
    days: int = 120,
    retry_times: int = 3,
    interval: float = 0.5,
) -> pd.DataFrame | None:
    """获取单只股票的历史行情数据"""
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    for attempt in range(retry_times):
        try:
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "日期": "date",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "volume",
                    "成交额": "amount",
                    "振幅": "amplitude",
                    "涨跌幅": "pct_change",
                    "涨跌额": "change",
                    "换手率": "turnover_rate",
                })
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
                return df
        except Exception:
            if attempt < retry_times - 1:
                time.sleep(interval * (attempt + 1))
            continue
    return None


def batch_get_history(
    codes: list[str],
    days: int = 120,
    retry_times: int = 3,
    interval: float = 0.5,
    progress_callback: Any = None,
) -> dict[str, pd.DataFrame]:
    """批量获取多只股票的历史数据"""
    result = {}
    total = len(codes)
    for i, code in enumerate(codes):
        df = get_stock_history(code, days, retry_times, interval)
        if df is not None and len(df) >= 30:
            result[code] = df
        if progress_callback:
            progress_callback(i + 1, total, code)
        time.sleep(interval)
    return result
