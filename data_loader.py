"""
data_loader.py — 資料載入層
台股量化交易策略儀表板

負責所有 API 調用、網頁爬蟲、資料清洗及快取機制。
資料來源：
  - FinMind API (個股查詢，需帶 data_id)
  - TWSE 證交所公開端點 (全市場批次查詢)
  - TPEx 櫃買中心公開端點 (上櫃股批次查詢)
  - PTT Stock / 鉅亨網 (新聞爬蟲)
"""
import time
import datetime
import logging
import random
import warnings

import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
import streamlit as st
import yfinance as yf

import config
import utils

warnings.filterwarnings("ignore")


class _BareStreamlit:
    """Minimal Streamlit adapter for scheduled and command-line jobs."""

    @staticmethod
    def cache_data(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    @staticmethod
    def warning(message):
        logging.getLogger(__name__).warning(message)


try:
    from streamlit.runtime.scriptrunner import get_script_run_ctx

    if get_script_run_ctx(suppress_warning=True) is None:
        st = _BareStreamlit()
except (ImportError, RuntimeError):
    st = _BareStreamlit()

# ============================================================
# 共用 HTTP 工具
# ============================================================

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]


def _random_ua() -> dict:
    """產生隨機 User-Agent 標頭。"""
    return {"User-Agent": random.choice(_USER_AGENTS)}


def _http_session() -> requests.Session:
    """
    Build a session that ignores environment proxy settings.
    The workspace injects a dead local proxy, which breaks outbound API calls.
    """
    session = requests.Session()
    session.trust_env = False
    return session


