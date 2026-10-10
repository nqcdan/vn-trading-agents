"""TDD Stage 4 — crypto news & sentiment (lexicon EN, lọc per-coin)."""
from vn import crypto_news


_FEED = [
    {"title": "Bitcoin surges to record high on ETF inflow", "summary": "bullish institutional adoption"},
    {"title": "Ethereum upgrade boosts network", "summary": "ether rally"},
    {"title": "Crypto market crash: liquidation wipes billions", "summary": "bearish selloff fear"},
    {"title": "Some unrelated stock news", "summary": "nothing here"},
]


def test_filter_per_coin():
    btc = crypto_news.get_news_crypto("BTC", items=_FEED)
    assert len(btc) == 1 and "Bitcoin" in btc[0]["title"]
    eth = crypto_news.get_news_crypto("ETH", items=_FEED)
    assert len(eth) == 1 and "Ethereum" in eth[0]["title"]


def test_score_lexicon():
    assert crypto_news.score([_FEED[0]])["signal"] == "BULLISH"   # surge/record/inflow/bullish
    assert crypto_news.score([_FEED[2]])["signal"] == "BEARISH"   # crash/liquidation/bearish
    assert crypto_news.score([_FEED[3]])["signal"] == "NEUTRAL"


def test_sentiment_crypto_uses_market(monkeypatch):
    s = crypto_news.sentiment_crypto("BTC", market=_FEED)
    assert s["signal"] == "BULLISH" and s["n"] == 1
    assert s["headlines"] and "Bitcoin" in s["headlines"][0]


def test_sentiment_crypto_resilient(monkeypatch):
    def boom():
        raise RuntimeError("network down")
    monkeypatch.setattr(crypto_news, "fetch_market_crypto", boom)
    s = crypto_news.sentiment_crypto("BTC")   # không vỡ
    assert s["signal"] == "NEUTRAL" and s["n"] == 0
