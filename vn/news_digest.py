"""Tổng hợp vĩ mô + tin tức per-symbol cho báo cáo ngày (deterministic).

Tách khỏi `decision_table` (chỉ lo layout). Fetch feed 1 lần rồi lọc per-symbol để
đỡ gọi RSS lặp; vnstock company news chỉ gọi cho mã đang giữ (ít) → giàu tin hơn.
Mọi lỗi mạng best-effort: trả rỗng, KHÔNG làm hỏng báo cáo.
"""
from __future__ import annotations

from . import vn_news


def macro_digest(limit: int = 4) -> dict:
    """Vĩ mô voz: signal + net + vài headline gần nhất."""
    try:
        voz = vn_news.fetch_voz()
    except Exception:
        voz = []
    s = vn_news.score_sentiment(voz)
    return {"signal": s["signal"], "net": s["net"], "n": s["n"],
            "titles": [n["title"] for n in voz[:limit]]}


def symbols_news(symbols: list[str], per: int = 2, use_vnstock: bool = True) -> dict:
    """{SYM: {signal, net, n, latest:[(title, source)]}} — feed RSS fetch 1 lần, lọc per-symbol."""
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
                hit = hit + vn_news._vnstock_news(s, 6)
            except Exception:
                pass
        seen, items = set(), []
        for n in hit:
            k = (n.get("title") or "")[:80]
            if not k or k in seen:
                continue
            seen.add(k)
            items.append(n)
        sc = vn_news.score_sentiment(items)
        out[s] = {"signal": sc["signal"], "net": sc["net"], "n": sc["n"],
                  "latest": [(n["title"], n.get("source", "")) for n in items[:per]]}
    return out
