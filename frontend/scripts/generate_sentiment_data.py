from __future__ import annotations

import json
import math
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "frontend" / "src" / "data" / "sentimentData.js"
ROTATION_FILE = ROOT / "frontend" / "src" / "data" / "rotationData.js"
MODEL_NAME = "IDEA-CCNL/Erlangshen-Roberta-110M-Sentiment"

for proxy_key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(proxy_key, None)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
}

PTT_HEADERS = {
    **HEADERS,
    "Referer": "https://www.ptt.cc/bbs/Stock/index.html",
    "Cache-Control": "no-cache",
}

POSITIVE_TERMS = {
    "上漲": 2.0,
    "大漲": 2.0,
    "強漲": 1.8,
    "創高": 1.7,
    "突破": 1.6,
    "買超": 1.6,
    "看多": 1.5,
    "偏多": 1.4,
    "利多": 1.4,
    "轉強": 1.3,
    "旺": 1.1,
    "成長": 1.1,
    "復甦": 1.0,
    "升溫": 0.9,
}

NEGATIVE_TERMS = {
    "下跌": 2.0,
    "大跌": 2.0,
    "重挫": 1.9,
    "破底": 1.8,
    "賣超": 1.6,
    "看空": 1.5,
    "偏空": 1.4,
    "利空": 1.4,
    "轉弱": 1.3,
    "衰退": 1.2,
    "降溫": 1.1,
    "回檔": 1.0,
    "風險": 0.9,
    "警訊": 0.9,
}


@dataclass
class SentimentItem:
    source: str
    source_type: str
    title: str
    url: str | None = None
    published_at: str | None = None
    api_score: float | None = None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def get_with_retry(
    session: requests.Session,
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int | tuple[int, int] = 14,
    attempts: int = 3,
    base_sleep: float = 1.5,
) -> requests.Response:
    last_error: Exception | None = None
    session.trust_env = False
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, headers=headers or HEADERS, timeout=timeout)
            response.raise_for_status()
            return response
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(base_sleep * attempt)
    assert last_error is not None
    raise last_error


def load_dotenv() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = ROOT / ".env"
    if not env_file.exists():
        return values
    for raw_line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


DOTENV = load_dotenv()


def secret(name: str) -> str | None:
    return os.getenv(name) or DOTENV.get(name)


def sanitize_error(exc: Exception | str) -> str:
    message = str(exc)
    if "403 Client Error: Forbidden" in message:
        return "403 Forbidden: API plan or permission does not allow this endpoint"
    if "404 Client Error: Not Found" in message:
        return "404 Not Found: endpoint unavailable"
    for key in ("ALPHA_VANTAGE_API_KEY", "FMP_API_KEY"):
        value = secret(key)
        if value:
            message = message.replace(value, "[redacted]")
    message = re.sub(r"apikey=[^&\s]+", "apikey=[redacted]", message)
    return message


def fetch_ptt(limit: int = 35) -> tuple[list[SentimentItem], str]:
    items: list[SentimentItem] = []
    url = "https://www.ptt.cc/bbs/Stock/index.html"
    session = requests.Session()
    session.trust_env = False
    session.cookies.set("over18", "1")

    try:
        seen: set[str] = set()
        for _ in range(2):
            response = get_with_retry(session, url, headers=PTT_HEADERS, timeout=18, attempts=4, base_sleep=2.0)
            soup = BeautifulSoup(response.text, "html.parser")
            for entry in soup.select("div.r-ent"):
                link = entry.select_one("div.title a")
                if not link:
                    continue
                title = clean_text(link.get_text())
                href = link.get("href")
                if not title or title in seen:
                    continue
                seen.add(title)
                items.append(
                    SentimentItem(
                        source="PTT Stock",
                        source_type="forum",
                        title=title,
                        url=f"https://www.ptt.cc{href}" if href else None,
                    )
                )
                if len(items) >= limit:
                    return items, "ok"
            prev = soup.select_one("a.btn.wide:-soup-contains('上頁')")
            if not prev or not prev.get("href"):
                break
            url = f"https://www.ptt.cc{prev['href']}"
            time.sleep(1.2)
        return items, "ok" if items else "empty"
    except Exception as exc:
        return items, f"error: {sanitize_error(exc)}"


