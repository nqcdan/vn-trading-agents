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


def macro_digest(voz_limit: int = 3, market_limit: int = 5) -> dict:
    """Vĩ mô voz (tâm lý cộng đồng) + tin THỊ TRƯỜNG CafeF (tài chính thật)."""
    try:
        voz = vn_news.fetch_voz()
    except Exception:
        voz = []
    try:
        cafef = _dedup(vn_news.fetch_cafef())
    except Exception:
        cafef = []
    s = vn_news.score_sentiment(voz)
    return {
        "signal": s["signal"], "net": s["net"], "n": s["n"],
        "voz_titles": [n["title"] for n in voz[:voz_limit]],
        "market": [(n["title"], _short_date(n.get("published", ""))) for n in cafef[:market_limit]],
    }


def symbols_news(symbols: list[str], per: int = 3, use_vnstock: bool = True) -> dict:
    """{SYM: {signal, net, n, latest:[(title, source, date)]}} — feed RSS fetch 1 lần, lọc per-symbol."""
    try:
        feeds = vn_news.fetch_cafef() + vn_news.fetch_voz()
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
                  "latest": [(n["title"], n.get("source", ""), _short_date(n.get("published", "")))
                             for n in items[:per]]}
    return out
