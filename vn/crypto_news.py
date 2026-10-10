"""Tin & sentiment crypto — RSS tiếng Anh (CoinTelegraph/Decrypt/CryptoSlate/BitcoinMag).

Tái dụng parser RSS của vn_news; lexicon tiếng Anh. Lọc per-coin theo từ khoá (BTC↔bitcoin).
Mọi lỗi mạng → trả rỗng/neutral, không làm vỡ pipeline.
"""
from __future__ import annotations

from . import vn_news

CRYPTO_FEEDS = [
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("CryptoSlate", "https://cryptoslate.com/feed/"),
    ("BitcoinMag", "https://bitcoinmagazine.com/.rss/full/"),
]
# ticker → từ khoá nhận diện trong tiêu đề/summary
SYMBOL_TERMS = {
    "BTC": ["btc", "bitcoin"],
    "ETH": ["eth", "ethereum", "ether"],
    "SOL": ["sol", "solana"],
    "BNB": ["bnb", "binance coin"],
}
POSITIVE = ["surge", "rally", "gain", "soar", "bullish", "jump", "record", "high",
            "adoption", "inflow", "breakout", "upgrade", "rise", "boost", "approve",
            "institutional", "accumulate", "milestone", "partnership"]
NEGATIVE = ["crash", "plunge", "drop", "fall", "bearish", "selloff", "sell-off", "hack",
            "exploit", "ban", "lawsuit", "outflow", "liquidation", "decline", "dump",
            "fear", "warning", "sink", "slump", "scam", "fraud"]


_MARKET_CACHE: list[dict] | None = None


def fetch_market_crypto() -> list[dict]:
    global _MARKET_CACHE
    if _MARKET_CACHE is not None:
        return _MARKET_CACHE
    out: list[dict] = []
    for source, url in CRYPTO_FEEDS:
        out += vn_news._parse_feed(url, source)
    _MARKET_CACHE = out
    return out


def _mentions(text: str, terms: list[str]) -> bool:
    t = (text or "").lower()
    return any(w in t for w in terms)


def get_news_crypto(symbol: str, limit: int = 12, items: list[dict] | None = None) -> list[dict]:
    terms = SYMBOL_TERMS.get(symbol.upper(), [symbol.lower()])
    feed = items if items is not None else fetch_market_crypto()
    hit = [n for n in feed if _mentions(n.get("title"), terms) or _mentions(n.get("summary"), terms)]
    seen, dedup = set(), []
    for n in hit:
        k = n["title"][:80]
        if k not in seen:
            seen.add(k); dedup.append(n)
    return dedup[:limit]


def score(items: list[dict]) -> dict:
    pos = neg = 0
    for n in items:
        title = (n.get("title") or "").lower()
        summ = (n.get("summary") or "").lower()
        pos += 2 * sum(w in title for w in POSITIVE) + sum(w in summ for w in POSITIVE)
        neg += 2 * sum(w in title for w in NEGATIVE) + sum(w in summ for w in NEGATIVE)
    net = pos - neg
    signal = "BULLISH" if net > 0 else "BEARISH" if net < 0 else "NEUTRAL"
    return {"signal": signal, "score": 1 if net > 0 else -1 if net < 0 else 0,
            "net": net, "pos": pos, "neg": neg, "n": len(items)}


def sentiment_crypto(symbol: str, limit: int = 12, market: list[dict] | None = None) -> dict:
    try:
        feed = market if market is not None else fetch_market_crypto()
        items = get_news_crypto(symbol, limit=limit, items=feed)
        s = score(items)
    except Exception:  # noqa: BLE001
        return {"agent": "sentiment", "signal": "NEUTRAL", "score": 0, "net": 0, "n": 0, "headlines": []}
    s["agent"] = "sentiment"
    s["headlines"] = [n["title"] for n in items[:6]]
    return s


def macro_mood_crypto() -> dict:
    try:
        m = score(fetch_market_crypto())
    except Exception:  # noqa: BLE001
        return {"agent": "macro", "signal": "NEUTRAL", "net": 0}
    m["agent"] = "macro"
    return m
