"""Tỷ giá USD→VND cho hạch toán crypto (giá thị trường USD, tiền/ví thật VND).

Suy tỷ giá từ CoinGecko (giá BTC theo cả usd & vnd) — không cần key. Lỗi → env VN_USD_VND
hoặc mặc định 26000. Cache trong tiến trình (mỗi lần chạy lấy 1 lần)."""
from __future__ import annotations
import json
import os
import urllib.request

_URL = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd,vnd"
_DEFAULT = 26000.0
_CACHE: float | None = None


def usd_vnd() -> float:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    rate = None
    try:
        req = urllib.request.Request(_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            b = json.loads(r.read().decode("utf-8"))["bitcoin"]
        if b.get("usd") and b.get("vnd"):
            rate = float(b["vnd"]) / float(b["usd"])
    except Exception:
        rate = None
    if not rate:
        env = os.environ.get("VN_USD_VND", "").strip()
        rate = float(env) if env else _DEFAULT
    _CACHE = rate
    return rate