_THEME_RULES = [
    (
        "SaaS/雲端軟體",
        [
            "saas",
            "雲端軟體",
            "軟體",
            "erp",
            "crm",
            "數位轉型",
            "訂閱制",
            "資訊服務",
        ],
        [
            "91app",
            "普萊德",
            "偉康科技",
            "叡揚",
            "邁達特",
            "伊雲谷",
            "訊連",
            "宏碁資訊",
        ],
    ),
    (
        "工業自動化/機器人",
        [
            "自動化",
            "工業電腦",
            "工控",
            "機器人",
            "伺服馬達",
            "plc",
            "人機介面",
            "智慧工廠",
        ],
        [
            "研華",
            "樺漢",
            "新漢",
            "所羅門",
            "羅昇",
            "和椿",
            "東台",
            "上銀",
        ],
    ),
    (
        "汽車/電動車",
        [
            "電動車",
            "汽車",
            "車用",
            "充電樁",
            "充電站",
            "馬達",
            "逆變器",
            "車聯網",
        ],
        [
            "裕隆",
            "鴻華",
            "和大",
            "東陽",
            "貿聯",
            "胡連",
            "和勤",
            "車王電",
        ],
    ),
    (
        "電源管理/電力電子",
        [
            "電源管理",
            "電源供應",
            "電源模組",
            "power management",
            "pmic",
            "bms",
            "dc-dc",
            "dcdc",
            "ups",
            "逆變器",
        ],
        [
            "台達電",
            "光寶科",
            "群電",
            "康舒",
            "致新",
            "茂達",
            "立錡",
            "力智",
            "飛宏",
            "全漢",
        ],
    ),
    (
        "車用半導體",
        [
            "車用半導體",
            "車載半導體",
            "汽車電子",
            "車載",
            "車規",
            "adas",
            "自駕",
        ],
        [
            "強茂",
            "新唐",
            "盛群",
            "瑞昱",
            "義隆",
            "原相",
            "凌陽",
            "偉詮電",
        ],
    ),
    (
        "電源管理IC",
        [
            "電源管理",
            "電源供應",
            "電源模組",
            "power management",
            "pmic",
            "bms",
            "充電樁",
            "充電",
            "逆變器",
            "變流器",
            "ups",
            "儲能",
            "節能",
        ],
        [
            "台達電",
            "光寶科",
            "群電",
            "康舒",
            "致新",
            "茂達",
            "立錡",
            "矽力*-ky",
            "力智",
            "飛宏",
            "全漢",
        ],
    ),
    (
        "重電/電力設備",
        [
            "重電",
            "變壓器",
            "配電盤",
            "配電",
            "斷路器",
            "開關設備",
            "電力設備",
            "輸配電",
            "變頻器",
            "高壓",
            "低壓",
            "馬達",
            "電機",
        ],
        [
            "士電",
            "中興電",
            "華城",
            "亞力",
            "東元",
            "大同",
        ],
    ),
    (
        "AI伺服器與散熱模組",
        [
            "ai伺服器",
            "伺服器",
            "散熱",
            "水冷",
            "風扇",
            "機殼",
            "機櫃",
            "導熱",
            "資料中心",
        ],
        [
            "奇鋐",
            "雙鴻",
            "建準",
            "健策",
            "緯穎",
            "廣達",
            "技嘉",
            "華碩",
        ],
    ),
    (
        "網通與光通訊",
        [
            "網通",
            "交換器",
            "路由器",
            "光通訊",
            "光纖",
            "網路設備",
            "收發器",
            "switch",
        ],
        [
            "智邦",
            "啟碁",
            "中磊",
            "瑞祺電通",
            "神準",
            "正文",
            "明泰",
        ],
    ),
    (
        "儲能與電池",
        [
            "儲能",
            "電池",
            "鋰電",
            "電芯",
            "電池模組",
            "不斷電",
            "能源儲存",
        ],
        [
            "新普",
            "順達",
            "錸寶",
            "康普",
            "美琪瑪",
            "台泥",
        ],
    ),
    (
        "半導體製造與IC設計",
        [
            "半導體",
            "晶圓",
            "封測",
            "ic設計",
            "ic製造",
            "晶片",
            "矽晶圓",
            "記憶體",
        ],
        [
            "台積電",
            "聯發科",
            "聯詠",
            "創意",
            "世芯",
            "力積電",
            "日月光",
            "京元電",
            "南亞科",
            "旺宏",
            "華邦電",
        ],
    ),
    (
        "車用零組件",
        [
            "汽車零組件",
            "車用零組件",
            "汽車電子",
            "車載",
            "電動車",
            "ev",
        ],
        [
            "和大",
            "東陽",
            "耿鼎",
            "堤維西",
            "宇隆",
            "劍麟",
        ],
    ),
    (
        "被動元件",
        [
            "被動元件",
            "電阻",
            "電容",
            "電感",
            "磁性元件",
            "晶片電阻",
        ],
        [
            "國巨",
            "華新科",
            "奇力新",
            "信昌電",
            "凱美",
            "鈺邦",
        ],
    ),
    (
        "PCB/CCL",
        [
            "pcb",
            "ccl",
            "印刷電路板",
            "載板",
            "軟板",
            "硬板",
        ],
        [
            "欣興",
            "南電",
            "景碩",
            "臻鼎",
            "高技",
            "台郡",
        ],
    ),
    (
        "面板與顯示",
        [
            "面板",
            "顯示器",
            "lcd",
            "oled",
            "背光",
            "顯示模組",
        ],
        [
            "友達",
            "群創",
            "彩晶",
            "元太",
        ],
    ),
    (
        "航運物流",
        [
            "航運",
            "海運",
            "貨櫃",
            "散裝",
            "物流",
            "運輸",
        ],
        [
            "長榮",
            "陽明",
            "萬海",
            "慧洋",
            "裕民",
        ],
    ),
    (
        "金融保險",
        [
            "金融",
            "金控",
            "銀行",
            "證券",
            "保險",
        ],
        [
            "富邦金",
            "國泰金",
            "中信金",
            "元大金",
            "玉山金",
            "凱基金",
        ],
    ),
]


def _normalize_text(*parts: object) -> str:
    return " ".join(str(p) for p in parts if p is not None).lower()


def _classify_theme(stock_name: str, industry_category: str) -> str:
    """
    Map the original industry bucket to a more actionable theme label.
    Falls back to the original industry when no rule matches.
    """
    text = _normalize_text(stock_name, industry_category)
    for theme, keywords, name_keywords in _THEME_RULES:
        if any(keyword.lower() in text for keyword in keywords):
            return theme
        if any(keyword.lower() in text for keyword in name_keywords):
            return theme
    return industry_category or "其他"


# ============================================================
# FinMind REST API (個股查詢，需帶 data_id)
# ============================================================

_FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"


