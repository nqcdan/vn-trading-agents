import pandas as pd

from vn import scorecard

MD = """# BÁO CÁO NGÀY 2026-09-07 · rổ VN30

**Nguồn:** tcbs-mcp · **Ngân sách:** 27,6tr

## 3. Quyết định & giải ngân
**▶ QUYẾT ĐỊNH ĐỢT NÀY: ...**

| Mã       | Hành động |  Lô | Giá LO |   Tiền |  % NS | Tín hiệu / Lý do |
| :------- | :-------- | --: | -----: | -----: | ----: | :--------------- |
| MCH      | MUA MỚI   |   1 | 143,000 | 14,3tr | 51.8% | lý do |
| HPG ◆9%  | GOM THÊM  |   4 | 20,100 |  8,0tr | 29.1% | lý do |
| HDB ◆14% | GIỮ       |   — |      — |      — |     — | RSI 69 |
| VNM ◆3%  | BÁN       |   1 | 57,700 |  5,8tr | 20.9% | lý do |

## 5. Xếp hạng cả rổ (rule-based)
| Mã       | Tín hiệu |     Giá | RSI |  P/E |  P/B | ROE | Khuyến nghị |
| :------- | :------- | ------: | --: | ---: | ---: | --: | :---------- |
| HPG ◆9%  | BUY      |  20,000 |  50 |  8.2 |  1.7 | 24% | GOM THÊM    |
"""


def test_parse_report_section3_and_prices():
    r = scorecard.parse_report(MD)
    assert r["mode"] == "tcbs-mcp" and r["budget"] == "27,6tr"
    assert r["actions"] == [
        {"action": "BUY", "symbol": "MCH", "lots": 1, "price": 143000.0},
        {"action": "BUY", "symbol": "HPG", "lots": 4, "price": 20100.0},
        {"action": "SELL", "symbol": "VNM", "lots": 1, "price": 57700.0}]
    assert r["ranking"] == [{"symbol": "HPG", "signal": "BUY", "close": 20.0}]


def test_decisions_lo_fill_and_pnl(monkeypatch):
    from vn import vn_market
    monkeypatch.setattr(vn_market, "detect_exchange", lambda s: "HOSE")
    idx = pd.to_datetime(["2026-09-08", "2026-09-09"])
    df = pd.DataFrame({"open": [20.5, 21], "high": [21, 22], "low": [19.8, 20.5], "close": [20.2, 22.0]}, index=idx)
    journals = {"2026-09-07": {"ranking": [], "actions": [
        {"action": "BUY", "symbol": "HPG", "lots": 1, "price": 20000.0},
        {"action": "BUY", "symbol": "HPG", "lots": 1, "price": 19500.0},
        {"action": "SELL", "symbol": "HPG", "lots": 1, "price": 20800.0}]}}
    rows = scorecard.decisions(journals, {"HPG": df}, idx)
    assert rows[0]["state"] == "khop" and rows[0]["fill"] == 20000.0 and rows[0]["pnl"] > 0
    assert rows[1]["filled"] is False
    assert rows[2]["state"] == "khop" and rows[2]["fill"] == 20800.0 and rows[2]["pnl"] < 0


def test_decisions_touch_and_band(monkeypatch):
    from vn import vn_market
    monkeypatch.setattr(vn_market, "detect_exchange", lambda s: "HOSE")
    idx = pd.to_datetime(["2026-09-07", "2026-09-08"])
    df = pd.DataFrame({"open": [20, 20.5], "high": [20, 21], "low": [20, 20.0], "close": [20, 20.5]}, index=idx)
    journals = {"2026-09-07": {"ranking": [{"symbol": "HPG", "close": 20.0}], "actions": [
        {"action": "BUY", "symbol": "HPG", "lots": 1, "price": 20000.0},
        {"action": "BUY", "symbol": "HPG", "lots": 1, "price": 18000.0}]}}
    rows = scorecard.decisions(journals, {"HPG": df}, idx)
    assert rows[0]["state"] == "cham" and rows[0]["filled"]
    assert rows[1]["state"] == "band" and not rows[1]["filled"]


def test_health_flags_fallback_and_frozen_budget():
    j = {"2026-09-08": {"mode": "tcbs-mcp", "budget": "100tr"},
         "2026-09-09": {"mode": "fallback-mcp-offline", "budget": "50tr"},
         "2026-09-10": {"mode": "tcbs-mcp", "budget": "50tr"}}
    h = scorecard.health(j)
    assert h["fallback"] == ["2026-09-09"]
    assert h["budget_unchanged_since"] == "2026-09-09"


def test_load_journals_reads_md_skips_weekend(tmp_path):
    for day in ("2026-10-09", "2026-10-11"):
        (tmp_path / f"{day}-daily.md").write_text(MD)
    (tmp_path / "2026-10-09-daily.json").write_text("{}")
    assert list(scorecard.load_journals(root=str(tmp_path))) == ["2026-10-09"]


def test_tick_and_lots():
    from vn import vn_market as m
    assert m.round_tick(21538, "HOSE", "BUY") == 21500
    assert m.round_tick(21538, "HOSE", "SELL") == 21550
    assert m.round_tick(74401, "HOSE", "SELL") == 74500
    assert m.round_tick(9995, "HOSE", "BUY") == 9990
    assert m.round_tick(12345, "HNX", "BUY") == 12300
    assert m.split_lots(1360) == (13, 60)
