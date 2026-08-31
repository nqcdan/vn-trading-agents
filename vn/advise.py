"""`advise` — kế hoạch hành động tháng, tối ưu TOÀN BỘ danh mục + dòng tiền mới.

Hai chế độ:
- MCP (mặc định): rule-based rank chỉ để LỌC shortlist (danh mục + top ứng viên) → LLM
  dùng TCBS MCP lấy rating 7 chiều + đồng thuận CTCK + khối ngoại THẬT cho shortlist rồi
  lập kế hoạch. Fallback text-mode nếu TCBS chưa auth.
- Text (--no-mcp): rank rule-based (+ LLM-verify top) → 1 lần gọi LLM text, không MCP.
"""
from __future__ import annotations

from . import recommend as rec
from . import tcbs as tcbs_mcp
from . import portfolio as pf
from . import actions
from .agents import _llm, _llm_available, _DEFAULT_SYS
from .profile import load_profile, profile_system

_JSON_DIRECTIVE = (
    "\n\nCUỐI CÙNG, sau phần trình bày, in DUY NHẤT MỘT khối ```json chứa list hành động "
    "thực thi đúng kế hoạch trên:\n"
    '[{"action":"BUY|SELL|HOLD","symbol":"MÃ","lots":<số lô 100cp>,'
    '"price":<giá 1 cp theo ĐỒNG, vd 84200>,"reason":"ngắn"}].\n'
    "Chỉ gồm mã CÓ hành động mua/bán thật (bỏ HOLD nếu không giao dịch). `lots`=số lô sẽ "
    "khớp, `price`=giá/cp theo đồng (không phải nghìn). Khối JSON PHẢI khớp con số trong "
    "bảng ở trên."
)


def _resolve_cash(cash: str | None, cash_wallet: tuple[str, ...] | None) -> tuple[str, dict | None]:
    """→ (cash_txt cho prompt, thông tin ví nếu lấy từ everyday).

    Ưu tiên --cash > ví chỉ định > ví bank mặc định (không còn hardcode 23tr).
    """
    if cash:
        return cash, None
    if cash_wallet:
        info = pf.fetch_cash(cash_wallet)  # raise PortfolioError nếu everyday không sẵn
        kinds = "+".join(cash_wallet)
        txt = (f"{info['total']:,}đ (số dư ví {kinds} thật từ everyday hôm nay — "
               "đây là TOÀN BỘ tiền có thể tiêu tháng này)")
        return txt, info
    info = pf.fetch_cash(("bank",))  # raise PortfolioError nếu everyday không sẵn
    txt = (f"{info['total']:,}đ (số dư ví bank thật từ everyday hôm nay — "
           "TOÀN BỘ tiền có thể tiêu)")
    return txt, info

MAX_CANDIDATES = 3  # số ứng viên mới đưa vào shortlist MCP (kiểm soát số tool-call)


def _ranking_lines(rows: list[dict], keep: set[str] | None = None) -> list[str]:
    out = []
    for r in rows:
        if "error" in r:
            continue
        if keep is not None and r["symbol"].upper() not in keep:
            continue
        tag = "GIỮ" if r["held"] else "mới"
        w = f" {r['weight_pct']:.0f}%" if isinstance(r.get("weight_pct"), (int, float)) else ""
        roe = f"{r['roe']:.0%}" if isinstance(r.get("roe"), (int, float)) else "—"
        c = r.get("close")
        px = f" giá≈{int(c * 1000):,}đ" if isinstance(c, (int, float)) else ""
        line = (f"{r['symbol']} [{tag}{w}] {r['signal']} align={r['align']} "
                f"RSI={r.get('rsi')} P/E={r.get('pe')} P/B={r.get('pb')} ROE={roe}{px} → {r['action']}")
        if r.get("llm_action"):
            lc = r.get("llm_conf")
            line += f"  ⟨LLM: {r['llm_action']}" + (f" {lc:.2f}" if isinstance(lc, (int, float)) else "") + "⟩"
        out.append(line)
    return out


def _shortlist(rows: list[dict], extra: list[str] | None = None) -> tuple[list[str], list[str]]:
    """(mã đang giữ, top ứng viên mới BUY) — để MCP đào sâu, giới hạn số tool-call.

    `extra` = mã ép thêm vào shortlist (vd GMD không thuộc VN30) dù không qua rule-based.
    """
    held = [r["symbol"] for r in rows if r.get("held") and "error" not in r]
    cands = [r["symbol"] for r in rows if not r.get("held") and "error" not in r
             and r["signal"] in ("BUY", "BUY-WAIT")][:MAX_CANDIDATES]
    for e in (extra or []):
        e = e.strip().upper()
        if e and e not in held and e not in cands:
            cands.append(e)
    return held, cands


