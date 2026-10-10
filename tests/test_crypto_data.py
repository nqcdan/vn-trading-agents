"""TDD Stage 1 — data layer crypto (Binance klines + CoinGecko fallback)."""
import pandas as pd
import pytest

from vn import crypto_data


def test_symbol_map():
    assert crypto_data.resolve("BTC") == ("BTCUSDT", "bitcoin")
    assert crypto_data.resolve("eth") == ("ETHUSDT", "ethereum")
    with pytest.raises(KeyError):
        crypto_data.resolve("DOGE_UNKNOWN")


def _binance_payload():
    # [openTime, open, high, low, close, volume, ...]
    return [
        [1700000000000, "100.0", "110.0", "95.0", "105.0", "12.5", 0, 0, 0, 0, 0, 0],
        [1700086400000, "105.0", "120.0", "104.0", "118.0", "20.0", 0, 0, 0, 0, 0, 0],
    ]


def test_ohlcv_binance(monkeypatch):
    def fake(url, **kw):
        assert "binance" in url and "BTCUSDT" in url
        return _binance_payload()
    monkeypatch.setattr(crypto_data, "_http_json", fake)
    df = crypto_data.get_ohlcv_crypto("BTC", "2023-11-14", "2023-11-16")
    assert list(df.columns[:6]) == ["date", "open", "high", "low", "close", "volume"]
    assert float(df["close"].iloc[-1]) == 118.0
    assert float(df["high"].iloc[0]) == 110.0
    assert df["date"].is_monotonic_increasing


def test_ohlcv_fallback_coingecko(monkeypatch):
    def fake(url, **kw):
        if "binance" in url:
            raise RuntimeError("binance geo-blocked")
        assert "coingecko" in url and "bitcoin" in url
        return {"prices": [[1700000000000, 105.0], [1700086400000, 118.0]],
                "total_volumes": [[1700000000000, 12.5], [1700086400000, 20.0]]}
    monkeypatch.setattr(crypto_data, "_http_json", fake)
    df = crypto_data.get_ohlcv_crypto("BTC", "2023-11-14", "2023-11-16")
    assert float(df["close"].iloc[-1]) == 118.0
    # fallback synth OHLC = close
    assert float(df["open"].iloc[-1]) == float(df["close"].iloc[-1])


def test_indicators_crypto(monkeypatch):
    # chuỗi 60 ngày tăng đều → sma20<sma50? close trên cả hai, rsi cao
    closes = [100 + i for i in range(60)]
    df = pd.DataFrame({
        "date": pd.to_datetime(pd.date_range("2023-09-01", periods=60)),
        "open": closes, "high": closes, "low": closes,
        "close": closes, "volume": [1000] * 60,
    })
    monkeypatch.setattr(crypto_data, "get_ohlcv_crypto", lambda *a, **k: df)
    monkeypatch.setenv("VN_NO_CACHE", "1")
    ind = crypto_data.get_indicators_crypto("BTC")
    assert ind["symbol"] == "BTC"
    assert ind["close"] == 159.0  # USD, không ×1000
    assert ind["sma20"] is not None and ind["sma50"] is not None
    assert ind["close"] > ind["sma20"] > ind["sma50"]  # uptrend


def test_group_symbols_crypto(monkeypatch):
    monkeypatch.delenv("VN_CRYPTO_SYMBOLS", raising=False)
    assert crypto_data.get_group_symbols_crypto() == ["BTC", "ETH"]
    monkeypatch.setenv("VN_CRYPTO_SYMBOLS", "BTC,ETH,SOL")
    assert crypto_data.get_group_symbols_crypto() == ["BTC", "ETH", "SOL"]
