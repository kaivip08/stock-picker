"""数据获取模块 - 使用AKShare获取A股行情数据"""

import os
import random
import time
from datetime import datetime, timedelta
from typing import Any

import akshare as ak
import pandas as pd
import requests


# 设置请求头，避免被服务器拒绝
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://quote.eastmoney.com/",
}


def _patch_session() -> None:
    """为requests设置默认headers和超时，提高连接稳定性"""
    original_get = requests.Session.get
    original_post = requests.Session.post

    def patched_get(self: requests.Session, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", 30)
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        for k, v in _HEADERS.items():
            kwargs["headers"].setdefault(k, v)
        return original_get(self, url, **kwargs)

    def patched_post(self: requests.Session, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", 30)
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        for k, v in _HEADERS.items():
            kwargs["headers"].setdefault(k, v)
        return original_post(self, url, **kwargs)

    requests.Session.get = patched_get  # type: ignore[assignment]
    requests.Session.post = patched_post  # type: ignore[assignment]


# 在模块加载时应用补丁
_patch_session()


def _retry_call(func: Any, max_retries: int = 5, base_delay: float = 2.0, **kwargs: Any) -> Any:
    """带指数退避的重试调用"""
    last_error = None
    for attempt in range(max_retries):
        try:
            result = func(**kwargs)
            return result
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                print(f"\n  ⚠ 请求失败（第{attempt + 1}次），{delay:.1f}秒后重试: {type(e).__name__}")
                time.sleep(delay)
    raise last_error  # type: ignore[misc]


def get_all_a_stocks() -> pd.DataFrame:
    """获取所有A股股票列表（带重试）"""
    df = _retry_call(ak.stock_zh_a_spot_em, max_retries=5, base_delay=3.0)
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
    retry_times: int = 5,
    interval: float = 1.0,
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
                delay = interval * (2 ** attempt) + random.uniform(0, 0.5)
                time.sleep(delay)
            continue
    return None


def batch_get_history(
    codes: list[str],
    days: int = 120,
    retry_times: int = 5,
    interval: float = 1.0,
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
        # 随机间隔，避免请求过于规律被限流
        time.sleep(interval + random.uniform(0, 0.5))
    return result