def _text_prompt(group, macro, lines, cash_txt) -> str:
    return (
        f"Vĩ mô voz hiện tại: {macro['signal']} (net {macro['net']}).\n"
        f"Tiền mới cần giải ngân tháng này: {cash_txt}.\n\n"
        f"BẢNG TÍN HIỆU (danh mục đang giữ + rổ {group}, as-of hôm nay):\n"
        + "\n".join(lines) + "\n\n"
        "Ghi chú: ⟨LLM: …⟩ là phán quyết LLM sâu — ƯU TIÊN nó hơn tín hiệu rule-based. "
        "CHỈ đề xuất MUA mã nào LLM xác nhận BUY; mã rule-based BUY nhưng ⟨LLM: HOLD/SELL⟩ thì KHÔNG mua.\n"
        "Hãy lập KẾ HOẠCH HÀNH ĐỘNG THÁNG NÀY, tối ưu TOÀN BỘ (danh mục hiện có + tiền mới), "
        "tuân thủ ràng buộc hồ sơ NĐT (không margin, ≤8–10 mã). Nêu rõ:\n"
        "1) RÓT TIỀN MỚI vào mã nào, tỷ lệ %, vì sao (ưu tiên phân tán ngành).\n"
        "2) BÁN / GIẢM / ROTATE mã nào, vì sao.\n"
        "3) Xử lý tập trung FPT (bán bớt vs pha loãng bằng tiền mới).\n"
        "4) Điểm vào: chia lệnh, tránh mua đuổi RSI≥70.\n"
        f"RÀNG BUỘC: ngân sách cứng {cash_txt}; mua theo LÔ 100 cp (giá×100=tiền/lô). "
        "Tính số lô mỗi mã, tổng ≤ ngân sách, in tiền mặt còn dư.\n"
        "Gọn, có số, tiếng Việt."
        + _JSON_DIRECTIVE
    )


def _mcp_prompt(group, macro, held, cands, ranking_lines, cash_txt) -> str:
    return (
        f"Lập KẾ HOẠCH ĐẦU TƯ THÁNG NÀY cho danh mục, dùng DỮ LIỆU TCBS REAL-TIME.\n"
        f"Vĩ mô voz (nguồn phụ): {macro['signal']} (net {macro['net']}). "
        f"Tiền mới giải ngân: {cash_txt}.\n\n"
        f"Mã ĐANG GIỮ: {', '.join(held) or '(không có)'}\n"
        f"Ứng viên mua mới (đã lọc rule-based từ {group}): {', '.join(cands) or '(không có)'}\n\n"
        "Rule-based tham khảo (giá/PE/RSI vnstock, có thể lệch — TCBS mới là chuẩn):\n"
        + "\n".join(ranking_lines) + "\n\n"
        "Với MỖI mã (đang giữ + ứng viên), gọi tool TCBS để lấy: getGeneralRating (điểm 7 chiều, "
        "chú ý điểm ĐỊNH GIÁ), getHistoryRecommendation (đồng thuận CTCK + giá mục tiêu vs giá hiện tại), "
        "getVolumeAndForeign (khối ngoại ròng + RS rank), getStockRatio (P/E,P/B,ROE real-time), "
        "getTechnicalIndicator (RSI/MACD). Ngân hàng dùng getFinancialRatioForBank.\n\n"
        "Rồi lập kế hoạch tối ưu TOÀN BỘ (danh mục + tiền mới), HỢP HỒ SƠ NĐT (không margin, ≤8–10 mã):\n"
        "1) RÓT TIỀN MỚI vào mã nào, tỷ lệ %, dựa trên rating/đồng thuận/khối ngoại TCBS (ưu tiên phân tán ngành).\n"
        "   CHỈ mua mã TCBS ủng hộ (rating tốt / định giá rẻ / CTCK Buy còn upside / ngoại mua ròng).\n"
        "2) BÁN / GIẢM / ROTATE mã nào, vì sao (dẫn số TCBS).\n"
        "3) Xử lý tập trung FPT (bán bớt vs pha loãng bằng tiền mới) — chọn tối ưu.\n"
        "4) Điểm vào: chia lệnh, tránh mua đuổi (RSI/Stoch cao), tôn trọng khối ngoại + kỹ thuật.\n\n"
        "RÀNG BUỘC DÒNG TIỀN (BẮT BUỘC tính đúng):\n"
        f"- Ngân sách CỨNG tháng này = {cash_txt}. Tổng tiền mua KHÔNG được vượt.\n"
        "- Cổ phiếu VN mua theo LÔ 100 cổ (tối thiểu 100 cp/lệnh). Lấy GIÁ hiện tại từ TCBS.\n"
        "- Với mỗi mã đề xuất mua, tính: tiền 1 lô = giá×100; số lô mua được trong ngân sách; "
        "thành tiền thực; và TIỀN MẶT CÒN DƯ (phần không đủ 1 lô để lại tiền mặt).\n"
        "- In BẢNG: Mã | Giá | Tiền/lô (giá×100) | Số lô | Thành tiền | % ngân sách. "
        "Có dòng TỔNG + TIỀN DƯ. Nếu mã giá cao khiến 1 lô > phần ngân sách dự kiến → nói rõ "
        "và điều chỉnh (giảm số lô mã khác hoặc để dư tiền chờ tháng sau).\n\n"
        "Trình bày gọn, có số, ghi rõ 'nguồn TCBS'."
        + _JSON_DIRECTIVE
    )


