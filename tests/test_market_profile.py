"""TDD Stage 2 — market profile (VN stock vs crypto)."""
import pytest

from vn import market_profile as mp
from vn import vn_market


def test_get_profiles():
    assert mp.get("vn_stock").asset_class == "vn_stock"
    assert mp.get("crypto").asset_class == "crypto"
    with pytest.raises(KeyError):
        mp.get("forex")


def test_vn_profile_matches_vn_market():
    p = mp.get("vn_stock")
    assert p.lot_size == vn_market.LOT_SIZE == 100
    assert p.settle_days == vn_market.SETTLE_DAYS == 2
    assert p.sell_tax == vn_market.SELL_TAX
    assert p.allow_fractional is False
    assert p.is_24_7 is False
    assert p.price_unit == "vnd_thousand"


def test_crypto_profile_params():
    p = mp.get("crypto")
    assert p.lot_size == 1
    assert p.allow_fractional is True
    assert p.settle_days == 0
    assert p.sell_tax == 0.0
    assert p.is_24_7 is True
    assert p.allow_short is False
    assert p.price_unit == "usd"
    assert p.price_limit is None
    assert "24/7" in p.rules_text
    assert "crypto" in p.system_prompt.lower()


def test_round_qty():
    assert mp.round_qty(mp.get("vn_stock"), 350) == 300      # bội 100
    assert mp.round_qty(mp.get("crypto"), 0.12345678) == pytest.approx(0.12345678)


def test_cost_helpers_crypto_no_tax():
    p = mp.get("crypto")
    # phí mua = gross*(1+slippage)*(1+fee), không thuế
    cost = mp.buy_cost(p, price=100.0, qty=2.0)
    assert cost == pytest.approx(100.0 * (1 + p.slippage) * 2.0 * (1 + p.buy_fee))
    proceeds = mp.sell_proceeds(p, price=100.0, qty=2.0)
    assert proceeds == pytest.approx(100.0 * (1 - p.slippage) * 2.0 * (1 - p.sell_fee))