def _finmind_query(dataset: str, **kwargs) -> pd.DataFrame:
    """
    統一 FinMind REST API 查詢介面。
    ⚠️ 基本會員必須帶 data_id 參數才能查詢。
    """
    params = {"dataset": dataset, "token": config.FINMIND_TOKEN}
    params.update(kwargs)
    try:
        resp = _http_session().get(_FINMIND_BASE, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != 200 and "data" not in data:
            return pd.DataFrame()
        df = pd.DataFrame(data.get("data", []))
        time.sleep(config.REQUEST_DELAY)
        return df
    except Exception as e:
        # 不要對已知的批次查詢失敗噴警告
        if "data_id" in kwargs:
            st.warning(f"FinMind API 查詢失敗 ({dataset}, {kwargs.get('data_id','')}): {e}")
        return pd.DataFrame()


# ============================================================
# TWSE 證交所公開端點 (全市場批次查詢)
# ============================================================

@st.cache_data(ttl=config.CACHE_TTL)
def _twse_stock_day_all() -> pd.DataFrame:
    """
    TWSE OpenAPI — 取得全市場當日所有上市股票成交資訊。
    來源: https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL
    """
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        resp = _http_session().get(url, headers=_random_ua(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        # 標準化欄位名稱
        rename_map = {
            "Code": "stock_id",
            "Name": "stock_name",
            "TradeVolume": "volume",
            "TradeValue": "amount",
            "OpeningPrice": "open",
            "HighestPrice": "high",
            "LowestPrice": "low",
            "ClosingPrice": "close",
            "Change": "change",
            "Transaction": "transaction",
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

        # 清理數值欄位 (移除逗號後轉數值)
        for col in ["volume", "amount", "open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(",", ""), errors="coerce"
                )

        df["date"] = pd.Timestamp(datetime.date.today())
        time.sleep(config.REQUEST_DELAY)
        return df

    except Exception as e:
        st.warning(f"TWSE OpenAPI 查詢失敗: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=config.CACHE_TTL)
def _twse_institutional_daily(date_str: str) -> pd.DataFrame:
    """
    TWSE T86 — 取得全市場上市股三大法人買賣超日報。
    來源: https://www.twse.com.tw/rwd/zh/fund/T86
    回傳標準化欄位：date, stock_id, foreign_net_buy, trust_net_buy, total_net_buy (單位：張)
    """
    date_fmt = date_str.replace("-", "")
    url = "https://www.twse.com.tw/rwd/zh/fund/T86"
    params = {"response": "json", "date": date_fmt, "selectType": "ALL"}

    try:
        resp = _http_session().get(url, params=params, headers=_random_ua(), timeout=15)
        time.sleep(config.REQUEST_DELAY * 3)  # TWSE 對頻率較敏感
        resp.raise_for_status()
        data = resp.json()

        if data.get("stat") != "OK" or "data" not in data:
            return pd.DataFrame()

        fields = data.get("fields", [])
        rows = data.get("data", [])
        if not fields or not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=fields)
        df["stock_id"] = df.iloc[:, 0].astype(str).str.strip()
        df["date"] = pd.to_datetime(date_str)

        # 解析數值欄位 (股數 → 張，除以 1000)
        def _parse_shares_col(col_name):
            if col_name in df.columns:
                return (
                    pd.to_numeric(
                        df[col_name].astype(str).str.replace(",", ""),
                        errors="coerce",
                    )
                    / 1000
                )
            return 0.0

        # 嘗試多種可能的欄位名稱 (TWSE 有時會微調)
        foreign_col = None
        trust_col = None
        total_col = None
        for col in fields:
            if "外陸資" in col and "買賣超" in col and ("自營商" not in col or "不含" in col):
                foreign_col = col
            elif "外資" in col and "買賣超" in col and ("自營商" not in col or "不含" in col) and foreign_col is None:
                foreign_col = col
            elif "投信" in col and "買賣超" in col:
                trust_col = col
            elif "三大法人" in col and "買賣超" in col:
                total_col = col

        df["foreign_net_buy"] = _parse_shares_col(foreign_col) if foreign_col else 0.0
        df["trust_net_buy"] = _parse_shares_col(trust_col) if trust_col else 0.0
        df["total_net_buy"] = _parse_shares_col(total_col) if total_col else 0.0

        # 只保留 4 碼數字股票代號
        df = df[df["stock_id"].str.match(r"^\d{4}$", na=False)].copy()

        return df[["date", "stock_id", "foreign_net_buy", "trust_net_buy", "total_net_buy"]].reset_index(drop=True)

    except Exception as e:
        # 靜默失敗 (可能是非交易日)
        return pd.DataFrame()


@st.cache_data(ttl=config.CACHE_TTL)
def _tpex_institutional_daily(date_str: str) -> pd.DataFrame:
    """
    TPEx — 取得全市場上櫃股三大法人買賣超日報。
    來源: https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php
    日期格式：民國年/月/日 (e.g., 115/05/28)
    """
    dt = pd.to_datetime(date_str)
    roc_year = dt.year - 1911
    roc_date = f"{roc_year}/{dt.month:02d}/{dt.day:02d}"

    url = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
    params = {"l": "zh-tw", "o": "json", "se": "AL", "t": "D", "d": roc_date}

    try:
        resp = _http_session().get(url, params=params, headers=_random_ua(), timeout=15)
        time.sleep(config.REQUEST_DELAY * 3)
        resp.raise_for_status()
        data = resp.json()

        rows = data.get("aaData", [])
        if not rows:
            return pd.DataFrame()

        # TPEx 欄位順序：
        # [0]代號 [1]名稱 [2]外資及陸資買股 [3]外資及陸資賣股 [4]外資及陸資淨買
        # [5]外資自營買 [6]外資自營賣 [7]外資自營淨
        # [8]投信買 [9]投信賣 [10]投信淨
        # [11]自營商買(自) [12]自營商賣(自) [13]自營商淨(自)
        # [14]自營商買(避) [15]自營商賣(避) [16]自營商淨(避)
        # [17]三大法人淨
        results = []
        for row in rows:
            if len(row) < 18:
                continue
            stock_id = str(row[0]).strip()
            if not stock_id or not stock_id[:4].isdigit():
                continue
            stock_id = stock_id[:4]

            def _parse(val):
                try:
                    return float(str(val).replace(",", "")) / 1000  # 股→張
                except (ValueError, TypeError):
                    return 0.0

            results.append({
                "date": pd.to_datetime(date_str),
                "stock_id": stock_id,
                "foreign_net_buy": _parse(row[4]),
                "trust_net_buy": _parse(row[10]),
                "total_net_buy": _parse(row[17]) if len(row) > 17 else 0.0,
            })

        df = pd.DataFrame(results)
        df = df[df["stock_id"].str.match(r"^\d{4}$", na=False)]
        return df.reset_index(drop=True)

    except Exception:
        return pd.DataFrame()


# ============================================================
# 公開 API — 股票基本資訊
# ============================================================

@st.cache_data(ttl=config.CACHE_TTL * 24)  # 24 小時快取
def get_stock_info() -> pd.DataFrame:
    """
    取得所有上市/上櫃股票基本資訊。
    回傳欄位：stock_id, stock_name, industry_category, theme_category, type
    """
    df = _finmind_query("TaiwanStockInfo")
    if df.empty:
        return df

    if "type" in df.columns:
        df = df[df["type"].isin(["twse", "tpex"])].copy()

    df = df[df["stock_id"].str.match(r"^\d{4}$", na=False)].copy()
    df["theme_category"] = df.apply(
        lambda row: _classify_theme(
            row.get("stock_name", ""),
            row.get("industry_category", ""),
        ),
        axis=1,
    )
    return df[["stock_id", "stock_name", "industry_category", "theme_category", "type"]].reset_index(drop=True)


def _month_starts(start_date: str, end_date: str) -> list[pd.Timestamp]:
    start = pd.to_datetime(start_date).replace(day=1)
    end = pd.to_datetime(end_date).replace(day=1)
    return list(pd.date_range(start=start, end=end, freq="MS"))


def _roc_date_to_datetime(series: pd.Series) -> pd.Series:
    parts = series.astype(str).str.split("/", expand=True)
    year = pd.to_numeric(parts[0], errors="coerce") + 1911
    month = pd.to_numeric(parts[1], errors="coerce")
    day = pd.to_numeric(parts[2], errors="coerce")
    return pd.to_datetime(
        {"year": year, "month": month, "day": day},
        errors="coerce",
    )


@st.cache_data(ttl=config.CACHE_TTL)
def _twse_stock_daily_history(stock_id: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    TWSE 個股歷史日成交資料。
    官方端點可作為 FinMind 的替代來源，避免 402 quota。
    """
    frames: list[pd.DataFrame] = []
    for month_start in _month_starts(start_date, end_date):
        date_str = month_start.strftime("%Y%m01")
        url = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
        params = {"response": "json", "date": date_str, "stockNo": stock_id}
        try:
            resp = _http_session().get(url, params=params, headers=_random_ua(), timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("stat") != "OK":
                continue
            fields = payload.get("fields", [])
            rows = payload.get("data", [])
            if not rows:
                continue
            df = pd.DataFrame(rows, columns=fields)
            if "日期" not in df.columns:
                continue
            df["date"] = _roc_date_to_datetime(df["日期"])
            if "成交股數" in df.columns:
                df["volume"] = pd.to_numeric(df["成交股數"].astype(str).str.replace(",", ""), errors="coerce")
            if "成交金額" in df.columns:
                df["amount"] = pd.to_numeric(df["成交金額"].astype(str).str.replace(",", ""), errors="coerce")
            if "開盤價" in df.columns:
                df["open"] = pd.to_numeric(df["開盤價"].replace("--", pd.NA), errors="coerce")
            if "最高價" in df.columns:
                df["high"] = pd.to_numeric(df["最高價"].replace("--", pd.NA), errors="coerce")
            if "最低價" in df.columns:
                df["low"] = pd.to_numeric(df["最低價"].replace("--", pd.NA), errors="coerce")
            if "收盤價" in df.columns:
                df["close"] = pd.to_numeric(df["收盤價"].replace("--", pd.NA), errors="coerce")
            df["stock_id"] = stock_id
            frames.append(df[["date", "stock_id", "open", "high", "low", "close", "volume", "amount"]].copy())
            time.sleep(config.REQUEST_DELAY)
        except Exception:
            continue

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    result = result.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    result = result[(result["date"] >= start_dt) & (result["date"] <= end_dt)]
    return result


# ============================================================
# 公開 API — 個股日 K 線
# ============================================================

@st.cache_data(ttl=config.CACHE_TTL)
def get_stock_daily(stock_id: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    取得個股日K線資料 (OHLCV)。
    優先使用 TWSE 官方歷史資料，失敗後再退回 FinMind。
    """
    if start_date is None:
        start_date = utils.get_start_date()
    if end_date is None:
        end_date = utils.get_end_date()

    twse_df = _twse_stock_daily_history(stock_id, start_date, end_date)
    if not twse_df.empty:
        return twse_df

    df = _finmind_query(
        "TaiwanStockPrice",
        data_id=stock_id,
        start_date=start_date,
        end_date=end_date,
    )
    if df.empty:
        return df

    rename_map = {
        "max": "high",
        "min": "low",
        "Trading_Volume": "volume",
        "Trading_money": "amount",
        "Trading_turnover": "turnover",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    df["date"] = pd.to_datetime(df["date"])
    df["stock_id"] = df.get("stock_id", stock_id)

    cols = ["date", "stock_id", "open", "high", "low", "close", "volume", "amount"]
    available = [c for c in cols if c in df.columns]
    return df[available].sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=config.CACHE_TTL * 6)
def get_stock_pe_ratio(stock_id: str, date: str = None) -> float | None:
    """
    取得個股本益比。
    優先使用 TWSE 官方端點，失敗後可回傳 None 由上層決定是否顯示警示。
    """
    if date is None:
        date = utils.get_end_date()

    date_str = pd.to_datetime(date).strftime("%Y%m%d")
    url = "https://www.twse.com.tw/exchangeReport/BWIBBU"
    params = {"response": "json", "date": date_str, "stockNo": stock_id}

    try:
        resp = _http_session().get(url, params=params, headers=_random_ua(), timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("stat") != "OK":
            return None

        fields = payload.get("fields", [])
        rows = payload.get("data", [])
        if not fields or not rows:
            return None

        pe_idx = None
        for idx, field in enumerate(fields):
            if "本益比" in str(field):
                pe_idx = idx
                break
        if pe_idx is None:
            return None

        first = rows[0]
        if len(first) <= pe_idx:
            return None

        pe_raw = str(first[pe_idx]).replace(",", "").strip()
        if pe_raw in {"", "--", "nan", "None"}:
            return None
        return float(pe_raw)
    except Exception:
        return None


# ============================================================
# 公開 API — 全市場當日成交 (產業資金流向用)
# ============================================================

@st.cache_data(ttl=config.CACHE_TTL)
def get_stock_daily_all() -> pd.DataFrame:
    """
    取得全市場當日所有個股成交資訊。
    使用 TWSE OpenAPI (不需 FinMind 批次權限)。
    """
    return _twse_stock_day_all()


# ============================================================
# 公開 API — 三大法人買賣超
# ============================================================

@st.cache_data(ttl=config.CACHE_TTL)
def get_institutional_investors(stock_id: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    取得個股三大法人買賣超。
    先嘗試從 TWSE/TPEx 公開日資料過濾，避免大量查詢 FinMind。
    回傳欄位：date, stock_id, name, buy, sell, net_buy
    """
    if start_date is None:
        start_date = utils.get_start_date(60)
    if end_date is None:
        end_date = utils.get_end_date()

    # 近幾日資料優先走官方端點，通常足以支援短線與籌碼判斷
    official = get_institutional_investors_multi_day(start_date, end_date)
    if not official.empty:
        filtered = official[official["stock_id"] == stock_id].copy()
        if not filtered.empty:
            filtered["date"] = pd.to_datetime(filtered["date"])
            return filtered.sort_values(["date"]).reset_index(drop=True)

    df = _finmind_query(
        "TaiwanStockInstitutionalInvestorsBuySell",
        data_id=stock_id,
        start_date=start_date,
        end_date=end_date,
    )
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    if "buy" in df.columns and "sell" in df.columns:
        df["buy"] = pd.to_numeric(df["buy"], errors="coerce").fillna(0)
        df["sell"] = pd.to_numeric(df["sell"], errors="coerce").fillna(0)
        df["net_buy"] = df["buy"] - df["sell"]

    return df.sort_values(["date", "name"]).reset_index(drop=True)


@st.cache_data(ttl=config.CACHE_TTL)
def get_institutional_investors_multi_day(start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    取得多日全市場法人買賣超。
    使用 TWSE T86 + TPEx 端點 (不需 FinMind 批次權限)。
    回傳標準化欄位：date, stock_id, foreign_net_buy, trust_net_buy, total_net_buy
    """
    if end_date is None:
        end_date = utils.get_end_date()
    if start_date is None:
        start_date = utils.get_start_date(10)

    all_dfs = []
    current = pd.to_datetime(end_date).date()
    start_dt = pd.to_datetime(start_date).date()

    days_fetched = 0
    max_days = 8  # 只取最近幾個交易日以避免過多請求，同時維持足夠的籌碼觀察窗口

    while current >= start_dt and days_fetched < max_days:
        if current.weekday() < 5:  # 跳過週末
            date_str = current.strftime("%Y-%m-%d")

            # TWSE 上市股
            twse_df = _twse_institutional_daily(date_str)
            if not twse_df.empty:
                all_dfs.append(twse_df)

            # TPEx 上櫃股
            tpex_df = _tpex_institutional_daily(date_str)
            if not tpex_df.empty:
                all_dfs.append(tpex_df)

            if not twse_df.empty or not tpex_df.empty:
                days_fetched += 1

        current -= datetime.timedelta(days=1)

    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        return result.sort_values(["stock_id", "date"]).reset_index(drop=True)

    return pd.DataFrame()


# ============================================================
# 公開 API — 融資融券
# ============================================================

@st.cache_data(ttl=config.CACHE_TTL)
def get_margin_trading(stock_id: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    取得個股融資融券資料 (FinMind 帶 data_id)。
    """
    if start_date is None:
        start_date = utils.get_start_date(30)
    if end_date is None:
        end_date = utils.get_end_date()

    df = _finmind_query(
        "TaiwanStockMarginPurchaseShortSale",
        data_id=stock_id,
        start_date=start_date,
        end_date=end_date,
    )
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])

    numeric_cols = [
        "MarginPurchaseBuy", "MarginPurchaseSell",
        "MarginPurchaseCashRepayment", "MarginPurchaseTodayBalance",
        "ShortSaleBuy", "ShortSaleSell",
        "ShortSaleCashRepayment", "ShortSaleTodayBalance",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "MarginPurchaseTodayBalance" in df.columns:
        df["margin_change"] = df["MarginPurchaseTodayBalance"].diff()
    if "ShortSaleTodayBalance" in df.columns:
        df["short_change"] = df["ShortSaleTodayBalance"].diff()

    return df.sort_values("date").reset_index(drop=True)


# ============================================================
# 公開 API — 基本面財報
# ============================================================

@st.cache_data(ttl=config.CACHE_TTL * 6)
def get_financial_statement(stock_id: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    取得個股季度損益表 (FinMind 帶 data_id)。
    回傳 type/value 長表格式。
    """
    if start_date is None:
        start_date = utils.get_start_date(365 * 2)
    if end_date is None:
        end_date = utils.get_end_date()

    df = _finmind_query(
        "TaiwanStockFinancialStatements",
        data_id=stock_id,
        start_date=start_date,
        end_date=end_date,
    )
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    if "value" in df.columns:
        df["value"] = pd.to_numeric(df["value"], errors="coerce")

    return df.sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=config.CACHE_TTL * 6)
def get_month_revenue(stock_id: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    取得個股月營收 (FinMind 帶 data_id)。
    """
    if start_date is None:
        start_date = utils.get_start_date(365 * 2)
    if end_date is None:
        end_date = utils.get_end_date()

    df = _finmind_query(
        "TaiwanStockMonthRevenue",
        data_id=stock_id,
        start_date=start_date,
        end_date=end_date,
    )
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    numeric_cols = ["revenue", "revenue_month", "revenue_year"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=config.CACHE_TTL * 24)
def get_fundamentals_yahoo(stock_id: str) -> dict:
    """
    使用 Yahoo Finance 作為基本面資料的備援。
    返回 {gross_margin, eps, revenue_yoy}。
    """
    result = {
        "gross_margin": None,
        "eps": None,
        "revenue_yoy": None,
        "total_revenue": None,
    }
    try:
        # 台股上市為 .TW, 上櫃為 .TWO，先嘗試 .TW
        stock_info_df = get_stock_info()
        suffix = ".TW"
        if not stock_info_df.empty:
            match = stock_info_df[stock_info_df["stock_id"] == stock_id]
            if not match.empty:
                if match.iloc[0].get("type") == "tpex":
                    suffix = ".TWO"

        ticker = yf.Ticker(f"{stock_id}{suffix}")
        info = ticker.info
        if not info:
            # 嘗試另一種後綴
            alt_suffix = ".TWO" if suffix == ".TW" else ".TW"
            ticker = yf.Ticker(f"{stock_id}{alt_suffix}")
            info = ticker.info

        if info:
            gm = info.get("grossMargins")
            if gm is not None:
                result["gross_margin"] = gm * 100

            eps = info.get("trailingEps")
            if eps is not None:
                result["eps"] = eps

            ry = info.get("revenueGrowth")
            if ry is not None:
                result["revenue_yoy"] = ry * 100

            tr = info.get("totalRevenue")
            if tr is not None:
                result["total_revenue"] = tr

    except Exception as e:
        pass

    return result


# ============================================================
# 產業資金流向 (TWSE + FinMind 混合)
# ============================================================

@st.cache_data(ttl=config.CACHE_TTL)
def get_industry_fund_flow(days: int = 7) -> pd.DataFrame:
    """
    取得各主題成交金額佔比。
    優先使用 TWSE OpenAPI 取得當日全市場資料，合併主題分類後計算。
    僅返回當日快照 (TWSE 只提供當日資料)。
    """
    stock_info = get_stock_info()
    if stock_info.empty:
        return pd.DataFrame()

    # 使用 TWSE OpenAPI 取得當日全市場資料
    price_df = _twse_stock_day_all()

    if price_df.empty or "amount" not in price_df.columns:
        return pd.DataFrame()

    # 合併主題資訊
    merged = price_df.merge(
        stock_info[["stock_id", "industry_category", "theme_category"]],
        on="stock_id",
        how="left",
    )
    merged["theme_category"] = merged["theme_category"].fillna(merged["industry_category"])
    merged = merged.dropna(subset=["theme_category"])
    merged = merged[merged["amount"] > 0]

    if merged.empty:
        return pd.DataFrame()

    # 按主題彙總成交金額
    industry_daily = (
        merged.groupby(["date", "theme_category"])["amount"]
        .sum()
        .reset_index()
    )

    # 計算大盤當日總成交金額
    market_total = merged["amount"].sum()
    industry_daily["market_total"] = market_total
    industry_daily["pct"] = (industry_daily["amount"] / market_total * 100).round(2)
    industry_daily["industry_category"] = industry_daily["theme_category"]

    return industry_daily.sort_values("pct", ascending=False).reset_index(drop=True)


# ============================================================
# 新聞/社群爬蟲 (文字雲來源)
# ============================================================

@st.cache_data(ttl=config.CACHE_TTL)
def fetch_ptt_stock_titles() -> list[str]:
    """
    爬取 PTT Stock 板今日文章標題。
    含重試機制與多重容錯處理。若失敗，返回空列表（由上層提供 fallback）。
    """
    titles = []
    url = "https://www.ptt.cc/bbs/Stock/index.html"

    max_retries = 2
    for attempt in range(max_retries):
        try:
            session = _http_session()
            session.cookies.set("over18", "1")
            headers = _random_ua()
            headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            headers["Accept-Language"] = "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7"
            headers["Connection"] = "keep-alive"

            # 只抓 1 頁，減少被封鎖機率
            resp = session.get(url, headers=headers, timeout=8, verify=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            for entry in soup.select("div.r-ent"):
                title_tag = entry.select_one("div.title a")
                if title_tag:
                    title = title_tag.get_text(strip=True)
                    if title and not title.startswith("[公告]"):
                        titles.append(title)

            if titles:
                break  # 成功取得，跳出重試

        except Exception:
            if attempt < max_retries - 1:
                time.sleep(2)  # 重試前等待
            continue

    return titles


@st.cache_data(ttl=config.CACHE_TTL)
def fetch_anue_news_titles() -> list[str]:
    """
    爬取鉅亨網熱門新聞標題。
    """
    titles = []
    url = "https://news.cnyes.com/news/cat/tw_stock"
    try:
        headers = _random_ua()
        resp = _http_session().get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        for tag in soup.select("a[href*='/news/id/']"):
            title = tag.get_text(strip=True)
            if title and len(title) > 5:
                titles.append(title)

        titles = list(dict.fromkeys(titles))

    except Exception:
        pass

    return titles


@st.cache_data(ttl=config.CACHE_TTL)
def get_all_news_titles() -> list[str]:
    """合併所有新聞/社群來源的標題。若全部失敗，使用示範資料。"""
    ptt = fetch_ptt_stock_titles()
    anue = fetch_anue_news_titles()
    all_titles = ptt + anue

    if not all_titles:
        all_titles = [
            "台積電法說會釋出AI需求強勁訊號 半導體族群全面上攻",
            "外資連續買超台股 加權指數站穩萬八關卡",
            "航運股營收年增亮眼 長榮陽明法人持續加碼",
            "輝達財報超預期 AI伺服器供應鏈股價齊揚",
            "投信連買 散戶融資減少 籌碼面看好半導體後市",
            "聯發科天璣系列出貨暢旺 下半年營收有望創高",
            "台股量縮整理 法人看好拉回買點浮現",
            "生技股利多不斷 新藥臨床數據亮眼推升股價",
            "電動車概念股發酵 鴻海MIH平台吸引國際大廠合作",
            "高速運算HBM需求爆發 先進封裝CoWoS產能供不應求",
            "金融股殖利率優勢 存股族持續買進",
            "美國聯準會降息預期升溫 外資回補台股",
            "光電族群營收回溫 面板雙虎法人轉買",
            "雲端資料中心擴建潮 網通設備股接單暢旺",
            "鋼鐵股價量齊揚 中鋼盤價調漲帶動類股表現",
        ]

    return all_titles


# ============================================================
# 個股公司概述 (Company Profile)
# ============================================================

@st.cache_data(ttl=config.CACHE_TTL * 24)
def get_company_profile(stock_id: str, stock_name: str = "") -> dict:
    """
    取得個股公司概述。
    嘗試從公開資訊觀測站取得，失敗則回傳基本資訊。
    """
    profile = {
        "stock_id": stock_id,
        "stock_name": stock_name,
        "description": "",
        "main_business": "",
        "products": "",
    }

    try:
        url = "https://mops.twse.com.tw/mops/web/ajax_t05st03"
        headers = _random_ua()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = {
            "encodeURIComponent": "1",
            "step": "1",
            "firstin": "1",
            "off": "1",
            "keyword4": "",
            "code1": "",
            "TYPEK": "all",
            "co_id": stock_id,
        }
        resp = _http_session().post(url, data=data, headers=headers, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            tables = soup.select("table.hasBorder")
            if tables:
                rows = tables[0].select("tr")
                for row in rows:
                    cells = row.select("td")
                    if len(cells) >= 2:
                        label = cells[0].get_text(strip=True)
                        value = cells[1].get_text(strip=True)
                        if "營業項目" in label or "主要經營業務" in label:
                            profile["main_business"] = value
                        elif "主要產品" in label or "產品" in label:
                            profile["products"] = value
                        elif "公司簡稱" in label:
                            profile["stock_name"] = value
        time.sleep(config.REQUEST_DELAY)
    except Exception:
        pass

    if not profile["main_business"]:
        stock_info = get_stock_info()
        if not stock_info.empty:
            match = stock_info[stock_info["stock_id"] == stock_id]
            if not match.empty:
                industry = match.iloc[0].get("industry_category", "")
                profile["main_business"] = f"{industry}產業"
                profile["stock_name"] = match.iloc[0].get("stock_name", stock_name)

    return profile
