"""Schema + parser hành động agent (BUY/SELL/HOLD) trích từ text LLM."""
from __future__ import annotations
import json
import re

from .vn_market import LOT_SIZE

VALID_ACTIONS = {"BUY", "SELL", "HOLD"}

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def normalize(a: dict) -> dict:
    return {
        "action": str(a.get("action", "")).upper(),
        "symbol": str(a.get("symbol", "")).upper(),
        "lots": int(a.get("lots", 0)),
        "price": float(a.get("price", 0)),
        "reason": str(a.get("reason", "")),
    }


def _valid(a) -> bool:
    if not isinstance(a, dict):
        return False
    if str(a.get("action", "")).upper() not in VALID_ACTIONS:
        return False
    if not str(a.get("symbol", "")).strip():
        return False
    try:
        lots = int(a["lots"])
        price = float(a["price"])
    except (KeyError, ValueError, TypeError):
        return False
    return lots >= 0 and price >= 0


def reconcile_lots(acts: list[dict], budget: float | None) -> list[dict]:
    """LLM hay điền `lots` = số CỔ PHIẾU thay vì số LÔ (1 lô = 100 cp) → tiền ×100 sai.

    Guard budget-aware, model-agnostic: nếu tổng tiền tính-theo-lô vượt xa ngân sách
    nhưng tính-theo-cp lại vừa khít → suy ra LLM dùng đơn vị cổ phiếu; quy về lô
    (÷100, làm tròn xuống, tối thiểu 1). Model xuất đúng số lô → không kích, giữ nguyên.
    """
    if not budget or budget <= 0:
        return acts
    buys = [a for a in acts if a["action"] == "BUY" and a["price"] > 0 and a["lots"] > 0]
    if not buys:
        return acts
    lot_cost = sum(a["lots"] * 100 * a["price"] for a in buys)
    share_cost = sum(a["lots"] * a["price"] for a in buys)
    if not (lot_cost > budget * 1.2 and share_cost <= budget * 1.2):
        return acts
    out = []
    for a in acts:
        if a["action"] in ("BUY", "SELL") and a["lots"] >= 100:
            out.append({**a, "lots": max(1, a["lots"] // 100)})
        else:
            out.append(a)
    return out


def validate_actions(acts: list[dict], budget: float | None,
                     held_lots: dict | None = None) -> tuple[list[dict], list[str]]:
    """Chặn kế hoạch LLM vô lý (money path) bằng dữ liệu thật, model-agnostic:

    - BÁN vượt số lô đang giữ → cắt về số đang giữ (bỏ lệnh nếu giữ 0). Cần `held_lots`
      ({SYM: số lô đang giữ}); không có thì không chặn được (giữ nguyên).
    - Tổng MUA vượt (ngân sách + tiền bán thật vừa cắt) → cắt/loại lệnh mua thừa theo thứ tự.

    Trả (acts đã làm sạch, warnings) — warnings nổi bật trong báo cáo để người thấy đã can thiệp.
    """
    held_lots = held_lots or {}
    warnings: list[str] = []
    stage1: list[dict] = []
    sell_proceeds = 0.0
    for a in acts:
        if a["action"] == "SELL":
            sym = a["symbol"].upper()
            if sym in held_lots:
                cap = held_lots[sym]
                if a["lots"] > cap:
                    warnings.append(f"BÁN {sym}: {a['lots']} lô > đang giữ {cap} lô → cắt còn {cap}")
                    if cap <= 0:
                        continue
                    a = {**a, "lots": cap}
            sell_proceeds += a["lots"] * LOT_SIZE * a["price"]
        stage1.append(a)

    if not budget or budget <= 0:
        return stage1, warnings

    avail = budget + sell_proceeds
    spent = 0.0
    out: list[dict] = []
    for a in stage1:
        if a["action"] == "BUY" and a["price"] > 0 and a["lots"] > 0:
            cost = a["lots"] * LOT_SIZE * a["price"]
            if spent + cost > avail + 1:
                max_lots = int((avail - spent) // (LOT_SIZE * a["price"]))
                if max_lots <= 0:
                    warnings.append(f"MUA {a['symbol']}: {a['lots']} lô vượt ngân sách còn lại → loại")
                    continue
                warnings.append(f"MUA {a['symbol']}: {a['lots']} lô vượt ngân sách → cắt còn {max_lots}")
                a = {**a, "lots": max_lots}
                cost = max_lots * LOT_SIZE * a["price"]
            spent += cost
        out.append(a)
    return out, warnings


def parse_actions(text: str) -> list[dict]:
    if not text:
        return []
    blocks = _FENCE_RE.findall(text)
    if not blocks:
        return []
    for raw in reversed(blocks):
        try:
            data = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        if not isinstance(data, list):
            continue
        return [normalize(a) for a in data if _valid(a)]
    return []
