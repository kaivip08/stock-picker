"""事件驱动数据模块

业绩预告、解禁、龙虎榜等事件数据。
"""

import time
from datetime import datetime, timedelta

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


def get_performance_forecast() -> pd.DataFrame:
    """获取业绩预告数据"""
    params = {
        "reportName": "RPT_PUBLIC_OP_NEWPREDICT",
        "columns": "ALL",
        "pageSize": "200",
        "pageNumber": "1",
        "sortColumns": "NOTICE_DATE",
        "sortTypes": "-1",
        "source": "WEB",
        "_": str(int(time.time() * 1000)),
    }

    try:
        resp = _session.get(_DATACENTER_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        items = result.get("data", [])

        if not items:
            return pd.DataFrame()

        rows = []
        for item in items:
            predict_type = item.get("PREDICT_FINANCE", "")
            rows.append({
                "code": item.get("SECURITY_CODE", ""),
                "name": item.get("SECURITY_NAME_ABBR", ""),
                "notice_date": str(item.get("NOTICE_DATE", ""))[:10],
                "report_date": str(item.get("REPORT_DATE", ""))[:10],
                "predict_type": predict_type,
                "predict_content": item.get("PREDICT_CONTENT", ""),
                "change_lower": item.get("ADD_AMP_LOWER"),
                "change_upper": item.get("ADD_AMP_UPPER"),
                "amount_lower": item.get("PREDICT_AMT_LOWER"),
                "amount_upper": item.get("PREDICT_AMT_UPPER"),
                "change_reason": item.get("CHANGE_REASON_EXPLAIN", ""),
            })

        df = pd.DataFrame(rows)
        for col in ["change_lower", "change_upper", "amount_lower", "amount_upper"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception:
        return pd.DataFrame()


def get_lock_up_expiry(days_ahead: int = 30) -> pd.DataFrame:
    """获取近期解禁数据"""
    params = {
        "reportName": "RPT_LIFT_STAGE",
        "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,FREE_DATE,CURRENT_FREE_SHARES,LIFT_MARKET_CAP,FREE_RATIO",
        "pageSize": "100",
        "pageNumber": "1",
        "sortColumns": "FREE_DATE",
        "sortTypes": "-1",
        "source": "WEB",
        "_": str(int(time.time() * 1000)),
    }

    try:
        resp = _session.get(_DATACENTER_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        items = result.get("data", [])

        if not items:
            return pd.DataFrame()

        today = datetime.now()
        cutoff = today + timedelta(days=days_ahead)

        rows = []
        for item in items:
            free_date_str = str(item.get("FREE_DATE", ""))[:10]
            try:
                free_date = datetime.strptime(free_date_str, "%Y-%m-%d")
            except ValueError:
                continue

            if today - timedelta(days=7) <= free_date <= cutoff:
                rows.append({
                    "code": item.get("SECURITY_CODE", ""),
                    "name": item.get("SECURITY_NAME_ABBR", ""),
                    "free_date": free_date_str,
                    "free_shares": item.get("CURRENT_FREE_SHARES"),
                    "lift_market_cap": item.get("LIFT_MARKET_CAP"),
                    "free_ratio": item.get("FREE_RATIO"),
                })

        df = pd.DataFrame(rows) if rows else pd.DataFrame()
        if not df.empty:
            for col in ["free_shares", "lift_market_cap", "free_ratio"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception:
        return pd.DataFrame()


def get_dragon_tiger_list() -> pd.DataFrame:
    """获取龙虎榜数据"""
    params = {
        "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
        "columns": "ALL",
        "pageSize": "50",
        "pageNumber": "1",
        "sortColumns": "TRADE_DATE",
        "sortTypes": "-1",
        "source": "WEB",
        "_": str(int(time.time() * 1000)),
    }

    try:
        resp = _session.get(_DATACENTER_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        items = result.get("data", [])

        if not items:
            return pd.DataFrame()

        rows = []
        seen = set()
        for item in items:
            code = item.get("SECURITY_CODE", "")
            if code in seen:
                continue
            seen.add(code)
            rows.append({
                "code": code,
                "name": item.get("SECURITY_NAME_ABBR", ""),
                "trade_date": str(item.get("TRADE_DATE", ""))[:10],
                "close_price": item.get("CLOSE_PRICE"),
                "change_rate": item.get("CHANGE_RATE"),
                "billboard_amount": item.get("BILLBOARD_DEAL_AMT"),
                "turnover_rate": item.get("TURNOVERRATE"),
                "explain": item.get("EXPLAIN", ""),
                "d1_pct": item.get("D1_CLOSE_ADJCHRATE"),
                "d2_pct": item.get("D2_CLOSE_ADJCHRATE"),
                "d5_pct": item.get("D5_CLOSE_ADJCHRATE"),
            })

        df = pd.DataFrame(rows)
        for col in ["close_price", "change_rate", "billboard_amount", "turnover_rate",
                     "d1_pct", "d2_pct", "d5_pct"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception:
        return pd.DataFrame()


def get_event_flags(codes: list[str]) -> dict[str, list[str]]:
    """获取指定股票的事件标记

    返回: {code: [event_type, ...]}
    事件类型: 业绩预增, 业绩预减, 近期解禁, 龙虎榜
    """
    code_set = set(codes)
    flags: dict[str, list[str]] = {}

    # 业绩预告
    try:
        forecast_df = get_performance_forecast()
        if not forecast_df.empty:
            for _, row in forecast_df.iterrows():
                code = row["code"]
                if code in code_set:
                    ptype = row.get("predict_type", "")
                    if "预增" in ptype or "扭亏" in ptype or "略增" in ptype or "续盈" in ptype:
                        flags.setdefault(code, []).append(f"业绩预增({ptype})")
                    elif "预减" in ptype or "首亏" in ptype or "略减" in ptype or "续亏" in ptype:
                        flags.setdefault(code, []).append(f"业绩预减({ptype})")
                    else:
                        flags.setdefault(code, []).append(f"业绩预告({ptype})")
    except Exception:
        pass

    # 解禁
    try:
        lockup_df = get_lock_up_expiry(days_ahead=15)
        if not lockup_df.empty:
            for _, row in lockup_df.iterrows():
                code = row["code"]
                if code in code_set:
                    ratio = row.get("free_ratio", 0)
                    if pd.notna(ratio) and ratio > 1:
                        flags.setdefault(code, []).append(f"近期解禁(占比{ratio:.1f}%)")
    except Exception:
        pass

    # 龙虎榜
    try:
        dragon_df = get_dragon_tiger_list()
        if not dragon_df.empty:
            for _, row in dragon_df.iterrows():
                code = row["code"]
                if code in code_set:
                    explain = row.get("explain", "")
                    flags.setdefault(code, []).append(f"龙虎榜({explain[:20]})")
    except Exception:
        pass

    return flags
