"""Máy quét sự kiện cuối phiên (EOD): quét danh mục + ví bank realtime từ everyday,
CHỈ báo khi có việc, và khi có việc thì đề xuất hành động (bán/rotate/giải ngân).

Nguồn sự thật = everyday (holdings + số dư ví), agent stateless fetch realtime. Không
lịch, không hardcode ngân sách — ngân sách mua = số dư ví bank realtime.

GUARD chống churn (cốt lõi): chỉ đề xuất rotate khi lợi thế mã mới vượt rõ chi phí vòng
lặp round-trip (~0.5%: phí 0.15%×2 + thuế bán 0.1% + slippage ~0.1%) và bù thời gian chết
T+2. Nhúng nhẹ / lợi thế mỏng → GIỮ NGUYÊN. Bài học invariant backtest: whipsaw + phí ăn
mòn alpha.

TODO: tin xấu mới per-symbol (vn_news) hiện chỉ dùng cho mã đã bị trigger kỹ thuật để
tránh gọi RSS cả rổ; có thể mở rộng quét news như một trigger độc lập nếu chấp nhận chi phí.
"""
from __future__ import annotations

from . import portfolio as pf, recommend as rec, vn_data, vn_news
from .agents import _llm, _llm_available, _DEFAULT_SYS
from .profile import profile_system
from . import tcbs

ROUND_TRIP_COST_PCT = 0.5  # phí+thuế+slippage vòng round-trip → ngưỡng guard rotate
LOT = 100
PRICE_UNIT_VND = 1000      # giá vnstock đơn vị nghìn đồng → ×1000 ra VND
MAX_CANDIDATES = 6         # số ứng viên rotate/giải ngân đưa vào prompt


def _close(symbol: str) -> float | None:
    try:
        c = vn_data.get_indicators(symbol).get("close")
        return c if isinstance(c, (int, float)) else None
    except BaseException:
        return None


def _positions(asset_class: str, holdings_csv: str | None, throttle: float) -> tuple[list[dict], str | None]:
    """→ (positions, note). Mỗi position: {symbol, weight_pct, analysis:{...}, ...}."""
    if holdings_csv:
        held = rec._holdings(holdings_csv, asset_class, None, None)
        out = []
        for sym, w in held.items():
            r = rec._screen_one(sym, throttle)
            out.append({
                "symbol": sym, "weight_pct": w, "market_value": None,
                "pnl_pct": None, "close": None,
                "analysis": {
                    "signal": r.get("signal"), "rsi14": r.get("rsi"),
                    "pb": r.get("pb"), "pe": r.get("pe"), "roe": r.get("roe"),
                    "overbought": isinstance(r.get("rsi"), (int, float)) and r["rsi"] >= 70,
                    "error": r.get("error"),
                },
            })
        return out, "danh mục từ --holdings (không có tỷ trọng NAV thật nếu thiếu số)"
    data = pf.analyze_portfolio(asset_class)
    out = []
    for p in data.get("positions", []):
        a = p.get("analysis", {})
        out.append({
            "symbol": p["symbol"], "weight_pct": p.get("weight_pct"),
            "market_value": p.get("market_value"), "pnl_pct": p.get("pnl_pct"),
            "close": a.get("close"),
            "analysis": a,
        })
    return out, None


def _sma50_break(symbol: str) -> tuple[bool, float | None, float | None]:
    """close < sma50 → thủng. Trả (broke, close, sma50); im lặng nếu không lấy được."""
    try:
        ind = vn_data.get_indicators(symbol)
    except BaseException:
        return False, None, None
    close, sma50 = ind.get("close"), ind.get("sma50")
    if isinstance(close, (int, float)) and isinstance(sma50, (int, float)):
        return close < sma50, close, sma50
    return False, close if isinstance(close, (int, float)) else None, None


def _bad_news(symbol: str) -> str | None:
    """Tin xấu mới per-symbol (chỉ gọi cho mã đã trigger kỹ thuật → rẻ)."""
    try:
        items = vn_news.get_news(symbol, limit=8)
        s = vn_news.score_sentiment(items)
    except BaseException:
        return None
    if s.get("signal") == "BEARISH":
        return f"tin xấu mới (net {s.get('net')}, {s.get('n')} tin)"
    return None