def advise(group: str = "VN30", holdings_csv: str | None = None, asset_class: str = "vn_stock",
           cash: str | None = None, throttle: float = 2.2, llm_top: int = 5,
           use_mcp: bool = True, extra: list[str] | None = None,
           cash_wallet: tuple[str, ...] | None = None,
           require_mcp: bool = False) -> dict:
    if not _llm_available():
        return {"error": "cần LLM (VN_LLM_BACKEND=claude-cli|api) cho advise"}
    if not load_profile():
        return {"error": "thiếu PROFILE.md — chạy /interview-me hoặc tạo hồ sơ trước"}
    try:
        cash_txt, cash_info = _resolve_cash(cash, cash_wallet)
    except pf.PortfolioError as e:
        return {"error": f"không lấy được số dư ví everyday: {e}"}

    # MCP mode: rank rule-based CHỈ để lọc shortlist (llm_top=0, khỏi vét quota) → TCBS đào sâu.
    # Text mode: LLM-verify top rồi 1 prompt text.
    r = rec.recommend(group, holdings_csv=holdings_csv, asset_class=asset_class,
                      llm_top=0 if use_mcp else llm_top, throttle=throttle)
    lines = _ranking_lines(r["ranking"])          # đầy đủ — cho journal/return
    macro = r["macro"]
    held, cands = _shortlist(r["ranking"], extra)
    keep = {s.upper() for s in held + cands}
    prompt_lines = _ranking_lines(r["ranking"], keep=keep)  # trim → LLM khỏi nhồi cả rổ

    def _text_fallback(reason: str) -> tuple[str, str]:
        try:
            p = _llm(_text_prompt(group, macro, prompt_lines, cash_txt),
                     system=profile_system(_DEFAULT_SYS), max_tokens=1500, timeout=220)
            return p, (reason or "text")
        except Exception as e:  # timeout/CLI lỗi → degrade sạch, không crash
            return (f"(LLM tổng hợp thất bại: {e}. Bảng tín hiệu rule-based vẫn dùng được ở "
                    "phần ranking_lines / --json.)"), f"llm-failed ({e})"

    if use_mcp:
        prompt = _mcp_prompt(group, macro, held, cands, prompt_lines, cash_txt)
        try:
            plan, tcbs_ok = tcbs_mcp._llm_mcp(prompt, system=profile_system(tcbs_mcp._TCBS_SYS))
            mode = "tcbs-mcp" if tcbs_ok else "fallback-mcp-offline (rule-based, TCBS ngắt)"
        except tcbs_mcp.TcbsError as e:
            if require_mcp:
                return {"error": f"TCBS MCP không dùng được (--require-mcp bật): {e}. "
                                 "Chạy: claude → /mcp → tcbs → Authenticate"}
            plan, mode = _text_fallback(f"fallback-text ({e})")
    else:
        plan, mode = _text_fallback("text")

    plan = plan.strip()
    return {"group": group, "macro": macro, "mode": mode, "ranking_lines": lines,
            "cash_txt": cash_txt, "cash_info": cash_info,
            "errors": r["errors"], "plan": plan,
            "actions": actions.parse_actions(plan)}
