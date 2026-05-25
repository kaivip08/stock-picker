"""数据获取模块 - 多数据源获取A股行情数据（东方财富/新浪/腾讯）"""

import random
import re
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _create_session() -> requests.Session:
    """创建带重试机制的HTTP会话"""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    return session


_session = _create_session()


# ========== 东方财富数据源 ==========

def _fetch_eastmoney_spot() -> pd.DataFrame:
    """东方财富实时行情API"""
    url = "https://82.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "cb": "",
        "pn": "1",
        "pz": "5000",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "wbp2u": "|0|0|0|web",
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23",
        "_": str(int(time.time() * 1000)),
    }
    _session.headers["Referer"] = "https://quote.eastmoney.com/center/gridlist.html"
    resp = _session.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("data", {}).get("diff", [])
    if not items:
        raise ValueError("东方财富未返回数据")

    rows = []
    for item in items:
        rows.append({
            "code": item.get("f12", ""),
            "name": item.get("f14", ""),
            "close": item.get("f2"),
            "pct_change": item.get("f3"),
            "change": item.get("f4"),
            "volume": item.get("f5"),
            "amount": item.get("f6"),
            "amplitude": item.get("f7"),
            "turnover_rate": item.get("f8"),
            "pe_ratio": item.get("f9"),
            "volume_ratio": item.get("f10"),
            "high": item.get("f15"),
            "low": item.get("f16"),
            "open": item.get("f17"),
            "pre_close": item.get("f18"),
            "total_market_cap": item.get("f20"),
            "circulating_market_cap": item.get("f21"),
            "pb_ratio": item.get("f23"),
        })

    df = pd.DataFrame(rows)
    numeric_cols = [
        "close", "pct_change", "change", "volume", "amount",
        "amplitude", "turnover_rate", "pe_ratio", "volume_ratio",
        "high", "low", "open", "pre_close",
        "total_market_cap", "circulating_market_cap", "pb_ratio",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _fetch_eastmoney_history(code: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """东方财富历史行情API"""
    market = 1 if code.startswith(("6", "9")) else 0
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": f"{market}.{code}",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "beg": start_date,
        "end": end_date,
        "_": str(int(time.time() * 1000)),
    }
    _session.headers["Referer"] = "https://quote.eastmoney.com/"
    resp = _session.get(url, params=params, timeout=30)
    resp.raise_for_status()
    klines = resp.json().get("data", {}).get("klines", [])
    if not klines:
        return None

    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 11:
            rows.append({
                "date": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]),
                "amplitude": float(parts[7]),
                "pct_change": float(parts[8]),
                "change": float(parts[9]),
                "turnover_rate": float(parts[10]),
            })
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


# ========== 腾讯数据源（备用） ==========

def _tencent_code(code: str) -> str:
    """转换为腾讯格式代码"""
    if code.startswith(("6", "9")):
        return f"sh{code}"
    return f"sz{code}"


