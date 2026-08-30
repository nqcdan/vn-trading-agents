"""Khuyến nghị danh mục: rank mã đang giữ + rổ thị trường → mua/bán/rotate.

Hai tầng:
  1. Sàng rule-based nhanh cả universe (technical + fundamental + P/B penalty).
  2. LLM-verify top ứng viên BUY (chống rule-based thổi phồng, vd VCB P/B đắt).

Nguồn danh mục: --holdings CLI, hoặc everyday API (portfolio.fetch_holdings).
"""
from __future__ import annotations
import time

from . import vn_data, portfolio as pf
from .agents import technical_analyst, fundamental_analyst, macro_mood, analyze, _llm_available

CONCENTRATION_CAP = 25.0  # % NAV: 1 mã vượt ngưỡng này → cờ giảm tỷ trọng
EXPENSIVE_PB = 3.0        # P/B > mức này → phạt điểm (bài học VCB: đúng chất, sai giá)


def _screen_one(sym: str, throttle: float) -> dict:
    """Chấm điểm 1 mã (rule-based, không LLM/news) với retry khi rate-limit."""
    for attempt in range(4):
        try:
            time.sleep(throttle)
            ind = vn_data.get_indicators(sym)
            fund = vn_data.get_fundamentals(sym)
            ta = technical_analyst(ind)
            fa = fundamental_analyst(fund)
            score = ta["score"] + fa["score"]
            pb = fund.get("pb")
            notes = list(ta["notes"]) + list(fa["notes"])
            if isinstance(pb, (int, float)) and pb > EXPENSIVE_PB:
                score -= 1
                notes.append(f"P/B {pb} đắt (>{EXPENSIVE_PB})")
            rsi = ind.get("rsi14")
            align = ("golden" if any("golden" in n for n in ta["notes"])
                     else "death" if any("death" in n for n in ta["notes"]) else "-")
            overbought = isinstance(rsi, (int, float)) and rsi >= 70
            return {
                "symbol": sym, "score": score, "signal": _signal(score, overbought),
                "align": align, "rsi": rsi, "pe": fund.get("pe"), "pb": pb,
                "roe": fund.get("roe"), "close": ind.get("close"),
                "technical": ta["signal"], "fundamental": fa["signal"],
                "notes": notes,
            }
        except BaseException as e:
            if "rate limit" in str(e).lower() and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            return {"symbol": sym, "error": f"{type(e).__name__}: {str(e)[:40]}"}


def _signal(score: int, overbought: bool) -> str:
    if score >= 2:
        return "BUY-WAIT" if overbought else "BUY"
    if score <= -2:
        return "SELL"
    return "HOLD"


def _action(row: dict, held: bool, weight: float | None) -> str:
    """Khuyến nghị theo bối cảnh danh mục."""
    if "error" in row:
        return "LỖI"
    sig = row["signal"]
    if held:
        if weight is not None and weight > CONCENTRATION_CAP:
            return "GIẢM TỶ TRỌNG (tập trung)"
        return {"BUY": "GOM THÊM", "BUY-WAIT": "GIỮ (chờ RSI hạ)",
                "HOLD": "GIỮ", "SELL": "BÁN/GIẢM"}[sig]
    return {"BUY": "MUA MỚI", "BUY-WAIT": "THEO DÕI (đang nóng)",
            "HOLD": "—", "SELL": "—"}[sig]


def _holdings(holdings_csv: str | None, asset_class: str,
              base: str | None, token: str | None) -> dict[str, float | None]:
    """→ {SYMBOL: weight_pct|None}. Ưu tiên CLI; không có thì gọi everyday."""
    if holdings_csv:
        out: dict[str, float | None] = {}
        for tok in holdings_csv.split(","):
            tok = tok.strip()
            if not tok:
                continue
            sym, _, w = tok.partition(":")
            try:
                out[sym.strip().upper()] = float(w) if w else None
            except ValueError:
                out[sym.strip().upper()] = None
        return out
    try:
        rows = pf.fetch_holdings(asset_class, base, token)
    except pf.PortfolioError:
        return {}
    total = sum(h.get("marketValue") or 0 for h in rows)
    out: dict[str, float | None] = {}
    for h in rows:
        sym = str(h.get("symbol", "")).upper()
        if sym:
            out[sym] = round((h.get("marketValue") or 0) / total * 100, 1) if total else None
    return out


def recommend(group: str = "VN30", holdings_csv: str | None = None,
              asset_class: str = "vn_stock", base: str | None = None, token: str | None = None,
              llm_top: int = 4, throttle: float = 2.2) -> dict:
    macro = macro_mood()
    held = _holdings(holdings_csv, asset_class, base, token)
    try:
        universe = vn_data.get_group_symbols(group)
    except BaseException:
        universe = []
    symbols = list(dict.fromkeys(list(held) + universe))  # giữ thứ tự, khử trùng

    rows, errors = [], []
    for sym in symbols:
        r = _screen_one(sym, throttle)
        if "error" in r:
            errors.append(f"{sym}: {r['error']}")
            continue
        r["held"] = sym in held
        r["weight_pct"] = held.get(sym)
        r["action"] = _action(r, r["held"], r["weight_pct"])
        rows.append(r)

    order = {"BUY": 0, "BUY-WAIT": 1, "HOLD": 2, "SELL": 3}
    rows.sort(key=lambda x: (order.get(x["signal"], 9), -x["score"], -(x["rsi"] or 0)))

    # LLM-verify: top ứng viên BUY (cả mã mới lẫn mã giữ đề xuất gom)
    verified = []
    if _llm_available() and llm_top > 0:
        buys = [r for r in rows if r["signal"] == "BUY"][:llm_top]
        for r in buys:
            try:
                time.sleep(throttle * 2)  # giãn nhịp cho quota vnstock hồi sau lượt screen
                a = analyze(r["symbol"])
                d = a["trader_decision"]
                r["llm_action"] = d.get("action")
                r["llm_conf"] = d.get("confidence")
                r["llm_reason"] = d.get("reason", "")[:200]
                r["llm_weight"] = a["risk"].get("target_weight")
                verified.append(r["symbol"])
            except BaseException as e:
                r["llm_action"] = f"ERR:{type(e).__name__}"

    return {
        "group": group, "n": len(rows), "held": held,
        "macro": {"signal": macro.get("signal"), "net": macro.get("net")},
        "llm_verified": verified, "errors": errors,
        "ranking": rows,
    }