def fetch_google_news(limit: int = 35) -> tuple[list[SentimentItem], str]:
    query = requests.utils.quote("台股 OR 台積電 OR 半導體 OR AI概念股 OR 0050 when:2d")
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        session = requests.Session()
        session.trust_env = False
        response = get_with_retry(session, url, headers=HEADERS, timeout=14, attempts=3, base_sleep=2.0)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        items = []
        for node in root.findall("./channel/item")[:limit]:
            title = clean_text(node.findtext("title") or "")
            if not title:
                continue
            items.append(
                SentimentItem(
                    source="Google News 台股",
                    source_type="news",
                    title=title,
                    url=node.findtext("link"),
                    published_at=node.findtext("pubDate"),
                )
            )
        return items, "ok" if items else "empty"
    except Exception as exc:
        return [], f"error: {sanitize_error(exc)}"


def parse_av_score(raw: Any) -> float | None:
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return None
    return clamp(score, -1.0, 1.0)


def fetch_alpha_vantage(limit: int = 35) -> tuple[list[SentimentItem], str]:
    api_key = secret("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        return [], "missing API key"
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": "TSM",
        "topics": "technology,financial_markets",
        "sort": "LATEST",
        "limit": str(limit),
        "apikey": api_key,
    }
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get("https://www.alphavantage.co/query", params=params, headers=HEADERS, timeout=18)
        response.raise_for_status()
        payload = response.json()
        if payload.get("Information") or payload.get("Note"):
            return [], payload.get("Information") or payload.get("Note")
        feed = payload.get("feed") or []
        items = []
        for article in feed[:limit]:
            title = clean_text(article.get("title", ""))
            if not title:
                continue
            items.append(
                SentimentItem(
                    source="Alpha Vantage News",
                    source_type="api_news",
                    title=title,
                    url=article.get("url"),
                    published_at=article.get("time_published"),
                    api_score=parse_av_score(article.get("overall_sentiment_score")),
                )
            )
        return items, "ok" if items else "empty"
    except Exception as exc:
        return [], f"error: {sanitize_error(exc)}"


def fetch_cnn_fear_greed() -> dict:
    endpoints = [
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2024-01-01",
    ]
    for url in endpoints:
        try:
            response = requests.get(url, headers=HEADERS, timeout=16)
            response.raise_for_status()
            payload = response.json()
            fg = payload.get("fear_and_greed") or payload.get("fearGreed") or {}
            raw_score = fg.get("score") or fg.get("value")
            if raw_score is None and isinstance(payload.get("data"), list) and payload["data"]:
                raw_score = payload["data"][-1].get("y")
            score = float(raw_score)
            rating = fg.get("rating") or fg.get("status") or label_0_100(score)
            return {
                "name": "CNN Fear & Greed",
                "status": "ok",
                "score": clamp(score, 0, 100),
                "rawValue": clamp(score, 0, 100),
                "state": translate_fear_greed_state(str(rating), score),
                "sourceUrl": "https://www.cnn.com/markets/fear-and-greed",
            }
        except Exception:
            continue
    return {
        "name": "CNN Fear & Greed",
        "status": "unavailable: official page data endpoint did not return a score",
        "score": None,
        "rawValue": None,
        "state": "未納入",
        "sourceUrl": "https://www.cnn.com/markets/fear-and-greed",
    }


def fetch_google_trends() -> dict:
    keywords = ["台股", "台積電", "0050", "AI概念股", "半導體"]
    try:
        from pytrends.request import TrendReq

        last_error: Exception | None = None
        frame = None
        for attempt in range(1, 4):
            try:
                pytrends = TrendReq(hl="zh-TW", tz=480, timeout=(10, 25))
                pytrends.build_payload(keywords, timeframe="now 7-d", geo="TW")
                frame = pytrends.interest_over_time()
                break
            except Exception as exc:
                last_error = exc
                if "429" in str(exc):
                    time.sleep(20 * attempt)
                else:
                    time.sleep(4 * attempt)
        if frame is None:
            assert last_error is not None
            raise last_error
        if frame.empty:
            raise RuntimeError("empty Google Trends response")
        data = frame.drop(columns=["isPartial"], errors="ignore")
        latest = float(data.tail(24).mean().mean())
        baseline = float(data.head(max(1, len(data) - 24)).mean().mean())
        change = (latest - baseline) / baseline if baseline > 0 else 0.0
        score = clamp(50 + change * 45, 0, 100)
        return {
            "name": "Google Trends",
            "status": "ok",
            "score": score,
            "rawValue": latest,
            "state": "搜尋熱度升溫" if change > 0.18 else "搜尋熱度降溫" if change < -0.18 else "搜尋熱度持平",
            "changePct": change,
            "keywords": keywords,
            "sourceUrl": "https://trends.google.com/",
        }
    except Exception as exc:
        status = "rate_limited_429" if "429" in str(exc) else f"unavailable: {exc}"
        return {
            "name": "Google Trends",
            "status": status,
            "score": None,
            "rawValue": None,
            "state": "未納入",
            "changePct": None,
            "keywords": keywords,
            "sourceUrl": "https://trends.google.com/",
        }