def _scan_triggers(positions: list[dict], throttle: float) -> list[dict]:
    """Quét trigger rule-based (không LLM). Trả [{symbol, reasons:[...]}]."""
    triggers = []
    for p in positions:
        sym = p["symbol"]
        a = p.get("analysis", {})
        reasons: list[str] = []
        rsi = a.get("rsi14")
        if isinstance(rsi, (int, float)) and rsi >= 70:
            reasons.append(f"RSI {rsi} ≥ 70 (quá mua → cân nhắc chốt lời)")
        w = p.get("weight_pct")
        if isinstance(w, (int, float)) and w > rec.CONCENTRATION_CAP:
            reasons.append(f"tỷ trọng {w}% > {rec.CONCENTRATION_CAP}% NAV (tập trung)")
        if a.get("signal") == "SELL":
            reasons.append("tín hiệu rule-based = SELL")
        broke, close, sma50 = _sma50_break(sym)
        if broke:
            reasons.append(f"thủng SMA50 (close {close} < sma50 {sma50})")
        if reasons:  # chỉ gọi news cho mã đã trigger → rẻ
            bn = _bad_news(sym)
            if bn:
                reasons.append(bn)
            triggers.append({"symbol": sym, "reasons": reasons})
    return triggers


def _candidates(held_syms: set[str], group: str, extra: list[str] | None, throttle: float) -> list[dict]:
    """Ứng viên rotate/giải ngân: rule-based BUY trong group ∪ extra, chưa nắm giữ."""
    try:
        universe = vn_data.get_group_symbols(group)
    except BaseException:
        universe = []
    pool = list(dict.fromkeys(universe + list(extra or [])))
    rows = []
    for sym in pool:
        if sym.upper() in held_syms:
            continue
        r = rec._screen_one(sym, throttle)
        if "error" in r or r.get("signal") not in ("BUY", "BUY-WAIT"):
            continue
        rows.append({"symbol": sym, "signal": r["signal"], "score": r.get("score"),
                     "rsi": r.get("rsi"), "pe": r.get("pe"), "pb": r.get("pb"),
                     "roe": r.get("roe"), "close": _close(sym)})
    rows.sort(key=lambda x: (0 if x["signal"] == "BUY" else 1, -(x["score"] or 0)))
    return rows[:MAX_CANDIDATES]


def _affordable(budget: int | None, candidates: list[dict]) -> bool:
    """budget đủ mua ≥1 lô (giá×100) của ít nhất 1 ứng viên?"""
    if not budget or budget <= 0:
        return False
    for c in candidates:
        px = c.get("close")
        if isinstance(px, (int, float)) and px > 0 and budget >= px * PRICE_UNIT_VND * LOT:
            return True
    return False


