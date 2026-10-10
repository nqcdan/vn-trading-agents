"""Lớp dữ liệu crypto (BTC/ETH…) — OHLC từ Binance klines, fallback CoinGecko.

Trả DataFrame cùng schema với vn_data (date,open,high,low,close,volume) → tái dụng
công thức chỉ báo `vn_data.indicators_from_ohlcv`. Giá đơn vị USD (không ×1000).
"""
from __future__ import annotations
import json
import os
import urllib.request
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from . import cache, vn_data

# ticker ngắn → (Binance symbol, CoinGecko id)
SYMBOL_MAP = {
    "BTC": ("BTCUSDT", "bitcoin"),
    "ETH": ("ETHUSDT", "ethereum"),
    "SOL": ("SOLUSDT", "solana"),
    "BNB": ("BNBUSDT", "binancecoin"),
}
_BINANCE = "https://api.binance.com/api/v3/klines"
_COINGECKO = "https://api.coingecko.com/api/v3/coins/{id}/market_chart/range"


def resolve(symbol: str) -> tuple[str, str]:
    return SYMBOL_MAP[symbol.upper()]


def _http_json(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _ms(d: str) -> int:
    return int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _from_binance(binance_sym: str, start: str, end: str) -> pd.DataFrame:
    url = (f"{_BINANCE}?symbol={binance_sym}&interval=1d"
           f"&startTime={_ms(start)}&endTime={_ms(end)}&limit=1000")
    rows = _http_json(url)
    if not rows:
        raise RuntimeError("binance empty")
    df = pd.DataFrame({
        "date": pd.to_datetime([r[0] for r in rows], unit="ms"),
        "open": [float(r[1]) for r in rows],
        "high": [float(r[2]) for r in rows],
        "low": [float(r[3]) for r in rows],
        "close": [float(r[4]) for r in rows],
        "volume": [float(r[5]) for r in rows],
    })
    return df


def _from_coingecko(cg_id: str, start: str, end: str) -> pd.DataFrame:
    frm = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
    to = int(datetime.fromisoformat(end).replace(tzinfo=timezone.utc).timestamp())
    url = _COINGECKO.format(id=cg_id) + f"?vs_currency=usd&from={frm}&to={to}"
    d = _http_json(url)
    prices = d.get("prices", [])
    if not prices:
        raise RuntimeError("coingecko empty")
    vols = {int(ts): v for ts, v in d.get("total_volumes", [])}
    raw = pd.DataFrame({
        "ts": [int(p[0]) for p in prices],
        "close": [float(p[1]) for p in prices],
    })
    raw["volume"] = [float(vols.get(t, 0.0)) for t in raw["ts"]]
    raw["day"] = pd.to_datetime(raw["ts"], unit="ms").dt.normalize()
    # CoinGecko range <90 ngày trả dữ liệu giờ → gộp về daily (close cuối ngày, volume tổng).
    g = raw.groupby("day", as_index=False).agg(close=("close", "last"), volume=("volume", "sum"))
    g = g.rename(columns={"day": "date"})
    for c in ("open", "high", "low"):  # synth OHLC = close
        g[c] = g["close"]
    return g[["date", "open", "high", "low", "close", "volume"]]


def get_ohlcv_crypto(symbol: str, start: str, end: str) -> pd.DataFrame:
    binance_sym, cg_id = resolve(symbol)
    try:
        df = _from_binance(binance_sym, start, end)
    except Exception:
        df = _from_coingecko(cg_id, start, end)
    return df.sort_values("date").reset_index(drop=True)


def get_indicators_crypto(symbol: str, as_of: str | None = None, lookback_days: int = 200) -> dict:
    def _compute() -> dict:
        end = as_of or date.today().isoformat()
        start = (date.fromisoformat(end) - timedelta(days=lookback_days * 2)).isoformat()
        return vn_data.indicators_from_ohlcv(get_ohlcv_crypto(symbol, start, end), symbol)

    return cache.memoize("indicators_crypto", symbol.upper(), _compute, as_of=as_of)


def get_group_symbols_crypto() -> list[str]:
    env = os.environ.get("VN_CRYPTO_SYMBOLS", "").strip()
    if env:
        return [s.strip().upper() for s in env.split(",") if s.strip()]
    return ["BTC", "ETH"]