def load_money_flow_component() -> dict:
    try:
        text = ROTATION_FILE.read_text(encoding="utf-8")
        match = re.search(r"export const rotationData = (\{.*\});\s*$", text, re.S)
        if not match:
            raise RuntimeError("rotationData payload not found")
        payload = json.loads(match.group(1))
        summary = payload.get("summary", {})
        total_net5 = float(summary.get("totalNet5", 0))
        total_net20 = float(summary.get("totalNet20", 0))
        sector_count = int(summary.get("candidateSectorCount", 0))
        directional = clamp(total_net5 / 600000 * 25, -35, 35)
        persistence = clamp((total_net20 / 1500000) * 10, -10, 10)
        score = clamp(50 + directional + persistence + min(sector_count, 8), 0, 100)
        return {
            "name": "法人資金流向",
            "status": "ok",
            "score": score,
            "rawValue": total_net5,
            "state": "資金偏多" if score >= 60 else "資金偏空" if score <= 40 else "資金中性",
            "sourceUrl": "frontend/src/data/rotationData.js",
            "net5": total_net5,
            "net20": total_net20,
            "candidateSectorCount": sector_count,
        }
    except Exception as exc:
        return {
            "name": "法人資金流向",
            "status": f"unavailable: {exc}",
            "score": None,
            "rawValue": None,
            "state": "未納入",
            "sourceUrl": "frontend/src/data/rotationData.js",
        }


def load_bert_pipeline() -> tuple[Any | None, str]:
    try:
        from transformers import pipeline

        return pipeline("text-classification", model=MODEL_NAME, device=-1), MODEL_NAME
    except Exception as exc:
        return None, f"unavailable: {exc}"


def lexicon_score(text: str) -> float:
    pos = sum(weight for term, weight in POSITIVE_TERMS.items() if term in text)
    neg = sum(weight for term, weight in NEGATIVE_TERMS.items() if term in text)
    if pos == 0 and neg == 0:
        return 0.0
    return clamp((pos - neg) / (pos + neg + 1.5), -1.0, 1.0)


def bert_score(pipe: Any | None, text: str) -> tuple[float | None, float | None, str | None]:
    if pipe is None:
        return None, None, None
    try:
        result = pipe(text[:180])[0]
        label = str(result.get("label", "")).lower()
        confidence = float(result.get("score", 0))
        if "pos" in label or label in {"1", "label_1", "positive"}:
            return confidence, confidence, result.get("label")
        if "neg" in label or label in {"0", "label_0", "negative"}:
            return -confidence, confidence, result.get("label")
        return 0.0, confidence, result.get("label")
    except Exception:
        return None, None, None


