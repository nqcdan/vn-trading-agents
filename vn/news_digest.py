"""Tổng hợp vĩ mô + tin tức per-symbol cho báo cáo ngày (deterministic).

Tách khỏi `decision_table` (chỉ lo layout). Fetch feed 1 lần rồi lọc per-symbol để
đỡ gọi RSS lặp; vnstock company news chỉ gọi cho mã đang giữ/ứng viên → giàu tin hơn.
Mọi lỗi mạng best-effort: trả rỗng, KHÔNG làm hỏng báo cáo.
"""
from __future__ import annotations

import re

from . import vn_news


def _short_date(published: str) -> str:
    """'2026-09-05T…' | '2026-09-05 10:00' → '09-05'; không parse được → ''."""
    if not published:
        return ""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(published))
    if m:
        return f"{m.group(2)}-{m.group(3)}"
    return ""


def _dedup(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for n in items:
        k = (n.get("title") or "")[:80]
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(n)
    return out


def _by_recency(items: list[dict]) -> list[dict]:
    """Mới nhất trước — published là ISO (sort lexical đúng); tin không parse được xuống cuối."""
    return sorted(items, key=lambda n: str(n.get("published") or ""), reverse=True)


def _diverse_recent(items: list[dict], limit: int) -> list[dict]:
    """Xen kẽ nguồn: mỗi vòng lấy tin mới nhất của từng nguồn → mọi nguồn được hiện,
    không để nguồn đăng dày (CafeF) chiếm hết. Trong 1 nguồn vẫn theo recency."""
    buckets: dict[str, list[dict]] = {}
    for n in _by_recency(items):
        buckets.setdefault(n.get("source", ""), []).append(n)
    out, queues = [], list(buckets.values())
    while len(out) < limit and any(queues):
        for q in queues:
            if q:
                out.append(q.pop(0))
                if len(out) >= limit:
                    break
    return out


def macro_digest(market_limit: int = 8) -> dict:
    """Vĩ mô suy từ headline tin THỊ TRƯỜNG (CafeF/Vietstock/VnEconomy/ĐTCK) — tâm lý + headline."""
    try:
        market = _dedup(vn_news.fetch_market())
    except Exception:
        market = []
    s = vn_news.score_sentiment(market)  # tâm lý trên TOÀN BỘ tin (mọi nguồn)
    return {
        "signal": s["signal"], "net": s["net"], "n": s["n"],
        "market": [{"title": n["title"], "date": _short_date(n.get("published", "")),
                    "link": n.get("link", ""), "source": n.get("source", "")}
                   for n in _diverse_recent(market, market_limit)],
    }


def symbols_news(symbols: list[str], per: int = 4, use_vnstock: bool = True) -> dict:
    """{SYM: {signal, net, n, latest:[{title, source, date, link, summary}]}} — feed fetch 1 lần, lọc per-symbol."""
    try:
        feeds = vn_news.fetch_market()
    except Exception:
        feeds = []
    out = {}
    for sym in symbols:
        s = sym.upper()
        hit = [n for n in feeds
               if vn_news._symbol_mentions(n["title"], s) or vn_news._symbol_mentions(n["summary"], s)]
        if use_vnstock:
            try:
                hit = hit + vn_news._vnstock_news(s, 8)
            except Exception:
                pass
        items = _dedup(hit)
        sc = vn_news.score_sentiment(items)
        out[s] = {"signal": sc["signal"], "net": sc["net"], "n": sc["n"],
                  "latest": [{"title": n["title"], "source": n.get("source", ""),
                              "date": _short_date(n.get("published", "")),
                              "link": n.get("link", ""),
                              "summary": (n.get("summary") or "").strip()}
                             for n in _by_recency(items)[:per]]}
    return out
