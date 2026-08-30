"""News feed cho sentiment agent — CafeF RSS + vnstock per-symbol, chỉ dùng stdlib."""
from __future__ import annotations
import contextlib
import io
import re
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

CAFEF_FEEDS = [
    "https://cafef.vn/thi-truong-chung-khoan.rss",
    "https://cafef.vn/doanh-nghiep.rss",
    "https://cafef.vn/tai-chinh-ngan-hang.rss",
]
# voz "Điểm báo" — RSS public (không cần login; trang HTML bị Cloudflare chặn).
VOZ_FEEDS = ["https://voz.vn/f/diem-bao.33/index.rss"]
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) vn-trading-agents/1.0"
_TAG = re.compile(r"<[^>]+>")


def _fetch(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _clean(text: str) -> str:
    return _TAG.sub("", text or "").strip()


def _parse_feed(url: str, source: str) -> list[dict]:
    try:
        root = ET.fromstring(_fetch(url))
    except Exception:
        return []
    items = []
    for it in root.iter("item"):
        pub = it.findtext("pubDate", "")
        try:
            dt = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat()
        except Exception:
            dt = pub
        items.append({"title": _clean(it.findtext("title", "")),
                      "summary": _clean(it.findtext("description", "")),
                      "link": (it.findtext("link", "") or "").strip(),
                      "published": dt, "source": source})
    return items


def fetch_cafef(feeds: list[str] | None = None) -> list[dict]:
    out = []
    for url in feeds or CAFEF_FEEDS:
        out += _parse_feed(url, "CafeF")
    return out


def fetch_voz(feeds: list[str] | None = None) -> list[dict]:
    out = []
    for url in feeds or VOZ_FEEDS:
        out += _parse_feed(url, "voz/Điểm báo")
    return out


def _symbol_mentions(text: str, symbol: str) -> bool:
    return re.search(rf"\b{re.escape(symbol.upper())}\b", (text or "").upper()) is not None


def _vnstock_news(symbol: str, limit: int) -> list[dict]:
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            from vnstock.api.company import Company
            df = Company(symbol=symbol.upper(), source="VCI").news()
    except Exception:
        return []
    out = []
    for _, row in df.head(limit).iterrows():
        title = str(row.get("news_title") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "summary": str(row.get("news_short_content") or "")[:300],
            "link": str(row.get("news_source_link") or ""),
            "published": str(row.get("public_date") or ""),
            "source": str(row.get("news_source") or "vnstock"),
        })
    return out


def get_news(symbol: str, limit: int = 12, cafef_only: bool = False,
             include_voz: bool = True) -> list[dict]:
    """Tin per-symbol: CafeF RSS + voz Điểm báo (lọc theo mã) + vnstock company news."""
    sym = symbol.upper()
    feeds = fetch_cafef() + (fetch_voz() if include_voz else [])
    hit = [n for n in feeds
           if _symbol_mentions(n["title"], sym) or _symbol_mentions(n["summary"], sym)]
    items = hit if cafef_only else hit + _vnstock_news(sym, limit)
    seen, dedup = set(), []
    for n in items:
        key = n["title"][:80]
        if key in seen:
            continue
        seen.add(key)
        dedup.append(n)
    return dedup[:limit]


# ---------- Sentiment ----------

POSITIVE = ["tăng", "lãi", "lợi nhuận", "kỷ lục", "tăng trưởng", "vượt", "cổ tức",
            "trúng thầu", "ký kết", "mở rộng", "khả quan", "bứt phá", "mua ròng",
            "khởi sắc", "hồi phục", "cao nhất", "lập đỉnh", "dẫn đầu", "hưởng lợi"]
NEGATIVE = ["giảm", "lỗ", "sụt", "bán ròng", "cảnh báo", "vi phạm", "phạt", "điều tra",
            "rủi ro", "thoái vốn", "lao dốc", "giảm sàn", "thua lỗ", "bị bán",
            "sụp", "khó khăn", "nợ xấu", "chậm", "hủy", "đình chỉ"]


def score_sentiment(items: list[dict]) -> dict:
    if not items:
        return {"signal": "NEUTRAL", "score": 0, "n": 0, "pos": 0, "neg": 0}
    pos = neg = 0
    for n in items:
        title = (n["title"] or "").lower()
        summ = (n["summary"] or "").lower()
        pos += 2 * sum(w in title for w in POSITIVE) + sum(w in summ for w in POSITIVE)
        neg += 2 * sum(w in title for w in NEGATIVE) + sum(w in summ for w in NEGATIVE)
    net = pos - neg
    signal = "BULLISH" if net > 1 else "BEARISH" if net < -1 else "NEUTRAL"
    return {"signal": signal, "score": 1 if net > 1 else -1 if net < -1 else 0,
            "n": len(items), "pos": pos, "neg": neg, "net": net}
