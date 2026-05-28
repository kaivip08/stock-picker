"""Pro Scanner 数据层：主板实时行情、资金流、板块强度。

复用项目根部的 `data_fetcher` 会话/重试机制，并补充：
- 多页拉取主板（沪深主板）股票实时行情
- 主力资金流排行（个股 / 板块）
- 行业板块涨跌幅与资金流
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from stock_picker.data_fetcher import _session


EASTMONEY_CLIST_NODES = [
    "http://push2.eastmoney.com/api/qt/clist/get",
    "http://82.push2.eastmoney.com/api/qt/clist/get",
    "http://18.push2.eastmoney.com/api/qt/clist/get",
    "http://32.push2.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
]


# 主板筛选 fs（沪深主板，不含创业板/科创板/北交所）
# 注意：东财 fs 段同时包含科创板/创业板，我们在 Python 层再用代码前缀过滤
_MAIN_BOARD_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"

# 主板个股 spot 字段（按代码取，避免按涨跌幅排序后只返回 100）
_SPOT_FIELDS = (
    "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23"
)
_SPOT_FIELD_MAP = {
    "f2": "close",
    "f3": "pct_change",
    "f4": "change",
    "f5": "volume",
    "f6": "amount",
    "f7": "amplitude",
    "f8": "turnover_rate",
    "f9": "pe_ratio",
    "f10": "volume_ratio",
    "f12": "code",
    "f14": "name",
    "f15": "high",
    "f16": "low",
    "f17": "open",
    "f18": "pre_close",
    "f20": "total_market_cap",
    "f21": "circulating_market_cap",
    "f23": "pb_ratio",
}

# 资金流字段（个股）
# f62=今日主力净流入额, f184=主力净流入占比, f66/f72/f78/f84=超大单/大单/中单/小单 净流入额
_FUND_FLOW_FIELDS = "f12,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f124"
_FUND_FLOW_FIELD_MAP = {
    "f12": "code",
    "f14": "name",
    "f62": "main_net_inflow",
    "f184": "main_net_inflow_pct",
    "f66": "super_large_net_inflow",
    "f72": "large_net_inflow",
    "f78": "medium_net_inflow",
    "f84": "small_net_inflow",
}

# 行业板块字段
_SECTOR_FIELDS = "f2,f3,f12,f14,f62,f124,f128,f136"
_SECTOR_FIELD_MAP = {
    "f2": "close",
    "f3": "pct_change",
    "f12": "code",
    "f14": "name",
    "f62": "main_net_inflow",
    "f128": "leader_name",
    "f136": "leader_pct_change",
}


def _get_paginated(
    fs: str,
    fields: str,
    fid: str = "f12",
    pz: int = 100,
    max_pages: int = 80,
    sleep: float = 0.25,
) -> list[dict[str, Any]]:
    """通用分页拉取（多节点轮询、502 自动切换）。"""
    base_params = {
        "pz": str(pz),
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "wbp2u": "|0|0|0|web",
        "fid": fid,
        "fs": fs,
        "fields": fields,
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}

    items: list[dict[str, Any]] = []
    server_total: int | None = None
    consecutive_failures = 0
    for pn in range(1, max_pages + 1):
        params = dict(base_params)
        params["pn"] = str(pn)
        params["_"] = str(int(time.time() * 1000))

        page_items: list[dict[str, Any]] | None = None
        for url in EASTMONEY_CLIST_NODES:
            try:
                resp = _session.get(url, params=params, headers=headers, timeout=8)
                if resp.status_code != 200 or not resp.text.startswith("{"):
                    continue
                data = resp.json().get("data") or {}
                page_items = data.get("diff") or []
                if server_total is None:
                    server_total = int(data.get("total") or 0)
                break
            except Exception:
                continue

        if not page_items:
            consecutive_failures += 1
            # 第一页就失败 → 直接放弃（节点不可用）
            if pn == 1 and consecutive_failures >= 1:
                break
            # 节点暂时不可用 / 已超过总页数
            if server_total is not None and pn * pz >= server_total:
                break
            if consecutive_failures >= 5:
                break
            time.sleep(0.6)
            continue
        consecutive_failures = 0

        items.extend(page_items)
        if server_total and len(items) >= server_total:
            break
        if len(page_items) < pz:
            break
        time.sleep(sleep)

    return items


def _items_to_df(items: list[dict[str, Any]], field_map: dict[str, str]) -> pd.DataFrame:
    """把东财 raw items 转成有列名的 DataFrame。"""
    if not items:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for it in items:
        row: dict[str, Any] = {}
        for raw_key, col in field_map.items():
            row[col] = it.get(raw_key)
        rows.append(row)
    df = pd.DataFrame(rows)
    for col in df.columns:
        if col not in ("code", "name", "leader_name"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "code" in df.columns:
        df["code"] = df["code"].astype(str)
    return df


def _fetch_main_board_spot_tencent_fallback() -> pd.DataFrame:
    """东财不可用时的降级方案：从腾讯拉全 A 股 spot，再过滤主板。

    注意：
    - 腾讯 amount 字段单位是万元，需要 × 1e4 转为元
    - 腾讯返回中 volume_ratio 字段在原 data_fetcher 中没有正确解析，置为 NaN
    """
    from stock_picker.data_fetcher import _fetch_tencent_spot
    df = _fetch_tencent_spot()
    if df.empty:
        return df
    df["code"] = df["code"].astype(str)
    mask = df["code"].apply(is_main_board_code)
    df = df[mask].copy().reset_index(drop=True)
    # 单位统一：amount 万元 → 元
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce") * 1e4
    # volume_ratio 在 data_fetcher 里未正确解析（实际是 volume），重置为缺失
    if "volume_ratio" in df.columns:
        df["volume_ratio"] = pd.NA
    return df


def fetch_main_board_spot() -> pd.DataFrame:
    """拉取沪深主板（含科创/创业）实时行情，全部分页。

    注意：fs 段实际包含科创/创业板，调用方需用 `is_main_board` 过滤纯主板。
    若东财全部节点不可用，自动降级到腾讯 spot。
    """
    try:
        items = _get_paginated(
            fs=_MAIN_BOARD_FS,
            fields=_SPOT_FIELDS,
            fid="f12",
            pz=100,
        )
    except Exception:
        items = []
    df = _items_to_df(items, _SPOT_FIELD_MAP)
    if df.empty or len(df) < 100:
        # 东财空 / 极度残缺 → 用腾讯降级
        try:
            df = _fetch_main_board_spot_tencent_fallback()
        except Exception:
            pass
    return df


def fetch_fund_flow_rank() -> pd.DataFrame:
    """拉取个股主力资金流排行（全市场）。"""
    items = _get_paginated(
        fs=_MAIN_BOARD_FS,
        fields=_FUND_FLOW_FIELDS,
        fid="f62",  # 按主力净流入排序
        pz=100,
        max_pages=60,
    )
    return _items_to_df(items, _FUND_FLOW_FIELD_MAP)


def fetch_industry_sectors() -> pd.DataFrame:
    """拉取行业板块行情（按涨跌幅排序，含主力资金流）。"""
    items = _get_paginated(
        fs="m:90+t:2",  # 行业板块
        fields=_SECTOR_FIELDS,
        fid="f3",
        pz=100,
        max_pages=5,
    )
    return _items_to_df(items, _SECTOR_FIELD_MAP)


def fetch_concept_sectors() -> pd.DataFrame:
    """拉取概念板块行情（按涨跌幅排序）。"""
    items = _get_paginated(
        fs="m:90+t:3",  # 概念板块
        fields=_SECTOR_FIELDS,
        fid="f3",
        pz=100,
        max_pages=10,
    )
    return _items_to_df(items, _SECTOR_FIELD_MAP)


_EASTMONEY_STOCK_GET_NODES = [
    "http://18.push2.eastmoney.com/api/qt/stock/get",
    "http://82.push2.eastmoney.com/api/qt/stock/get",
    "http://32.push2.eastmoney.com/api/qt/stock/get",
    "http://push2.eastmoney.com/api/qt/stock/get",
    "https://push2.eastmoney.com/api/qt/stock/get",
]


def fetch_stock_sectors(code: str, max_retries: int = 2) -> dict[str, Any] | None:
    """获取单只股票的行业 / 概念 / 地域标签（带重试与节点轮询）。

    返回 {'industry': str, 'region': str, 'concepts': list[str]} 或 None。
    """
    market = "1" if code.startswith(("6", "9")) else "0"
    params_base = {
        "secid": f"{market}.{code}",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "fields": "f57,f58,f127,f128,f129",
    }
    for attempt in range(max_retries):
        for url in _EASTMONEY_STOCK_GET_NODES:
            try:
                params = dict(params_base)
                params["_"] = str(int(time.time() * 1000))
                resp = _session.get(
                    url, params=params,
                    headers={"Referer": "https://quote.eastmoney.com/"},
                    timeout=8,
                )
                if resp.status_code != 200:
                    continue
                if not resp.text.startswith("{"):
                    continue
                data = resp.json().get("data") or {}
                if not data:
                    continue
                concepts_raw = data.get("f129") or ""
                concepts = [c.strip() for c in concepts_raw.split(",") if c.strip()]
                return {
                    "industry": (data.get("f127") or "").strip() or None,
                    "region": (data.get("f128") or "").strip() or None,
                    "concepts": concepts,
                }
            except Exception:
                continue
        if attempt < max_retries - 1:
            time.sleep(0.8 + attempt * 0.5)
    return None


def is_main_board_code(code: str) -> bool:
    """判断是否为严格主板（沪 60xxxx + 深 000xxx/001xxx/002xxx/003xxx）。

    排除：
    - 30xxxx 创业板
    - 688xxx/689xxx 科创板
    - 8xxxxx/4xxxxx 北交所
    """
    if not code or len(code) < 6:
        return False
    head = code[:3]
    if head.startswith("60"):
        return True
    if head in ("000", "001", "002", "003"):
        return True
    return False
