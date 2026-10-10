"""TDD Stage 5 — lệnh crypto (orchestrator + render), portfolio mock."""
from vn import crypto_cmd, agents, crypto_data, market_refs
from vn import portfolio as pf


def _fake_analysis(sym, action, signal, close, rsi):
    return {
        "symbol": sym, "asset_class": "crypto", "exchange": None, "price_limit_pct": None,
        "indicators": {"symbol": sym, "close": close, "sma20": close * 0.98, "sma50": close * 0.95,
                       "rsi14": rsi, "ret20d_pct": 3.0, "vol20d_pct": 2.5, "avg_vol20": 1000},
        "fundamentals": {"note": "crypto"}, "technical": {"signal": signal, "score": 2, "notes": ["uptrend"]},
        "fundamental": {"signal": "NEUTRAL", "score": 0, "notes": []},
        "sentiment": {"signal": "NEUTRAL", "score": 0}, "macro": {"signal": "NEUTRAL", "net": 0},
        "debate": {"bull": "", "bear": ""},
        "trader_decision": {"action": action, "confidence": 0.6, "reason": "rule-based"},
        "risk": {"approved_action": action, "target_weight": 0.1, "note": "vol ok"}, "llm": False,
    }


def test_run_crypto_with_holdings(monkeypatch):
    monkeypatch.setattr(crypto_data, "get_group_symbols_crypto", lambda: ["BTC", "ETH"])
    monkeypatch.setattr(agents, "analyze",
                        lambda s, as_of=None, asset_class="crypto":
                        _fake_analysis(s, "BUY" if s == "BTC" else "HOLD",
                                       "BULLISH", 83000 if s == "BTC" else 2500, 55))
    monkeypatch.setattr(pf, "fetch_holdings", lambda ac: [
        {"symbol": "BTC", "qty": 0.1, "costBasis": 8000, "marketValue": 8300, "pnlPct": 3.7}])
    monkeypatch.setattr(pf, "fetch_cash", lambda kinds: {"total": 27589754, "kinds": ["bank"], "wallets": []})
    monkeypatch.setattr(market_refs, "crypto_usd", lambda: "BTC $83,000 · ETH $2,500")

    res = crypto_cmd.run_crypto()
    assert res["symbols"] == ["BTC", "ETH"]
    assert res["budget"] == 27589754
    assert res["analyses"][0]["held_qty"] == 0.1   # BTC đang giữ
    assert res["analyses"][1]["held_qty"] is None

    md = crypto_cmd.render_crypto(res, "2026-10-11")
    assert "BÁO CÁO CRYPTO 2026-10-11" in md
    assert "Giá tham chiếu" in md and "BTC $83,000" in md
    assert "Danh mục crypto hiện tại" in md
    assert "BTC ◆" in md          # mã đang giữ có dấu ◆
    assert "BUY" in md and "HOLD" in md


def test_run_crypto_everyday_down(monkeypatch):
    monkeypatch.setattr(crypto_data, "get_group_symbols_crypto", lambda: ["BTC"])
    monkeypatch.setattr(agents, "analyze",
                        lambda s, as_of=None, asset_class="crypto": _fake_analysis(s, "BUY", "BULLISH", 83000, 55))

    def boom(*a, **k):
        raise pf.PortfolioError("everyday down")
    monkeypatch.setattr(pf, "fetch_holdings", boom)
    monkeypatch.setattr(pf, "fetch_cash", boom)
    monkeypatch.setattr(market_refs, "crypto_usd", lambda: "BTC $83,000")

    res = crypto_cmd.run_crypto()        # không vỡ khi everyday chết
    assert res["holdings"] is None and res["budget"] is None
    md = crypto_cmd.render_crypto(res, "2026-10-11")
    assert "BÁO CÁO CRYPTO" in md
