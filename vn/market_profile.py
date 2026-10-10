"""Market profile — trừu tượng hoá vi cấu trúc theo asset_class (vn_stock vs crypto).

Gom mọi hằng số/quy tắc đặc thù thị trường vào 1 chỗ để pipeline agent + paper + advise
chạy chung code, chỉ đổi profile. VN giữ y hệt `vn_market.py` (không đổi hành vi cũ).
"""
from __future__ import annotations
import textwrap
from dataclasses import dataclass

from . import vn_market

_VN_RULES = textwrap.dedent(
    """
    RÀNG BUỘC THỊ TRƯỜNG VN (bắt buộc tuân thủ khi khuyến nghị):
    - Biên độ giá/phiên: HOSE ±7%, HNX ±10%, UPCOM ±15%. Không kỳ vọng biến động vượt biên.
    - T+2: cổ/tiền về sau ~2 phiên. KHÔNG lướt sóng trong ngày (không mua-bán cùng mã 1 phiên).
    - Retail KHÔNG bán khống. Khuyến nghị "bearish" = BÁN hoặc ĐỨNG NGOÀI, không phải mở short.
    - Lô 100, thanh khoản midcap có thể mỏng → cân nhắc slippage.
    """
).strip()

_CRYPTO_RULES = textwrap.dedent(
    """
    RÀNG BUỘC THỊ TRƯỜNG CRYPTO (bắt buộc tuân thủ khi khuyến nghị):
    - Giao dịch 24/7, không biên độ trần/sàn, biến động mạnh — quản rủi ro bằng tỷ trọng, không all-in.
    - Thanh toán tức thì (T+0), mua lẻ được (fractional), không có "lô 100"; lệnh tối thiểu ~$10.
    - KHÔNG margin/đòn bẩy, KHÔNG short (giữ khẩu vị thận trọng). "Bearish" = BÁN hoặc ĐỨNG NGOÀI.
    - Không có P/E/ROE — đánh giá dựa kỹ thuật (xu hướng, RSI, SMA) + dòng tiền/tin tức; coi chừng tin giả.
    - Phí ~0.1%/chiều, không thuế; trượt giá theo thanh khoản.
    """
).strip()


@dataclass(frozen=True)
class Profile:
    asset_class: str
    name: str
    lot_size: int
    allow_fractional: bool
    settle_days: int
    buy_fee: float
    sell_fee: float
    sell_tax: float
    slippage: float
    price_limit: dict | None
    allow_short: bool
    is_24_7: bool
    price_unit: str      # "vnd_thousand" | "usd"
    rules_text: str
    system_prompt: str


VN = Profile(
    asset_class="vn_stock", name="Chứng khoán VN (HOSE/HNX/UPCOM)",
    lot_size=vn_market.LOT_SIZE, allow_fractional=False, settle_days=vn_market.SETTLE_DAYS,
    buy_fee=vn_market.BUY_FEE, sell_fee=vn_market.SELL_FEE, sell_tax=vn_market.SELL_TAX,
    slippage=vn_market.SLIPPAGE, price_limit=dict(vn_market.PRICE_LIMIT),
    allow_short=False, is_24_7=False, price_unit="vnd_thousand",
    rules_text=_VN_RULES,
    system_prompt="Bạn là chuyên gia phân tích chứng khoán VN. Trả lời tiếng Việt, ngắn gọn.",
)

CRYPTO = Profile(
    asset_class="crypto", name="Crypto (BTC/ETH…)",
    lot_size=1, allow_fractional=True, settle_days=0,
    buy_fee=0.001, sell_fee=0.001, sell_tax=0.0, slippage=0.001,
    price_limit=None, allow_short=False, is_24_7=True, price_unit="usd",
    rules_text=_CRYPTO_RULES,
    system_prompt="Bạn là chuyên gia phân tích thị trường crypto (BTC/ETH…). Trả lời tiếng Việt, ngắn gọn.",
)

_PROFILES = {"vn_stock": VN, "crypto": CRYPTO}


def get(asset_class: str) -> Profile:
    return _PROFILES[asset_class]


def round_qty(p: Profile, qty: float) -> float:
    if p.allow_fractional:
        return float(qty)
    return int(qty // p.lot_size) * p.lot_size


def buy_cost(p: Profile, price: float, qty: float) -> float:
    gross = price * (1 + p.slippage) * qty
    return gross * (1 + p.buy_fee)


def sell_proceeds(p: Profile, price: float, qty: float) -> float:
    gross = price * (1 - p.slippage) * qty
    return gross * (1 - p.sell_fee - p.sell_tax)
