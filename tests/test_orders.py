from vn import decision_table as dt, vn_market


def test_split_orders_ticks_cash_and_odd_lot(monkeypatch):
    monkeypatch.setattr(vn_market, "detect_exchange", lambda s: "HOSE")
    res = {"budget": 10_000_000, "actions": [
        {"action": "BUY", "symbol": "HPG", "lots": 3, "price": 20_120.0},
        {"action": "SELL", "symbol": "FPT", "lots": 13, "price": 57_130.0}]}
    rows = dt._order_rows(res["actions"], [{"symbol": "FPT", "qty": 1360}])
    assert [(r["side"], r["sym"], r["qty"], r["price"]) for r in rows] == [
        ("SELL", "FPT", 700, 57_200.0),
        ("BUY", "HPG", 200, 20_100.0),
        ("SELL", "FPT", 600, 58_100.0),
        ("SELL", "FPT", 60, 57_200.0),
        ("BUY", "HPG", 100, 19_750.0)]
    md = dt.render_orders(res, [{"symbol": "FPT", "qty": 1360}])
    assert "Bảng lô lẻ" in md and "⚠" not in md


def test_orders_flag_cash_shortfall(monkeypatch):
    monkeypatch.setattr(vn_market, "detect_exchange", lambda s: "HOSE")
    res = {"budget": 1_000_000, "actions": [{"action": "BUY", "symbol": "HPG", "lots": 1, "price": 20_000.0}]}
    assert "⚠" in dt.render_orders(res)
