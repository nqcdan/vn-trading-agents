from vn import snapshot


def _snap(date, qty_fpt, px_fpt, cash):
    pos = [{"symbol": "FPT", "qty": qty_fpt, "price": px_fpt, "value": qty_fpt * px_fpt}]
    sv = sum(p["value"] for p in pos)
    return {"date": date, "positions": pos, "stock_value": sv, "cash": cash, "total": sv + cash}


def test_diff_detects_trade_and_matches_plan():
    prev = _snap("2026-10-12", 1300, 57000, 10_000_000)
    now = _snap("2026-10-13", 1400, 58000, 4_200_000)
    acts = [{"action": "BUY", "symbol": "FPT", "lots": 1, "price": 57500.0},
            {"action": "SELL", "symbol": "VNM", "lots": 1, "price": 57700.0}]
    d = snapshot.diff(now, prev, acts)
    assert d["trades"] == [{"symbol": "FPT", "side": "BUY", "qty": 100, "planned_lots": 1, "planned_price": 57500.0}]
    assert d["skipped"] == [{"symbol": "VNM", "side": "SELL", "lots": 1, "price": 57700.0}]
    assert d["price_pnl"] == 0


def test_diff_price_pnl_when_qty_unchanged():
    d = snapshot.diff(_snap("b", 100, 60000, 0), _snap("a", 100, 57000, 0), [])
    assert d["price_pnl"] == 300_000 and d["trades"] == []


def test_render_parse_roundtrip():
    snap = {"date": "2026-10-12", "as_of": "2026-10-12", "stock_value": 5_710_000, "stock_cost": 6_000_000,
            "cash": 1_000_000, "crypto_value": 0, "crypto": [], "total": 6_710_000,
            "positions": [{"symbol": "FPT", "qty": 100, "lots": 1, "odd": 0, "avg_cost": 60000, "price": 57100,
                           "value": 5_710_000, "cost": 6_000_000, "pnl": -290_000, "weight": 100.0}]}
    back = snapshot.parse(snapshot.render(snap, {}, None))
    assert back["positions"] == [{"symbol": "FPT", "qty": 100, "price": 57100.0}]
    assert back["total"] == 6_710_000 and back["cash"] == 1_000_000