def _prompt(triggers: list[dict], candidates: list[dict], budget: int | None,
            has_cash_op: bool) -> str:
    trig_lines = "\n".join(
        f"- {t['symbol']}: " + "; ".join(t["reasons"]) for t in triggers) or "- (không có)"
    cand_lines = "\n".join(
        f"- {c['symbol']} [{c['signal']}] score={c.get('score')} RSI={c.get('rsi')} "
        f"P/E={c.get('pe')} P/B={c.get('pb')} ROE={c.get('roe')} giá≈{c.get('close')}"
        for c in candidates) or "- (không có ứng viên)"
    budget_line = (f"{budget:,} VND (số dư ví bank realtime)" if budget
                   else "chưa lấy được (không đề xuất mua mới bằng tiền rảnh)")
    return (
        "Đây là quét sự kiện cuối phiên danh mục chứng khoán VN. CHỈ đề xuất khi thực sự "
        "đáng làm — không giao dịch cho có.\n\n"
        f"MÃ ĐANG GIỮ BỊ TRIGGER:\n{trig_lines}\n\n"
        f"NGÂN SÁCH MUA (tiền rảnh): {budget_line}\n\n"
        f"ỨNG VIÊN ROTATE / GIẢI NGÂN (rule-based BUY, chưa nắm giữ):\n{cand_lines}\n\n"
        "Với mỗi mã bị trigger, dùng dữ liệu TCBS/thị trường quyết GIỮ / GIẢM / BÁN + lý do "
        "CÓ SỐ (rating, đồng thuận CTCK vs giá hiện tại, khối ngoại, RSI, SMA50).\n"
        "Nếu đề xuất BÁN → gợi ý xoay sang ứng viên nào, NHƯNG CHỈ khi vượt guard chi phí: lợi "
        f"thế mã mới phải hơn ~{ROUND_TRIP_COST_PCT}% round-trip (phí 0.15%×2 + thuế bán 0.1% + "
        "slippage ~0.1%) VÀ bù được thời gian chết T+2 (bán hôm nay tiền về sau 2 phiên). Lợi "
        "thế mỏng / chỉ nhúng nhẹ → GIỮ NGUYÊN, nói rõ 'không đủ biên để xoay'.\n"
        + ("Có tiền rảnh: RẢI vào 2–3 mã, KHÔNG dồn hết 1 mã (tránh tạo tập trung mới thay cho "
           "mã đang lệch). Không để mã MUA MỚI nào vượt ~20–25% NAV. Ưu tiên ngành CHƯA có trong "
           "danh mục để phân tán. Mua theo LÔ 100cp trong đúng ngân sách ví, in số lô mỗi mã + "
           "tiền dư.\n" if has_cash_op else "")
        + "Đây KHÔNG phải auto-trade — chỉ là đề xuất để người dùng cân nhắc. Trình bày tiếng "
        "Việt, ngắn gọn, có số. Kết: 'tham khảo, không phải khuyến nghị đầu tư'."
    )


def watch(asset_class: str = "vn_stock", holdings_csv: str | None = None,
          require_mcp: bool = False, throttle: float = 2.2,
          extra: list[str] | None = None, group: str = "VN30") -> dict:
    """Quét EOD danh mục + ví: im lặng nếu không có việc, escalate đề xuất nếu có trigger."""
    try:
        positions, note = _positions(asset_class, holdings_csv, throttle)
    except pf.PortfolioError as e:
        return {"error": f"không lấy được danh mục: {e}"}
    except BaseException as e:
        return {"error": f"lỗi quét danh mục: {type(e).__name__}"}

    budget: int | None = None
    budget_note = None
    try:
        budget = int(pf.fetch_cash(("bank",)).get("total") or 0)
    except pf.PortfolioError as e:
        budget_note = f"không lấy được số dư ví: {e}"
    except BaseException as e:
        budget_note = f"lỗi lấy số dư ví: {type(e).__name__}"

    triggers = _scan_triggers(positions, throttle)
    held_syms = {p["symbol"].upper() for p in positions}
    candidates = _candidates(held_syms, group, extra, throttle) if (triggers or budget) else []
    has_cash_op = _affordable(budget, candidates)

    if not triggers and not has_cash_op:
        return {"silent": True, "triggers": [], "budget": budget,
                "proposal": None, "note": budget_note or note, "group": group}

    result = {
        "silent": False, "triggers": triggers, "budget": budget,
        "candidates": candidates, "group": group,
        "note": budget_note or note,
    }

    if not _llm_available():
        lines = [f"{t['symbol']}: " + "; ".join(t["reasons"]) for t in triggers]
        if has_cash_op:
            lines.append(f"Tiền rảnh {budget:,} VND — có ứng viên giải ngân: "
                         + ", ".join(c["symbol"] for c in candidates))
        result["proposal"] = None
        result["mode"] = "rule-based"
        result["summary"] = "\n".join(lines) or "(chỉ có tiền rảnh, không mã bị trigger)"
        return result

    prompt = _prompt(triggers, candidates, budget, has_cash_op)
    try:
        text = tcbs._llm_mcp(prompt, system=profile_system(tcbs._TCBS_SYS))
        result["proposal"] = text
        result["mode"] = "mcp"
    except tcbs.TcbsError as e:
        if require_mcp:
            return {"error": f"MCP TCBS không dùng được: {e}"}
        try:
            text = _llm(prompt, system=profile_system(_DEFAULT_SYS), max_tokens=1200)
            result["proposal"] = text
            result["mode"] = f"fallback-text ({type(e).__name__})"
        except BaseException as e2:
            result["proposal"] = None
            result["mode"] = f"llm-failed ({type(e2).__name__})"
    return result
