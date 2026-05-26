"""板块概念模块

行业分类、概念题材、板块涨跌幅和龙头识别。
"""

import time

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


def get_industry_sectors() -> pd.DataFrame:
    """获取行业板块排行（东方财富行业分类）"""
    return _fetch_sector_list("m:90+t:2")


def get_concept_sectors() -> pd.DataFrame:
    """获取概念板块排行"""
    return _fetch_sector_list("m:90+t:3")


def _fetch_sector_list(fs: str) -> pd.DataFrame:
    """获取板块列表"""
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
        "fs": fs,
        "fields": "f2,f3,f4,f8,f12,f14,f104,f105,f128,f136,f140",
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
                rows.append({
                    "sector_code": str(item.get("f12", "")),
                    "sector_name": str(item.get("f14", "")),
                    "pct_change": item.get("f3"),
                    "close": item.get("f2"),
                    "turnover_rate": item.get("f8"),
                    "up_count": item.get("f104"),       # 上涨家数
                    "down_count": item.get("f105"),     # 下跌家数
                    "leader_code": item.get("f140"),    # 领涨股代码
                    "leader_name": item.get("f128"),    # 领涨股名称
                    "leader_pct": item.get("f136"),     # 领涨股涨幅
                })

            df = pd.DataFrame(rows)
            for col in df.columns:
                if col not in ("sector_code", "sector_name", "leader_code", "leader_name"):
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        except Exception:
            continue
    return pd.DataFrame()


def get_sector_stocks(sector_code: str) -> pd.DataFrame:
    """获取板块内成分股"""
    urls = [
        "http://push2.eastmoney.com/api/qt/clist/get",
        "http://82.push2.eastmoney.com/api/qt/clist/get",
    ]
    params = {
        "pn": "1",
        "pz": "100",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": f"b:{sector_code}+f:!50",
        "fields": "f2,f3,f4,f5,f6,f7,f8,f10,f12,f14,f15,f16,f17,f18,f62",
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
                rows.append({
                    "code": str(item.get("f12", "")),
                    "name": str(item.get("f14", "")),
                    "pct_change": item.get("f3"),
                    "close": item.get("f2"),
                    "volume_ratio": item.get("f10"),
                    "main_net_inflow": item.get("f62"),
                })

            df = pd.DataFrame(rows)
            for col in df.columns:
                if col not in ("code", "name"):
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        except Exception:
            continue
    return pd.DataFrame()


def get_hot_sectors(top_n: int = 5) -> list[dict]:
    """获取热门板块（概念+行业综合）"""
    results = []

    for label, fetch_func in [("行业", get_industry_sectors), ("概念", get_concept_sectors)]:
        try:
            df = fetch_func()
            if df.empty:
                continue
            df = df.sort_values("pct_change", ascending=False).head(top_n)
            for _, row in df.iterrows():
                results.append({
                    "type": label,
                    "name": row.get("sector_name", ""),
                    "pct_change": row.get("pct_change", 0),
                    "up_count": int(row.get("up_count", 0)) if pd.notna(row.get("up_count")) else 0,
                    "down_count": int(row.get("down_count", 0)) if pd.notna(row.get("down_count")) else 0,
                    "leader_name": row.get("leader_name", ""),
                    "leader_pct": row.get("leader_pct", 0),
                    "sector_code": row.get("sector_code", ""),
                })
        except Exception:
            continue

    results.sort(key=lambda x: x.get("pct_change", 0), reverse=True)
    return results[:top_n]
