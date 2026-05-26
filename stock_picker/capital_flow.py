"""资金流向数据模块

获取主力资金、北向资金、融资融券等数据。
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


def get_capital_flow_rank() -> pd.DataFrame:
    """获取个股主力资金流向排行（东方财富）"""
    urls = [
        "http://push2.eastmoney.com/api/qt/clist/get",
        "http://82.push2.eastmoney.com/api/qt/clist/get",
    ]
    params = {
        "pn": "1",
        "pz": "200",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f62",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f12,f14,f62,f66,f69,f72,f75,f78,f81,f84,f87,f184,f204,f205,f124",
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
                    "main_net_inflow": item.get("f62"),          # 主力净流入
                    "super_large_net": item.get("f66"),          # 超大单净流入
                    "super_large_pct": item.get("f69"),          # 超大单净占比
                    "large_net": item.get("f72"),                # 大单净流入
                    "large_pct": item.get("f75"),                # 大单净占比
                    "medium_net": item.get("f78"),               # 中单净流入
                    "small_net": item.get("f84"),                # 小单净流入
                    "main_net_pct": item.get("f184"),            # 主力净占比
                })

            df = pd.DataFrame(rows)
            for col in df.columns:
                if col not in ("code", "name"):
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        except Exception:
            continue

    return pd.DataFrame()


def get_north_flow() -> dict[str, Any]:
    """获取北向资金数据"""
    url = "http://push2.eastmoney.com/api/qt/kamt.rtmin/get"
    params = {
        "fields1": "f1,f2,f3,f4",
        "fields2": "f51,f52,f53,f54,f55,f56",
        "_": str(int(time.time() * 1000)),
    }
    try:
        resp = _session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        s2n = data.get("s2n", [])
        if s2n:
            latest = s2n[-1].split(",")
            return {
                "hk_to_sh": float(latest[1]) if len(latest) > 1 and latest[1] != "-" else 0,
                "hk_to_sz": float(latest[2]) if len(latest) > 2 and latest[2] != "-" else 0,
                "total": float(latest[3]) if len(latest) > 3 and latest[3] != "-" else 0,
            }
    except Exception:
        pass
    return {"hk_to_sh": 0, "hk_to_sz": 0, "total": 0}


def get_margin_data() -> pd.DataFrame:
    """获取融资融券数据"""
    url = "http://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPTA_WEB_RZRQ_GGMX",
        "columns": "ALL",
        "pageSize": "200",
        "pageNumber": "1",
        "sortColumns": "RZJME",
        "sortTypes": "-1",
        "source": "WEB",
        "_": str(int(time.time() * 1000)),
    }
    try:
        resp = _session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("result", {}).get("data", [])
        if data:
            rows = []
            for item in data:
                rows.append({
                    "code": item.get("SCODE", ""),
                    "name": item.get("SECNAME", ""),
                    "margin_buy": item.get("RZJME"),       # 融资净买入
                    "margin_balance": item.get("RZYE"),     # 融资余额
                    "short_sell": item.get("RQJME"),        # 融券净卖出
                    "short_balance": item.get("RQYE"),      # 融券余额
                })
            df = pd.DataFrame(rows)
            for col in ["margin_buy", "margin_balance", "short_sell", "short_balance"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
    except Exception:
        pass
    return pd.DataFrame()
