"""数据获取模块 - 多数据源获取A股行情数据（东方财富/腾讯/新浪）

支持HTTP/HTTPS自动切换，多CDN节点轮询，应对各种网络环境。
"""

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
        total=2,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
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


# ========== 东方财富数据源（多节点） ==========

_EASTMONEY_SPOT_URLS = [
    "http://push2.eastmoney.com/api/qt/clist/get",
    "http://82.push2.eastmoney.com/api/qt/clist/get",
    "http://18.push2.eastmoney.com/api/qt/clist/get",
    "http://32.push2.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
]

_EASTMONEY_HIST_URLS = [
    "http://push2his.eastmoney.com/api/qt/stock/kline/get",
    "https://push2his.eastmoney.com/api/qt/stock/kline/get",
]


def _fetch_eastmoney_spot() -> pd.DataFrame:
    """东方财富实时行情API（多节点轮询）"""
    params = {
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
        "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23",
        "_": str(int(time.time() * 1000)),
    }

    last_error = None
    for url in _EASTMONEY_SPOT_URLS:
        try:
            resp = _session.get(
                url, params=params, timeout=15,
                headers={"Referer": "https://quote.eastmoney.com/"},
            )
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
            for col in df.columns:
                if col not in ("code", "name"):
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(f"东方财富所有节点均失败: {last_error}")