def classify_items(items: list[SentimentItem]) -> tuple[list[dict], dict]:
    pipe, model_status = load_bert_pipeline()
    rows = []
    for item in items:
        lex = lexicon_score(item.title)
        bert, confidence, raw_label = bert_score(pipe, item.title)
        if item.api_score is not None and bert is not None:
            score = clamp(0.45 * item.api_score + 0.35 * bert + 0.20 * lex, -1.0, 1.0)
            method = "api_sentiment_plus_bert"
        elif item.api_score is not None:
            score = item.api_score
            method = "api_sentiment"
        elif bert is not None:
            score = clamp(0.35 * bert + 0.65 * lex, -1.0, 1.0)
            method = "bert_plus_finance_lexicon"
        else:
            score = lex
            method = "finance_lexicon"

        if score >= 0.18:
            label = "positive"
        elif score <= -0.18:
            label = "negative"
        else:
            label = "neutral"
        rows.append(
            {
                "source": item.source,
                "sourceType": item.source_type,
                "title": item.title,
                "url": item.url,
                "publishedAt": item.published_at,
                "score": score,
                "label": label,
                "method": method,
                "apiScore": item.api_score,
                "bertRawLabel": raw_label,
                "bertConfidence": confidence,
                "lexiconScore": lex,
            }
        )

    scores = [row["score"] for row in rows]
    avg = sum(scores) / len(scores) if scores else 0.0
    confidence = min(1.0, math.sqrt(len(rows)) / 10) if rows else 0.0
    summary = {
        "state": label_direction(avg),
        "score": avg,
        "confidence": confidence,
        "itemCount": len(rows),
        "positiveCount": sum(1 for row in rows if row["label"] == "positive"),
        "neutralCount": sum(1 for row in rows if row["label"] == "neutral"),
        "negativeCount": sum(1 for row in rows if row["label"] == "negative"),
        "model": "API Sentiment + BERT + Finance Lexicon" if pipe is not None else "API Sentiment + Finance Lexicon",
        "bertModel": MODEL_NAME if pipe is not None else None,
        "modelStatus": model_status,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    return rows, summary


def label_direction(score: float) -> str:
    if score >= 0.18:
        return "偏多"
    if score <= -0.18:
        return "偏空"
    return "中性"


def label_0_100(score: float) -> str:
    if score >= 75:
        return "極度貪婪"
    if score >= 60:
        return "偏多"
    if score <= 25:
        return "極度恐懼"
    if score <= 40:
        return "偏空"
    return "中性"


def translate_fear_greed_state(value: str, score: float) -> str:
    state = (value or "").strip().lower()
    mapping = {
        "extreme fear": "極度恐懼",
        "fear": "恐懼",
        "neutral": "中性",
        "greed": "貪婪",
        "extreme greed": "極度貪婪",
    }
    return mapping.get(state, label_0_100(score))


def aggregate_sources(items: list[dict], statuses: dict[str, str]) -> list[dict]:
    source_names = [
        "PTT Stock",
        "Google News 台股",
        "Alpha Vantage News",
    ]
    rows = []
    for source in source_names:
        source_items = [item for item in items if item["source"] == source]
        avg = sum(item["score"] for item in source_items) / len(source_items) if source_items else 0.0
        rows.append(
            {
                "name": source,
                "status": statuses.get(source, "not_run"),
                "count": len(source_items),
                "score": avg,
                "positiveCount": sum(1 for item in source_items if item["label"] == "positive"),
                "negativeCount": sum(1 for item in source_items if item["label"] == "negative"),
            }
        )
    return rows


def score_from_sentiment(avg: float) -> float:
    return clamp(50 + avg * 50, 0, 100)


def build_composite(summary: dict, sources: list[dict]) -> dict:
    cnn = fetch_cnn_fear_greed()
    trends = fetch_google_trends()
    money_flow = load_money_flow_component()

    ptt = next((source for source in sources if source["name"] == "PTT Stock"), None)
    ptt_score = score_from_sentiment(ptt["score"]) if ptt and ptt["count"] > 0 else None

    news_sources = [source for source in sources if source["name"] in {"Google News 台股", "Alpha Vantage News"}]
    news_counts = sum(source["count"] for source in news_sources)
    news_avg = (
        sum(source["score"] * source["count"] for source in news_sources) / news_counts
        if news_counts
        else None
    )
    news_score = score_from_sentiment(news_avg) if news_avg is not None else None

    components = [
        {
            "key": "fearGreed",
            "name": "Fear & Greed",
            "weight": 25,
            "score": cnn["score"],
            "state": cnn["state"],
            "status": cnn["status"],
            "source": "CNN Fear & Greed",
        },
        {
            "key": "ptt",
            "name": "PTT 散戶情緒",
            "weight": 20,
            "score": ptt_score,
            "state": label_0_100(ptt_score) if ptt_score is not None else "未納入",
            "status": ptt["status"] if ptt else "not_run",
            "source": "PTT Stock",
        },
        {
            "key": "trends",
            "name": "Google Trends",
            "weight": 15,
            "score": trends["score"],
            "state": trends["state"],
            "status": trends["status"],
            "source": "Google Trends",
        },
        {
            "key": "news",
            "name": "新聞情緒",
            "weight": 20,
            "score": news_score,
            "state": label_0_100(news_score) if news_score is not None else "未納入",
            "status": "ok" if news_counts else "no usable news items",
            "source": "Google News + Alpha Vantage",
        },
        {
            "key": "moneyFlow",
            "name": "法人資金流向",
            "weight": 20,
            "score": money_flow["score"],
            "state": money_flow["state"],
            "status": money_flow["status"],
            "source": "本地法人資金輪動資料",
        },
    ]
    active = [component for component in components if component["score"] is not None]
    active_weight = sum(component["weight"] for component in active)
    score = (
        sum(component["score"] * component["weight"] for component in active) / active_weight
        if active_weight
        else None
    )
    state = label_0_100(score) if score is not None else "資料不足"
    if score is None:
        advice, risk = "暫停用情緒因子決策", "未知"
    elif score >= 75:
        advice, risk = "正常持股，但避免追高加碼", "中高"
    elif score >= 60:
        advice, risk = "正常持股，維持策略訊號", "中低"
    elif score >= 45:
        advice, risk = "保守持股，只接受高分訊號", "中"
    elif score >= 30:
        advice, risk = "降低資金使用率，等待情緒修復", "中高"
    else:
        advice, risk = "防守為主，暫停新增部位", "高"

    return {
        "score": score,
        "state": state,
        "advice": advice,
        "risk": risk,
        "activeWeight": active_weight,
        "components": components,
        "details": {
            "cnnFearGreed": cnn,
            "googleTrends": trends,
            "moneyFlow": money_flow,
            "newsAverage": news_avg,
            "retailAverage": ptt["score"] if ptt else None,
        },
    }


def build_source_summaries(composite: dict, sources: list[dict], items: list[dict]) -> list[dict]:
    details = composite["details"]
    ptt = next((source for source in sources if source["name"] == "PTT Stock"), None)
    google_news = next((source for source in sources if source["name"] == "Google News 台股"), None)
    alpha = next((source for source in sources if source["name"] == "Alpha Vantage News"), None)
    trends = details["googleTrends"]
    fear_greed = details["cnnFearGreed"]
    money_flow = details["moneyFlow"]

    def headline(source_name: str) -> str:
        source_items = [item for item in items if item["source"] == source_name]
        return source_items[0]["title"] if source_items else "目前沒有可顯示的最新標題"

    return [
        {
            "name": "CNN Fear & Greed",
            "category": "市場風險偏好",
            "value": f"{fear_greed['score']:.0f}/100" if fear_greed["score"] is not None else "未取得",
            "state": fear_greed["state"],
            "summary": "美股風險偏好偏保守，對台股屬外部情緒降溫訊號。" if fear_greed["score"] is not None and fear_greed["score"] < 50 else "美股風險偏好升溫，外部情緒對風險資產較友善。",
        },
        {
            "name": "PTT Stock",
            "category": "散戶討論情緒",
            "value": f"{ptt['count']} 則" if ptt else "0 則",
            "state": label_0_100(score_from_sentiment(ptt["score"])) if ptt and ptt["count"] else "未取得",
            "summary": f"偏多 {ptt['positiveCount']} 則、偏空 {ptt['negativeCount']} 則，整體討論接近中性。" if ptt else "目前沒有可用討論資料。",
        },
        {
            "name": "Google Trends",
            "category": "搜尋熱度",
            "value": f"{trends['score']:.0f}/100" if trends["score"] is not None else "未取得",
            "state": trends["state"],
            "summary": "台股、台積電、0050、AI概念股與半導體搜尋熱度較基準降溫。" if trends.get("changePct", 0) is not None and trends.get("changePct", 0) < 0 else "台股相關搜尋熱度較基準升溫。",
        },
        {
            "name": "Google News 台股",
            "category": "新聞情緒",
            "value": f"{google_news['count']} 則" if google_news else "0 則",
            "state": label_0_100(score_from_sentiment(google_news["score"])) if google_news and google_news["count"] else "未取得",
            "summary": headline("Google News 台股"),
        },
        {
            "name": "Alpha Vantage News",
            "category": "API 新聞情緒",
            "value": f"{alpha['count']} 則" if alpha else "0 則",
            "state": label_0_100(score_from_sentiment(alpha["score"])) if alpha and alpha["count"] else "未取得",
            "summary": headline("Alpha Vantage News"),
        },
        {
            "name": "法人資金流向",
            "category": "資金情緒",
            "value": f"{money_flow.get('net5', 0):,.0f} 張",
            "state": money_flow["state"],
            "summary": f"5 日法人淨買超 {money_flow.get('net5', 0):,.0f} 張，20 日淨買超 {money_flow.get('net20', 0):,.0f} 張。",
        },
    ]


def write_payload(payload: dict) -> None:
    OUT.write_text(
        "export const sentimentData = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )


def main() -> None:
    source_batches = []
    statuses: dict[str, str] = {}
    for name, fetcher in [
        ("PTT Stock", fetch_ptt),
        ("Google News 台股", fetch_google_news),
        ("Alpha Vantage News", fetch_alpha_vantage),
    ]:
        items, status = fetcher()
        statuses[name] = status
        source_batches.extend(items)

    classified, summary = classify_items(source_batches)
    classified = sorted(classified, key=lambda row: abs(row["score"]), reverse=True)
    sources = aggregate_sources(classified, statuses)
    composite = build_composite(summary, sources)

    payload = {
        "summary": summary,
        "marketSentiment": composite,
        "sources": sources,
        "sourceSummaries": build_source_summaries(composite, sources, classified),
        "items": classified[:100],
    }
    write_payload(payload)
    print(
        json.dumps(
            {
                "items": len(classified),
                "marketSentimentScore": composite["score"],
                "activeWeight": composite["activeWeight"],
                "sources": statuses,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
