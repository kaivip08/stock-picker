"""市场情绪指标模块

涨停数/跌停数/连板高度/炸板率/赚钱效应等。
"""

import time
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _create_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=Retry(total=2, backoff_factor=1))
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://data.eastmoney.com/",
    })
    return session


_session = _create_session()


def get_limit_up_stocks() -> pd.DataFrame:
    """获取涨停股列表"""
    urls = [
        "http://push2.eastmoney.com/api/qt/clist/get",
        "http://82.push2.eastmoney.com/api/qt/clist/get",
    ]
    params = {
        "pn": "1",
        "pz": "500",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f2,f3,f4,f5,f6,f7,f8,f12,f14,f15,f16,f17,f18",
        "_": str(int(time.time() * 1000)),
    }

    for url in urls:
        try:
            resp = _session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", {}).get("diff", [])
            if not items:
                continue

            rows = []
            for item in items:
                pct = item.get("f3")
                if pct is None:
                    continue
                try:
                    pct_val = float(pct)
                except (ValueError, TypeError):
                    continue
                if pct_val >= 9.9:
                    rows.append({
                        "code": str(item.get("f12", "")),
                        "name": str(item.get("f14", "")),
                        "pct_change": pct_val,
                        "close": item.get("f2"),
                        "amount": item.get("f6"),
                    })
            return pd.DataFrame(rows) if rows else pd.DataFrame()
        except Exception:
            continue
    return pd.DataFrame()


def get_limit_down_stocks() -> pd.DataFrame:
    """获取跌停股列表"""
    urls = [
        "http://push2.eastmoney.com/api/qt/clist/get",
        "http://82.push2.eastmoney.com/api/qt/clist/get",
    ]
    params = {
        "pn": "1",
        "pz": "500",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f2,f3,f4,f5,f6,f7,f8,f12,f14",
        "_": str(int(time.time() * 1000)),
    }

    for url in urls:
        try:
            resp = _session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", {}).get("diff", [])
            if not items:
                continue

            rows = []
            for item in items:
                pct = item.get("f3")
                if pct is None:
                    continue
                try:
                    pct_val = float(pct)
                except (ValueError, TypeError):
                    continue
                if pct_val <= -9.9:
                    rows.append({
                        "code": str(item.get("f12", "")),
                        "name": str(item.get("f14", "")),
                        "pct_change": pct_val,
                    })
            return pd.DataFrame(rows) if rows else pd.DataFrame()
        except Exception:
            continue
    return pd.DataFrame()


def calc_market_sentiment(all_stocks_df: pd.DataFrame) -> dict[str, Any]:
    """基于全市场数据计算市场情绪指标"""
    if all_stocks_df.empty or "pct_change" not in all_stocks_df.columns:
        return _empty_sentiment()

    pct = all_stocks_df["pct_change"].dropna()
    if pct.empty:
        return _empty_sentiment()

    total = len(pct)
    up_count = int((pct > 0).sum())
    down_count = int((pct < 0).sum())
    flat_count = int((pct == 0).sum())
    limit_up = int((pct >= 9.9).sum())
    limit_down = int((pct <= -9.9).sum())

    # 赚钱效应：上涨占比
    profit_ratio = up_count / total * 100 if total > 0 else 0
    # 亏钱效应：下跌占比
    loss_ratio = down_count / total * 100 if total > 0 else 0

    return {
        "total_stocks": total,
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "limit_up_count": limit_up,
        "limit_down_count": limit_down,
        "profit_ratio": round(profit_ratio, 1),
        "loss_ratio": round(loss_ratio, 1),
        "avg_pct_change": round(float(pct.mean()), 2),
        "median_pct_change": round(float(pct.median()), 2),
        "sentiment_score": _calc_sentiment_score(profit_ratio, limit_up, limit_down, total),
    }


def _calc_sentiment_score(profit_ratio: float, limit_up: int, limit_down: int, total: int) -> float:
    """计算市场情绪综合评分 (0-100)"""
    score = 0.0
    # 赚钱效应占40分
    score += min(profit_ratio / 100 * 40, 40)
    # 涨停数量占30分
    limit_up_ratio = limit_up / total * 100 if total > 0 else 0
    score += min(limit_up_ratio * 10, 30)
    # 涨跌停比占30分
    if limit_down > 0:
        ratio = limit_up / limit_down
        score += min(ratio * 10, 30)
    elif limit_up > 0:
        score += 30
    return round(min(score, 100), 1)


def _empty_sentiment() -> dict[str, Any]:
    return {
        "total_stocks": 0, "up_count": 0, "down_count": 0, "flat_count": 0,
        "limit_up_count": 0, "limit_down_count": 0,
        "profit_ratio": 0, "loss_ratio": 0,
        "avg_pct_change": 0, "median_pct_change": 0, "sentiment_score": 0,
    }


def get_index_quotes() -> dict[str, dict[str, float]]:
    """获取主要指数行情"""
    indices = {
        "1.000001": "上证指数",
        "0.399001": "深证成指",
        "0.399006": "创业板指",
        "1.000688": "科创50",
        "0.399005": "中小100",
        "1.000300": "沪深300",
        "1.000905": "中证500",
        "2.932000": "中证1000",
    }
    codes = ",".join(indices.keys())
    urls = [
        "http://push2.eastmoney.com/api/qt/ulist.np/get",
        "http://82.push2.eastmoney.com/api/qt/ulist.np/get",
    ]
    params = {
        "fltt": "2",
        "secids": codes,
        "fields": "f2,f3,f4,f12,f14",
        "_": str(int(time.time() * 1000)),
    }

    for url in urls:
        try:
            resp = _session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", {}).get("diff", [])
            result = {}
            for item in items:
                name = str(item.get("f14", ""))
                result[name] = {
                    "close": item.get("f2"),
                    "pct_change": item.get("f3"),
                    "change": item.get("f4"),
                }
            return result
        except Exception:
            continue
    return {}