def _fetch_eastmoney_history(code: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """东方财富历史行情API"""
    market = 1 if code.startswith(("6", "9")) else 0
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
    for url in _EASTMONEY_HIST_URLS:
        try:
            resp = _session.get(
                url, params=params, timeout=15,
                headers={"Referer": "https://quote.eastmoney.com/"},
            )
            resp.raise_for_status()
            klines = resp.json().get("data", {}).get("klines", [])
            if not klines:
                continue
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
            if rows:
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"])
                return df.sort_values("date").reset_index(drop=True)
        except Exception:
            continue
    return None


# ========== 腾讯数据源 ==========

def _tencent_code(code: str) -> str:
    """转换为腾讯格式代码"""
    if code.startswith(("6", "9")):
        return f"sh{code}"
    return f"sz{code}"


def _fetch_tencent_spot() -> pd.DataFrame:
    """腾讯实时行情API - 使用qt.gtimg.cn批量接口"""
    # 先获取沪深A股代码列表
    all_codes = _get_stock_code_list()
    if not all_codes:
        raise ValueError("无法获取股票代码列表")

    all_rows = []
    batch_size = 50
    for i in range(0, len(all_codes), batch_size):
        batch = all_codes[i:i + batch_size]
        tc_codes = [_tencent_code(c) for c in batch]
        url = f"http://qt.gtimg.cn/q={','.join(tc_codes)}"
        try:
            resp = _session.get(url, timeout=15)
            resp.encoding = "gbk"
            text = resp.text
            for line in text.strip().split("\n"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                match = re.search(r'v_s([hz]\d{6})="(.+)"', line)
                if not match:
                    continue
                raw_code = match.group(1)[1:]  # remove s/z prefix
                fields = match.group(2).split("~")
                if len(fields) < 46:
                    continue
                all_rows.append({
                    "code": raw_code,
                    "name": fields[1],
                    "close": fields[3],
                    "pre_close": fields[4],
                    "open": fields[5],
                    "volume": fields[6],
                    "amount": fields[37],
                    "high": fields[33] or fields[41],
                    "low": fields[34] or fields[42],
                    "pct_change": fields[32],
                    "change": fields[31],
                    "amplitude": fields[43],
                    "turnover_rate": fields[38],
                    "pe_ratio": fields[39],
                    "volume_ratio": fields[36],
                    "total_market_cap": fields[45] if len(fields) > 45 else None,
                    "circulating_market_cap": fields[44] if len(fields) > 44 else None,
                    "pb_ratio": fields[46] if len(fields) > 46 else None,
                })
        except Exception:
            continue
        if i % 500 == 0 and i > 0:
            time.sleep(0.2)

    if not all_rows:
        raise ValueError("腾讯API未返回数据")

    df = pd.DataFrame(all_rows)
    for col in df.columns:
        if col not in ("code", "name"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # 腾讯市值单位是亿元，转为元
    if "total_market_cap" in df.columns:
        df["total_market_cap"] = df["total_market_cap"] * 1e8
    if "circulating_market_cap" in df.columns:
        df["circulating_market_cap"] = df["circulating_market_cap"] * 1e8
    return df


def _get_stock_code_list() -> list[str]:
    """获取沪深A股代码列表（使用东方财富轻量接口或硬编码范围）"""
    codes = []
    # 沪市主板: 600xxx-605xxx
    for prefix in range(600, 606):
        for suffix in range(0, 1000):
            codes.append(f"{prefix}{suffix:03d}")
    # 沪市科创板: 688xxx
    for suffix in range(0, 1000):
        codes.append(f"688{suffix:03d}")
    # 深市主板: 000xxx-003xxx
    for prefix in range(0, 4):
        for suffix in range(0, 1000):
            codes.append(f"{prefix:03d}{suffix:03d}")
    # 深市中小板: 002xxx
    # (already included above)
    # 深市创业板: 300xxx-301xxx
    for prefix in range(300, 302):
        for suffix in range(0, 1000):
            codes.append(f"{prefix}{suffix:03d}")
    return codes


def _fetch_tencent_history(code: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """腾讯历史行情API"""
    tc_code = _tencent_code(code)
    url = (
        f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={tc_code},day,{start_date},{end_date},640,qfq"
    )
    try:
        resp = _session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        stock_data = data.get("data", {}).get(tc_code, {})
        klines = stock_data.get("qfqday", stock_data.get("day", []))
        if not klines:
            return None

        rows = []
        for k in klines:
            if len(k) >= 6:
                rows.append({
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

        if not rows:
            return None
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
        if len(df) > 1:
            df["pct_change"] = df["close"].pct_change() * 100
            df["change"] = df["close"].diff()
        return df
    except Exception:
        return None


# ========== 新浪数据源 ==========

def _sina_code(code: str) -> str:
    if code.startswith(("6", "9")):
        return f"sh{code}"
    return f"sz{code}"


def _fetch_sina_spot() -> pd.DataFrame:
    """新浪实时行情API"""
    all_codes = _get_stock_code_list()
    all_rows = []
    batch_size = 800

    for i in range(0, len(all_codes), batch_size):
        batch = all_codes[i:i + batch_size]
        sina_codes = [_sina_code(c) for c in batch]
        url = f"http://hq.sinajs.cn/list={','.join(sina_codes)}"
        try:
            resp = _session.get(
                url, timeout=15,
                headers={"Referer": "https://finance.sina.com.cn"},
            )
            resp.encoding = "gbk"
            text = resp.text
            for line in text.strip().split("\n"):
                match = re.search(r'hq_str_(s[hz]\d{6})="(.+)"', line)
                if not match:
                    continue
                raw_code = match.group(1)[2:]
                fields = match.group(2).split(",")
                if len(fields) < 32 or not fields[0]:
                    continue
                all_rows.append({
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
        time.sleep(0.1)

    if not all_rows:
        raise ValueError("新浪API未返回数据")

    df = pd.DataFrame(all_rows)
    for col in df.columns:
        if col not in ("code", "name"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 过滤无效代码（收盘价为0的）
    df = df[df["close"] > 0].reset_index(drop=True)

    # 计算涨跌幅
    pre = df["pre_close"]
    close = df["close"]
    df["pct_change"] = ((close - pre) / pre * 100).round(2)
    df["change"] = (close - pre).round(2)

    return df


# ========== 统一入口 ==========

def get_all_a_stocks() -> pd.DataFrame:
    """获取所有A股股票实时行情（自动切换数据源）"""
    sources = [
        ("东方财富", _fetch_eastmoney_spot),
        ("腾讯财经", _fetch_tencent_spot),
        ("新浪财经", _fetch_sina_spot),
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
            err_msg = str(e)
            if len(err_msg) > 80:
                err_msg = err_msg[:80] + "..."
            print(f" 失败（{err_msg}）")
            continue

    raise RuntimeError(
        "所有数据源均不可用，请检查网络连接。\n"
        "提示：\n"
        "  1. 请确保能正常访问 quote.eastmoney.com 或 finance.sina.com.cn\n"
        "  2. 如在公司网络，请尝试使用手机热点\n"
        "  3. 如使用VPN，请尝试关闭后重试\n"
        "  4. 请在交易日运行（周一至周五）"
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
        valid_caps = cap_col.dropna()
        if len(valid_caps) > 0 and (valid_caps > 0).any():
            threshold = min_cap * 1e8  # 转为元
            # 自动检测单位：如果中位数远小于阈值，可能单位不是元
            median_cap = valid_caps[valid_caps > 0].median()
            if median_cap < 1e6:  # 中位数小于100万，可能是亿元单位
                threshold = min_cap  # 直接用亿元比较
            elif median_cap < 1e9:  # 中位数小于10亿，可能是万元单位
                threshold = min_cap * 1e4  # 转为万元比较
            filtered = df[df["circulating_market_cap"] >= threshold]
            if len(filtered) > 50:  # 确保筛选后还有足够股票
                df = filtered
            else:
                print(f"  ℹ 市值筛选后仅剩{len(filtered)}只，跳过市值筛选")

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
