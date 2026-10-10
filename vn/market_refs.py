"""Giá tham chiếu phụ cho báo cáo ngày: BTC/ETH (USD) + vàng PNJ (mua/bán).

Nguồn:
  Crypto — CoinGecko simple price (không cần key).
  Vàng   — PNJ edge-api (giamua = mua vào, giaban = bán ra; đơn vị nghìn đồng).

Mọi lỗi mạng/parse đều nuốt → trả phần lấy được, không làm vỡ báo cáo.
"""
from __future__ import annotations
import json
import urllib.request

_CRYPTO_URL = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd"
_PNJ_URL = "https://edge-api.pnj.io/ecom-frontend/v1/get-gold-price"
# Sản phẩm PNJ hiển thị (masp → nhãn gọn). Lấy theo thứ tự này nếu có.
_PNJ_WANT = [("SJC", "SJC"), ("N24K", "Nhẫn trơn 999.9")]


def _get(url: str, timeout: int = 10):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _vn(n: float) -> str:
    return f"{int(round(n)):,}".replace(",", ".")


def crypto_usd() -> str:
    try:
        d = _get(_CRYPTO_URL)
        btc, eth = d["bitcoin"]["usd"], d["ethereum"]["usd"]
        return f"BTC ${btc:,.0f} · ETH ${eth:,.0f}"
    except Exception:
        return ""


def pnj_gold() -> str:
    try:
        rows = _get(_PNJ_URL).get("data", [])
        by = {r.get("masp"): r for r in rows}
        parts = []
        for masp, label in _PNJ_WANT:
            r = by.get(masp)
            if r:
                parts.append(f"{label} {_vn(r['giamua'])}→{_vn(r['giaban'])}")
        return ("Vàng PNJ (mua→bán, nghìn đ): " + " · ".join(parts)) if parts else ""
    except Exception:
        return ""


def market_refs_line() -> str:
    """1 dòng markdown '**Giá tham chiếu:** …' hoặc '' nếu không lấy được gì."""
    segs = [s for s in (crypto_usd(), pnj_gold()) if s]
    return ("**Giá tham chiếu:** " + " · ".join(segs)) if segs else ""
