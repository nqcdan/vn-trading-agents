"""Schema + parser hành động agent (BUY/SELL/HOLD) trích từ text LLM."""
from __future__ import annotations
import json
import re

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
