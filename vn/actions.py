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
