"""TDD — paper-trade crypto (fractional, USD, book riêng), không đụng sổ cổ phiếu."""
import os

import pytest

from vn import paper, fx
from vn import portfolio as pf
from vn import crypto_data


@pytest.fixture(autouse=True)
def _tmp_book(tmp_path, monkeypatch):
    # book crypto → tmp; giá BTC/ETH cố định; holdings/cash mock; fx=1 để toán đơn vị
    monkeypatch.setattr(paper, "BOOK_PATH", str(tmp_path / "portfolio.json"))
    monkeypatch.setattr(fx, "usd_vnd", lambda: 1.0)
    monkeypatch.chdir(tmp_path)
    prices = {"BTC": 80000.0, "ETH": 2500.0}
    monkeypatch.setattr(crypto_data, "get_indicators_crypto",
                        lambda s, as_of=None: {"close": prices[s.upper()]})
    monkeypatch.setattr(pf, "fetch_holdings", lambda ac: [
        {"symbol": "BTC", "qty": 0.05, "costBasis": 3000.0, "marketValue": 4000.0}])
    monkeypatch.setattr(pf, "fetch_cash", lambda kinds: {"total": 10000, "kinds": ["bank"], "wallets": []})


def test_init_crypto_fractional():
    book = paper.init("crypto")
    assert os.path.exists(paper._book_path("crypto"))
    assert book["positions"]["BTC"]["qty"] == 0.05
    assert book["positions"]["BTC"]["avg_cost"] == pytest.approx(60000.0)  # 3000/0.05
    assert book["cash"] == 10000


def test_apply_buy_sell_fractional():
    paper.init("crypto")
    # mua 0.02 BTC @ 80000 = 1600 + phí; bán 0.01 ETH (chưa có → cảnh báo)
    r = paper.apply([{"action": "BUY", "symbol": "ETH", "qty": 0.1, "price": 2500.0}], "crypto")
    assert not r["warnings"]
    assert r["book"]["positions"]["ETH"]["qty"] == pytest.approx(0.1)
    # mua vượt tiền → tự giảm qty
    r2 = paper.apply([{"action": "BUY", "symbol": "BTC", "qty": 999, "price": 80000.0}], "crypto")
    assert any("thiếu tiền" in w for w in r2["warnings"])


def test_mark_and_score_crypto():
    paper.init("crypto")
    m = paper.mark(asset_class="crypto")
    # BTC 0.05 @ giá 80000 = 4000 USD + cash 10000
    assert m["market_value"] == pytest.approx(4000.0)
    assert m["nav"] == pytest.approx(14000.0)
    s = paper.score("crypto")
    assert "btc" in s and s["btc"] == 80000.0
    assert "vnindex" not in s


def test_stock_book_untouched(tmp_path):
    # sổ crypto nằm file riêng, không phải portfolio.json (sổ cổ phiếu)
    paper.init("crypto")
    assert paper._book_path("crypto").endswith("crypto.json")
    assert paper._book_path("vn_stock").endswith("portfolio.json")
    assert not os.path.exists(paper._book_path("vn_stock"))