def _fetch_tencent_spot() -> pd.DataFrame:
    """腾讯实时行情API（备用数据源）"""
    # 分批获取沪深A股
    all_rows = []
    for market_prefix, market_code in [("sh", "1"), ("sz", "0")]:
        url = f"https://proxy.finance.qq.com/ifzqgtimg/appstock/app/rankListByMarketValue/index?asc=0&page=0&num=5000&market={market_prefix}"
        try:
            resp = _session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            stock_list = data.get("data", {}).get("result", [])
            for item in stock_list:
                code = item.get("code", "")
                if not code:
                    continue
                all_rows.append({
                    "code": code,
                    "name": item.get("name", ""),
                    "close": item.get("price"),
                    "pct_change": item.get("percent"),
                    "change": item.get("change"),
                    "volume": item.get("volume"),
                    "amount": item.get("amount"),
                    "amplitude": None,
                    "turnover_rate": item.get("turnoverRate"),
                    "pe_ratio": item.get("pe"),
                    "volume_ratio": None,
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "open": item.get("open"),
                    "pre_close": item.get("lastClose"),
                    "total_market_cap": item.get("totalValue"),
                    "circulating_market_cap": item.get("flowValue"),
                    "pb_ratio": item.get("pb"),
                })
        except Exception:
            continue

    if not all_rows:
        raise ValueError("腾讯API未返回数据")

    df = pd.DataFrame(all_rows)
    numeric_cols = [
        "close", "pct_change", "change", "volume", "amount",
        "amplitude", "turnover_rate", "pe_ratio", "volume_ratio",
        "high", "low", "open", "pre_close",
        "total_market_cap", "circulating_market_cap", "pb_ratio",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _fetch_tencent_history(code: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """腾讯历史行情API"""
    tc_code = _tencent_code(code)
    start_y = start_date[:4]
    end_y = end_date[:4]
    years = list(range(int(start_y), int(end_y) + 1))

    all_rows = []
    for year in years:
        url = (
            f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?param={tc_code},day,{start_date},{end_date},640,qfq"
        )
        try:
            resp = _session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            stock_data = data.get("data", {}).get(tc_code, {})
            klines = stock_data.get("qfqday", stock_data.get("day", []))
            for k in klines:
                if len(k) >= 6:
                    all_rows.append({
                        "date": k[0],
                        "open": float(k[1]),
                        "close": float(k[2]),
                        "high": float(k[3]),
                        "low": float(k[4]),
                        "volume": float(k[5]) if len(k) > 5 else 0,
                        "amount": 0,
                        "amplitude": 0,
                        "pct_change": 0,
                        "change": 0,
                        "turnover_rate": 0,
                    })
        except Exception:
            continue

    if not all_rows:
        return None
    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    # 计算涨跌幅
    if len(df) > 1:
        df["pct_change"] = df["close"].pct_change() * 100
        df["change"] = df["close"].diff()
    return df


# ========== 新浪数据源（备用） ==========

def _sina_code(code: str) -> str:
    """转换为新浪格式代码"""
    if code.startswith(("6", "9")):
        return f"sh{code}"
    return f"sz{code}"


def _fetch_sina_spot_batch(codes: list[str]) -> list[dict]:
    """新浪批量实时行情"""
    sina_codes = [_sina_code(c) for c in codes]
    rows = []
    batch_size = 800
    for i in range(0, len(sina_codes), batch_size):
        batch = sina_codes[i:i + batch_size]
        url = f"https://hq.sinajs.cn/list={','.join(batch)}"
        _session.headers["Referer"] = "https://finance.sina.com.cn"
        try:
            resp = _session.get(url, timeout=30)
            resp.raise_for_status()
            text = resp.text
            for line in text.strip().split("\n"):
                match = re.search(r'hq_str_(s[hz]\d{6})="(.+)"', line)
                if not match:
                    continue
                full_code = match.group(1)
                raw_code = full_code[2:]
                fields = match.group(2).split(",")
                if len(fields) < 32:
                    continue
                rows.append({
                    "code": raw_code,
                    "name": fields[0],
                    "open": fields[1],
                    "pre_close": fields[2],
                    "close": fields[3],
                    "high": fields[4],
                    "low": fields[5],
                    "volume": fields[8],
                    "amount": fields[9],
                    "pct_change": None,
                    "change": None,
                    "amplitude": None,
                    "turnover_rate": None,
                    "pe_ratio": None,
                    "volume_ratio": None,
                    "total_market_cap": None,
                    "circulating_market_cap": None,
                    "pb_ratio": None,
                })
        except Exception:
            continue
        time.sleep(0.3)

    return rows


# ========== 统一入口（自动选择数据源） ==========

def get_all_a_stocks() -> pd.DataFrame:
    """获取所有A股股票实时行情（自动切换数据源）"""
    sources = [
        ("东方财富", _fetch_eastmoney_spot),
        ("腾讯财经", _fetch_tencent_spot),
    ]

    for source_name, fetch_func in sources:
        try:
            print(f"  尝试数据源: {source_name}...", end="", flush=True)
            df = fetch_func()
            if df is not None and len(df) > 100:
                print(f" 成功！获取到 {len(df)} 只股票")
                return df
            print(" 数据量不足，切换下一个数据源")
        except Exception as e:
            print(f" 失败（{type(e).__name__}: {e}）")
            continue

    raise RuntimeError(
        "所有数据源均不可用，请检查网络连接。\n"
        "提示：\n"
        "  1. 请确保能正常访问 quote.eastmoney.com\n"
        "  2. 如在公司网络，请尝试使用手机热点\n"
        "  3. 请在交易日运行（周一至周五）"
    )


def filter_stocks(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    """根据配置过滤股票"""
    selection = config.get("selection", {})

    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0].copy()

    if selection.get("exclude_st", True):
        df = df[~df["name"].str.contains("ST", case=False, na=False)]

    if selection.get("exclude_kcb", False):
        df = df[~df["code"].str.startswith("688")]

    if selection.get("exclude_bse", True):
        df = df[~df["code"].str.startswith("8")]

    min_cap = selection.get("min_market_cap", 30)
    if "circulating_market_cap" in df.columns:
        cap_col = df["circulating_market_cap"]
        if cap_col.notna().any() and (cap_col > 0).any():
            df = df[df["circulating_market_cap"] >= min_cap * 1e8]

    if "pct_change" in df.columns:
        pct = df["pct_change"]
        if pct.notna().any():
            df = df[pct.abs() < 9.9]

    # 计算涨跌幅（如果数据源没有提供）
    if df["pct_change"].isna().all() and "pre_close" in df.columns:
        pre = pd.to_numeric(df["pre_close"], errors="coerce")
        close = pd.to_numeric(df["close"], errors="coerce")
        df["pct_change"] = ((close - pre) / pre * 100).round(2)
        df = df[df["pct_change"].abs() < 9.9]

    return df.reset_index(drop=True)


def get_stock_history(
    code: str,
    days: int = 120,
    retry_times: int = 3,
    interval: float = 1.0,
) -> pd.DataFrame | None:
    """获取单只股票的历史行情数据（自动切换数据源）"""
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    fetchers = [
        _fetch_eastmoney_history,
        _fetch_tencent_history,
    ]

    for fetch_func in fetchers:
        for attempt in range(retry_times):
            try:
                df = fetch_func(code, start_date, end_date)
                if df is not None and len(df) >= 20:
                    return df
                break
            except Exception:
                if attempt < retry_times - 1:
                    time.sleep(interval * (attempt + 1) + random.uniform(0, 0.5))
                continue
    return None


def batch_get_history(
    codes: list[str],
    days: int = 120,
    retry_times: int = 3,
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
        time.sleep(interval + random.uniform(0, 0.3))
    return result
