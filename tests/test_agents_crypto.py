"""TDD Stage 3 — pipeline agent asset-aware (crypto dùng chung analyst/trader/risk)."""
import pytest

from vn import agents, crypto_data


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setenv("VN_LLM_BACKEND", "off")  # ép rule-based, không spawn claude


def _ind(close, sma20, sma50, rsi):
    return {"symbol": "BTC", "as_of": "2026-10-10", "close": close, "sma20": sma20,
            "sma50": sma50, "rsi14": rsi, "ret20d_pct": 2.0, "vol20d_pct": 3.0, "avg_vol20": 1000}


def test_analyze_crypto_uses_crypto_data(monkeypatch):
    from vn import crypto_news
    monkeypatch.setattr(crypto_news, "fetch_market_crypto", lambda: [])  # sentiment/macro neutral, offline
    monkeypatch.setattr(crypto_data, "get_indicators_crypto",
                        lambda *a, **k: _ind(83000, 80000, 78000, 55.0))
    res = agents.analyze("BTC", asset_class="crypto")
    assert res["asset_class"] == "crypto"
    assert res["indicators"]["close"] == 83000
    # crypto không có cơ bản → fundamental neutral, score 0
    assert res["fundamental"]["score"] == 0
    assert res["fundamental"]["signal"] == "NEUTRAL"
    # uptrend + RSI thường → technical bullish → trader BUY (rule-based)
    assert res["technical"]["signal"] == "BULLISH"
    assert res["trader_decision"]["action"] == "BUY"
    # không có biên độ trần/sàn cho crypto
    assert res.get("price_limit_pct") is None


def test_analyze_vn_unchanged(monkeypatch):
    from vn import vn_data, vn_news
    monkeypatch.setattr(vn_data, "get_indicators", lambda *a, **k: _ind(50, 48, 45, 60.0))
    monkeypatch.setattr(vn_data, "get_fundamentals", lambda *a, **k: {"symbol": "FPT", "roe": 0.2, "pe": 10})
    monkeypatch.setattr(vn_news, "get_news", lambda *a, **k: [])
    monkeypatch.setattr(vn_news, "fetch_market", lambda *a, **k: [])
    res = agents.analyze("FPT")  # default vn_stock
    assert res["asset_class"] == "vn_stock"
    assert res["exchange"]  # vẫn có sàn
    assert res["fundamental"]["score"] >= 1  # ROE tốt + PE rẻ


def test_trader_rules_from_profile(monkeypatch):
    # rule-based: tổng điểm quyết định hành động, bất kể asset
    ta = {"signal": "BEARISH", "score": -2, "notes": []}
    fa = {"signal": "NEUTRAL", "score": 0, "notes": []}
    d = agents.trader("BTC", ta, fa, {"bull": "", "bear": ""}, None,
                      profile=__import__("vn.market_profile", fromlist=["get"]).get("crypto"))
    assert d["action"] == "SELL"
