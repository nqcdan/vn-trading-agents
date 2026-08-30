"""Sổ paper-trade forward + scorecard 3 đường (agent / giữ nguyên / VNINDEX)."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone

from . import vn_data, vn_market
from . import portfolio as pf

BOOK_PATH = os.path.join("reports", "paper", "portfolio.json")


class PaperError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    if not os.path.exists(BOOK_PATH):
        raise PaperError(f"chưa có sổ paper ở {BOOK_PATH} — chạy paper init trước")
    with open(BOOK_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(book: dict) -> dict:
    os.makedirs(os.path.dirname(BOOK_PATH), exist_ok=True)
    with open(BOOK_PATH, "w", encoding="utf-8") as f:
        json.dump(book, f, ensure_ascii=False, indent=2)
    return book


def _price_vnd(symbol: str, as_of: str | None = None) -> float | None:
    """Giá 1 cp theo VND. vn_data.close ở đơn vị nghìn đồng → ×1000."""
    try:
        ind = vn_data.get_indicators(symbol, as_of=as_of)
    except BaseException:
        return None
    close = ind.get("close")
    if not isinstance(close, (int, float)):
        return None
    return float(close) * 1000.0


def init(asset_class: str = "vn_stock", seed_cash: float | None = None) -> dict:
    if os.path.exists(BOOK_PATH):
        raise PaperError(f"sổ paper đã tồn tại ở {BOOK_PATH} — xoá tay nếu muốn init lại")

    snap = pf.analyze_portfolio(asset_class)
    positions: dict[str, dict] = {}
    for p in snap.get("positions", []):
        sym = str(p.get("symbol", "")).upper()
        if not sym:
            continue
        qty = p.get("qty")
        cost = p.get("cost_basis")
        mv = p.get("market_value")
        px = None
        an = p.get("analysis") or {}
        if isinstance(an.get("close"), (int, float)):
            px = float(an["close"]) * 1000.0
        # avg_cost: ưu tiên cost thật; nếu không có → ước từ market_value/qty;
        # nếu không có qty → ước qty từ market_value/giá rồi lấy giá làm avg_cost.
        if qty and cost:
            avg_cost = float(cost) / float(qty)
        elif qty and mv:
            avg_cost = float(mv) / float(qty)
        elif mv and px:
            qty = int(round(float(mv) / px))
            avg_cost = px
        else:
            continue
        if not qty:
            continue
        positions[sym] = {"qty": int(qty), "avg_cost": round(float(avg_cost), 4)}

    if seed_cash is not None:
        cash = float(seed_cash)
    else:
        try:
            cash = float(pf.fetch_cash(("bank",)).get("total", 0))
        except Exception:
            cash = 0.0

    book = {
        "created": _now(),
        "cash": cash,
        "positions": positions,
        "trades": [],
        "cash_injections": [],
        "init_snapshot": {
            "cash": cash,
            "positions": {s: dict(v) for s, v in positions.items()},
        },
    }
    return _save(book)


def inject_cash(amount: float) -> dict:
    book = _load()
    amount = float(amount)
    book["cash"] = float(book["cash"]) + amount
    book["cash_injections"] = list(book.get("cash_injections", [])) + [
        {"ts": _now(), "amount": amount}
    ]
    return _save(book)


def apply(acts: list[dict]) -> dict:
    book = _load()
    cash = float(book["cash"])
    positions = {s: dict(v) for s, v in book.get("positions", {}).items()}
    trades = list(book.get("trades", []))
    warnings: list[str] = []

    for a in acts:
        action = str(a.get("action", "")).upper()
        sym = str(a.get("symbol", "")).upper()
        lots = int(a.get("lots", 0))
        price = float(a.get("price", 0))
        if action == "HOLD" or lots <= 0 or price <= 0 or not sym:
            continue

        if action == "BUY":
            shares = lots * vn_market.LOT_SIZE
            cost = vn_market.buy_cost(price, shares)
            if cost > cash:
                # giảm lots vừa túi
                afford_lots = 0
                while afford_lots + 1 <= lots and vn_market.buy_cost(
                    price, (afford_lots + 1) * vn_market.LOT_SIZE
                ) <= cash:
                    afford_lots += 1
                if afford_lots < lots:
                    warnings.append(
                        f"{sym}: thiếu tiền, giảm {lots}→{afford_lots} lô"
                    )
                lots = afford_lots
                if lots <= 0:
                    continue
                shares = lots * vn_market.LOT_SIZE
                cost = vn_market.buy_cost(price, shares)
            fee = cost - price * shares
            cash -= cost
            pos = positions.get(sym, {"qty": 0, "avg_cost": 0.0})
            old_qty = int(pos["qty"])
            new_qty = old_qty + shares
            new_avg = (old_qty * float(pos["avg_cost"]) + shares * price) / new_qty
            positions[sym] = {"qty": new_qty, "avg_cost": round(new_avg, 4)}
            trades.append({
                "ts": _now(), "action": "BUY", "symbol": sym, "qty": shares,
                "price": price, "fee": round(fee, 2), "tax": 0.0,
                "cash_after": round(cash, 2),
            })

        elif action == "SELL":
            pos = positions.get(sym)
            held = int(pos["qty"]) if pos else 0
            if held <= 0:
                warnings.append(f"{sym}: không có vị thế để bán")
                continue
            shares = min(lots * vn_market.LOT_SIZE, held)
            if shares < lots * vn_market.LOT_SIZE:
                warnings.append(
                    f"{sym}: chỉ có {held} cp, bán {shares} thay vì {lots * vn_market.LOT_SIZE}"
                )
            proceeds = vn_market.sell_proceeds(price, shares)
            gross = price * shares
            charges = gross - proceeds  # phí bán + thuế + slippage
            fee = gross * vn_market.SELL_FEE
            tax = gross * vn_market.SELL_TAX
            cash += proceeds
            rem = held - shares
            if rem <= 0:
                positions.pop(sym, None)
            else:
                positions[sym] = {"qty": rem, "avg_cost": pos["avg_cost"]}
            trades.append({
                "ts": _now(), "action": "SELL", "symbol": sym, "qty": shares,
                "price": price, "fee": round(fee, 2), "tax": round(tax, 2),
                "cash_after": round(cash, 2), "charges": round(charges, 2),
            })

    book["cash"] = round(cash, 2)
    book["positions"] = positions
    book["trades"] = trades
    _save(book)
    return {"book": book, "warnings": warnings}


def _mark_positions(positions: dict, cash: float, as_of: str | None = None) -> dict:
    marked = []
    notes = []
    mv_total = 0.0
    for sym, pos in positions.items():
        px = _price_vnd(sym, as_of)
        if px is None:
            notes.append(f"{sym}: không lấy được giá, bỏ khỏi mark")
            continue
        qty = int(pos["qty"])
        avg = float(pos["avg_cost"])
        mv = px * qty
        mv_total += mv
        marked.append({
            "symbol": sym, "qty": qty, "avg_cost": round(avg, 4),
            "price": round(px, 2), "market_value": round(mv, 2),
            "unrealized_pnl": round((px - avg) * qty, 2),
        })
    nav = cash + mv_total
    return {
        "cash": round(cash, 2), "positions": marked,
        "market_value": round(mv_total, 2), "nav": round(nav, 2),
        "notes": notes,
    }


def mark(as_of: str | None = None) -> dict:
    book = _load()
    return _mark_positions(book.get("positions", {}), float(book["cash"]), as_of)


def score() -> dict:
    book = _load()
    trades = book.get("trades", [])
    injections = book.get("cash_injections", [])
    total_injected = sum(float(i.get("amount", 0)) for i in injections)

    agent = _mark_positions(book.get("positions", {}), float(book["cash"]))

    snap = book.get("init_snapshot", {})
    hold_cash = float(snap.get("cash", 0)) + total_injected
    hold = _mark_positions(snap.get("positions", {}), hold_cash)

    fees = sum(float(t.get("fee", 0)) + float(t.get("tax", 0)) for t in trades)

    out = {
        "agent_nav": agent["nav"],
        "agent": agent,
        "hold_nav": hold["nav"],
        "hold": hold,
        "total_fees_tax": round(fees, 2),
        "turnover_trades": len(trades),
        "cash_now": round(float(book["cash"]), 2),
        "cash_injected": round(total_injected, 2),
        "notes": list(agent["notes"]) + list(hold["notes"]),
    }

    vnindex_px = _price_vnd("VNINDEX")
    if vnindex_px is None:
        try:
            ind = vn_data.get_indicators("VNINDEX")
            c = ind.get("close")
            vnindex_px = float(c) if isinstance(c, (int, float)) else None
        except BaseException:
            vnindex_px = None
    if vnindex_px is None:
        out["notes"].append("không lấy được VNINDEX")
    else:
        out["vnindex"] = round(vnindex_px, 2)

    return out
