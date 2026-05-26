"""基本面数据模块

获取财务报表数据：营收、利润、ROE、PE/PB/PS等。
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

_DATACENTER_URL = "http://datacenter-web.eastmoney.com/api/data/v1/get"


def get_financial_indicators(page_size: int = 500) -> pd.DataFrame:
    """获取最新财务指标数据（东方财富）

    返回字段：
    - eps: 每股收益
    - roe: 加权ROE
    - revenue_yoy: 营收同比增长率
    - profit_yoy: 净利润同比增长率
    - gross_margin: 毛利率
    - bps: 每股净资产
    - ocf_per_share: 每股经营现金流
    """
    params = {
        "reportName": "RPT_LICO_FN_CPD",
        "columns": "ALL",
        "pageSize": str(page_size),
        "pageNumber": "1",
        "sortColumns": "UPDATE_DATE,SECURITY_CODE",
        "sortTypes": "-1,-1",
        "source": "WEB",
        "client": "WEB",
        "_": str(int(time.time() * 1000)),
    }

    try:
        resp = _session.get(_DATACENTER_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        items = result.get("data", [])

        if not items:
            return pd.DataFrame()

        rows = []
        seen_codes = set()
        for item in items:
            code = item.get("SECURITY_CODE", "")
            if code in seen_codes:
                continue
            seen_codes.add(code)

            rows.append({
                "code": code,
                "name": item.get("SECURITY_NAME_ABBR", ""),
                "report_date": str(item.get("REPORTDATE", ""))[:10],
                "eps": item.get("BASIC_EPS"),
                "deduct_eps": item.get("DEDUCT_BASIC_EPS"),
                "revenue": item.get("TOTAL_OPERATE_INCOME"),
                "net_profit": item.get("PARENT_NETPROFIT"),
                "roe": item.get("WEIGHTAVG_ROE"),
                "revenue_yoy": item.get("YSTZ"),
                "profit_yoy": item.get("SJLTZ"),
                "bps": item.get("BPS"),
                "ocf_per_share": item.get("MGJYXJJE"),
                "gross_margin": item.get("XSMLL"),
                "revenue_qoq": item.get("YSHZ"),
                "profit_qoq": item.get("SJLHZ"),
            })

        df = pd.DataFrame(rows)
        for col in df.columns:
            if col not in ("code", "name", "report_date"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    except Exception:
        return pd.DataFrame()


def get_valuation_data() -> pd.DataFrame:
    """从实时行情中获取估值数据（PE/PB已在行情数据中）

    实时行情的 pe_ratio 和 pb_ratio 字段已可用，
    此函数提供额外的估值指标。
    """
    urls = [
        "http://push2.eastmoney.com/api/qt/clist/get",
        "http://82.push2.eastmoney.com/api/qt/clist/get",
    ]
    params = {
        "pn": "1",
        "pz": "5000",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f9,f12,f14,f23,f115,f20,f21",
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
                    "pe_ratio": item.get("f9"),
                    "pb_ratio": item.get("f23"),
                    "pe_ttm": item.get("f115"),
                    "total_market_cap": item.get("f20"),
                    "circulating_market_cap": item.get("f21"),
                })

            df = pd.DataFrame(rows)
            for col in df.columns:
                if col not in ("code", "name"):
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        except Exception:
            continue
    return pd.DataFrame()


def filter_by_fundamentals(
    candidates: list[str],
    fundamentals_df: pd.DataFrame,
    max_pe: float = 100,
    min_roe: float = 5,
    min_revenue_yoy: float = -20,
) -> tuple[list[str], dict[str, dict]]:
    """根据基本面过滤股票，返回通过的代码和基本面信息映射"""
    if fundamentals_df.empty:
        return candidates, {}

    fund_map = {}
    for _, row in fundamentals_df.iterrows():
        fund_map[row["code"]] = {
            "eps": row.get("eps"),
            "roe": row.get("roe"),
            "revenue_yoy": row.get("revenue_yoy"),
            "profit_yoy": row.get("profit_yoy"),
            "gross_margin": row.get("gross_margin"),
            "ocf_per_share": row.get("ocf_per_share"),
            "report_date": row.get("report_date"),
        }

    passed = []
    for code in candidates:
        info = fund_map.get(code)
        if not info:
            passed.append(code)
            continue

        pe = info.get("eps")
        roe = info.get("roe")
        rev_yoy = info.get("revenue_yoy")

        # 宽松过滤：只排除明显有问题的
        skip = False
        if roe is not None and pd.notna(roe) and roe < -10:
            skip = True
        if rev_yoy is not None and pd.notna(rev_yoy) and rev_yoy < -50:
            skip = True

        if not skip:
            passed.append(code)

    return passed, fund_map
