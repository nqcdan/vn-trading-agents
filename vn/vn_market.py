"""Quy tắc vi cấu trúc thị trường chứng khoán VN (HOSE/HNX/UPCOM)."""
from __future__ import annotations

# Biên độ dao động giá theo sàn (một phiên thường)
PRICE_LIMIT = {"HOSE": 0.07, "HNX": 0.10, "UPCOM": 0.15}

# Chi phí giao dịch (tỷ lệ trên giá trị khớp)
BUY_FEE = 0.0015        # phí mua ~0.15% (môi giới online phổ biến)
SELL_FEE = 0.0015       # phí bán ~0.15%
SELL_TAX = 0.001        # thuế TNCN 0.1% trên giá trị bán
SLIPPAGE = 0.001        # trượt giá giả định 0.1% mỗi chiều

LOT_SIZE = 100          # lô chẵn HOSE/HNX
SETTLE_DAYS = 2         # T+2: cổ/tiền về sau 2 phiên

DEFAULT_EXCHANGE = "HOSE"

_EXCHANGE_CACHE: dict[str, str] | None = None


def _load_exchange_map() -> dict[str, str]:
    global _EXCHANGE_CACHE
    if _EXCHANGE_CACHE is not None:
        return _EXCHANGE_CACHE
    mapping: dict[str, str] = {}
    try:
        import contextlib, io, os
        with contextlib.redirect_stdout(io.StringIO()):
            from vnstock.api.listing import Listing
            df = Listing().symbols_by_exchange()
        col = "exchange" if "exchange" in df.columns else "comGroupCode"
        sym = "symbol" if "symbol" in df.columns else "ticker"
        for _, row in df.iterrows():
            ex = str(row.get(col, "")).upper()
            if "HOSE" in ex or ex == "HSX":
                ex = "HOSE"
            elif "HNX" in ex:
                ex = "HNX"
            elif "UPCOM" in ex or "UPCOM" in ex:
                ex = "UPCOM"
            else:
                continue
            mapping[str(row.get(sym, "")).upper()] = ex
    except Exception:
        pass
    _EXCHANGE_CACHE = mapping
    return mapping


def detect_exchange(symbol: str) -> str:
    return _load_exchange_map().get(symbol.upper(), DEFAULT_EXCHANGE)


def price_limit(symbol: str) -> float:
    return PRICE_LIMIT[detect_exchange(symbol)]


def clamp_to_band(ref_price: float, target_price: float, symbol: str) -> float:
    """Kẹp giá khớp vào biên độ ± của phiên (mô phỏng trần/sàn)."""
    lim = price_limit(symbol)
    hi, lo = ref_price * (1 + lim), ref_price * (1 - lim)
    return max(lo, min(hi, target_price))


def round_lot(shares: float) -> int:
    return int(shares // LOT_SIZE) * LOT_SIZE


def buy_cost(price: float, shares: int) -> float:
    gross = price * (1 + SLIPPAGE) * shares
    return gross * (1 + BUY_FEE)


def sell_proceeds(price: float, shares: int) -> float:
    gross = price * (1 - SLIPPAGE) * shares
    return gross * (1 - SELL_FEE - SELL_TAX)
