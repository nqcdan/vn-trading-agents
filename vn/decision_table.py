"""Render bảng quyết định deterministic từ kết quả `advise()`.

Không phụ thuộc LLM tự bịa layout: gộp ranking rule-based + actions (JSON đã parse)
+ ngân sách → bảng cố định + dòng "giải ngân hay hold". `render()` = output lệnh
`advise`; `render_daily()` = báo cáo gộp (cảnh báo + quyết định + xếp hạng cả rổ) cho
lệnh `daily`. Phần diễn giải sâu để nguyên plan LLM/TCBS bên dưới.
"""
from __future__ import annotations

import re
import unicodedata

from . import vn_market

SPLIT_STEP = 0.015  # lệnh 2: mua thấp hơn / bán cao hơn 1.5% ≈ dao động 1 phiên của bluechip

_ACTION_ORDER = {"MUA MỚI": 0, "GOM THÊM": 1, "GIỮ": 2, "GIẢM": 3, "BÁN": 4}
_LOT = 100


def _w(s: str) -> int:
    """Bề rộng hiển thị: chuẩn hoá NFC, bỏ combining marks (dấu tiếng Việt = 0 rộng)."""
    s = unicodedata.normalize("NFC", s)
    return sum(0 if unicodedata.combining(c) else 1 for c in s)


def _pad(s: str, width: int, align: str) -> str:
    gap = max(0, width - _w(s))
    return (" " * gap + s) if align == "r" else (s + " " * gap)


def _money(v: float | None) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}".replace(".", ",") + "tr"
    if abs(v) >= 1_000:
        return f"{v / 1_000:.0f}k"
    return f"{v:.0f}"


def _num(v, fmt: str = "{:.1f}") -> str:
    return fmt.format(v) if isinstance(v, (int, float)) else "—"


def _pct(v, fmt: str = "{:.0%}") -> str:
    return fmt.format(v) if isinstance(v, (int, float)) else "—"


def _budget(res: dict) -> float | None:
    b = res.get("budget")
    if isinstance(b, (int, float)):
        return float(b)
    info = res.get("cash_info") or {}
    if isinstance(info.get("total"), (int, float)):
        return float(info["total"])
    m = re.search(r"([\d.,]{6,})", res.get("cash_txt", ""))
    if m:
        try:
            return float(m.group(1).replace(".", "").replace(",", ""))
        except ValueError:
            return None
    return None


def _box(headers: list[str], rows: list[list[str]], aligns: list[str]) -> str:
    """Bảng MARKDOWN (render đẹp mọi viewer .md; raw text vẫn thẳng cột nhờ pad)."""
    cols = len(headers)
    widths = [_w(headers[i]) for i in range(cols)]
    for r in rows:
        for i in range(cols):
            widths[i] = max(widths[i], _w(r[i]))
    widths = [max(3, w) for w in widths]

    def _row(vals: list[str]) -> str:
        return "| " + " | ".join(_pad(vals[i], widths[i], aligns[i]) for i in range(cols)) + " |"

    def _sep(i: int) -> str:
        w = widths[i]
        if aligns[i] == "r":
            return "-" * (w - 1) + ":"
        if aligns[i] == "c":
            return ":" + "-" * (w - 2) + ":"
        return ":" + "-" * (w - 1)

    out = [_row(headers), "| " + " | ".join(_sep(i) for i in range(cols)) + " |"]
    out += [_row(r) for r in rows]
    return "\n".join(out)


def _classify(held: bool, act: str | None) -> str:
    if act == "SELL":
        return "BÁN"
    if act == "BUY":
        return "GOM THÊM" if held else "MUA MỚI"
    return "GIỮ"


def _rule_note(row: dict) -> str:
    parts = []
    if isinstance(row.get("rsi"), (int, float)):
        parts.append(f"RSI {row['rsi']:.0f}")
    if isinstance(row.get("pe"), (int, float)):
        parts.append(f"P/E {row['pe']:.1f}")
    if isinstance(row.get("roe"), (int, float)):
        parts.append(f"ROE {row['roe']:.0%}")
    tail = {"golden": "golden", "death": "death"}.get(row.get("align"), "")
    if tail:
        parts.append(tail)
    return " · ".join(parts) or "—"


def _parse_money(s: str) -> float:
    if not s or s == "—":
        return 0.0
    s = s.replace("tr", "").replace("k", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _verdict(deploy: float, budget: float | None, has_acts: bool, macro: dict,
             sell: float = 0.0) -> str:
    if not has_acts or deploy <= 0:
        tail = " (vĩ mô yếu, không mã nào đủ hấp dẫn)" if macro.get("signal") == "BEARISH" else ""
        return f"▶ QUYẾT ĐỊNH ĐỢT NÀY: HOLD TIỀN — agent không đề xuất mua{tail}."
    if not budget:
        return f"▶ QUYẾT ĐỊNH ĐỢT NÀY: GIẢI NGÂN {_money(deploy)}."
    net = deploy - sell  # tiền MỚI rót ra (phần mua vượt phần bán tự tài trợ)
    pct = max(0.0, net) / budget * 100
    reserve = budget - net
    lean = ("giải ngân phần lớn" if pct >= 60
            else "giải ngân một phần, giữ đệm tiền mặt lớn" if pct >= 30
            else "giải ngân thăm dò, phần lớn hold tiền")
    return (f"▶ QUYẾT ĐỊNH ĐỢT NÀY: GIẢI NGÂN RÒNG {_money(max(0.0, net))} ({pct:.0f}%) · "
            f"giữ lại {_money(reserve)} ({100 - pct:.0f}%) — {lean}.")


def _header(res: dict, title: str = "Kế hoạch") -> str:
    macro = res.get("macro", {})
    macro_s = f"{macro.get('signal', '—')} (net {macro.get('net', 0)})"
    return (f"=== {title} {res.get('group', '?')} | nguồn: {res.get('mode', '?')} "
            f"| vĩ mô tin: {macro_s} | ngân sách: {_money(_budget(res))} ===")


def _held_tag(row: dict) -> str:
    w = row.get("weight_pct")
    if isinstance(w, (int, float)):
        return f"◆{w:.0f}%"
    return "◆" if row.get("held") else ""


def _clip(reason: str, width: int) -> str:
    reason = (reason or "").strip().replace("\n", " ")
    return reason[: width - 1] + "…" if _w(reason) > width else reason


def _action_block(res: dict, reason_width: int = 46) -> tuple[str, str]:
    """→ (bảng hành động, dòng verdict). Lặp theo LIST actions (1 mã có thể có ≥2 lệnh),
    cộng thêm mã đang giữ không có lệnh (GIỮ). Deploy = tổng BUY; sell = tổng SELL."""
    ranking = {r["symbol"].upper(): r for r in res.get("ranking", []) if "error" not in r}
    all_acts = [a for a in res.get("actions", []) if a.get("action") in ("BUY", "SELL")]
    budget = _budget(res)

    rows, deploy, sell = [], 0.0, 0.0
    acted = set()
    for a in all_acts:
        sym = a["symbol"].upper()
        acted.add(sym)
        row = ranking.get(sym, {})
        label = _classify(bool(row.get("held")), a["action"])
        if a.get("lots"):
            tien = a["lots"] * a["price"] * _LOT
            lots_s, tien_s = str(a["lots"]), _money(tien)
            lo_s = f"{a['price']:,.0f}" if a.get("price") else "—"
            pct_s = f"{tien / budget * 100:.1f}%" if budget else "—"
            (deploy, sell) = (deploy + tien, sell) if a["action"] == "BUY" else (deploy, sell + tien)
        else:
            lots_s = tien_s = pct_s = lo_s = "—"
        tag = _held_tag(row)
        rows.append([f"{sym}{(' ' + tag) if tag else ''}", label, lots_s, lo_s, tien_s, pct_s,
                     _clip(a.get("reason"), reason_width)])

    for sym, row in ranking.items():  # mã đang giữ không có lệnh → GIỮ
        if row.get("held") and sym not in acted:
            tag = _held_tag(row)
            rows.append([f"{sym}{(' ' + tag) if tag else ''}", "GIỮ", "—", "—", "—", "—",
                         _clip(_rule_note(row), reason_width)])

    rows.sort(key=lambda r: (_ACTION_ORDER.get(r[1], 5), -_parse_money(r[4])))
    verdict = _verdict(deploy, budget, bool(all_acts), res.get("macro", {}), sell)
    if sell > 0:
        verdict += f" Kèm BÁN {_money(sell)} (tài trợ phần mua)."
    warns = res.get("action_warnings") or []
    if warns:
        verdict += "\n\n> ⚠ Đã tự chỉnh lệnh LLM cho khớp thực tế (số cổ đang giữ / ngân sách):\n" \
                   + "\n".join(f"> - {w}" for w in warns)
    table = _box(["Mã", "Hành động", "Lô", "Giá LO", "Tiền", "% NS", "Tín hiệu / Lý do"],
                 rows, ["l", "l", "r", "r", "r", "r", "l"])
    return table, verdict


def _order_rows(acts: list[dict], holdings: list[dict] | None) -> list[dict]:
    """Tách actions thành lệnh LO cụ thể: ≥2 lô → 2 lệnh (lệnh 1 giá báo cáo, lệnh 2 lệch SPLIT_STEP)."""
    held = {str(h.get("symbol", "")).upper(): int(h.get("qty") or 0) for h in holdings or []}
    first, second = [], []
    for a in sorted(acts, key=lambda a: a["action"] != "SELL"):  # BÁN trước
        side, sym, lots = a["action"], a["symbol"].upper(), int(a.get("lots") or 0)
        if side not in ("BUY", "SELL") or lots <= 0 or not a.get("price"):
            continue
        ex = vn_market.detect_exchange(sym)
        lo = vn_market.round_tick(float(a["price"]), ex, side)
        n1 = (lots + 1) // 2 if lots >= 2 else lots
        first.append({"side": side, "sym": sym, "qty": n1 * _LOT, "price": lo, "when": "Phiên tới, sau ATO (~9:15)"})
        if lots - n1:
            p2 = vn_market.round_tick(lo * (1 - SPLIT_STEP if side == "BUY" else 1 + SPLIT_STEP), ex, side)
            second.append({"side": side, "sym": sym, "qty": (lots - n1) * _LOT, "price": p2,
                           "when": f"Treo LO mỗi phiên tới khi khớp ({'−' if side == 'BUY' else '+'}{SPLIT_STEP:.1%})"})
        odd = held.get(sym, 0) % _LOT
        if side == "SELL" and odd and lots * _LOT >= held[sym] - odd:
            second.append({"side": side, "sym": sym, "qty": odd, "price": lo, "when": "Bảng lô lẻ (bán hết phần lẻ)"})
    return first + second


def render_orders(res: dict, holdings: list[dict] | None = None) -> str:
    """Bảng lệnh đặt cụ thể từ mục 3: số cp, giá LO đúng bước giá, tiền gồm phí, tiền mặt còn lại."""
    acts = [a for a in res.get("actions", []) if a.get("action") in ("BUY", "SELL")]
    rows = _order_rows(acts, holdings)
    if not rows:
        return ""
    cash = _budget(res)
    table, buy_total, sell_total, short = [], 0.0, 0.0, False
    for i, o in enumerate(rows, 1):
        gross = o["qty"] * o["price"]
        if o["side"] == "BUY":
            money = gross * (1 + vn_market.BUY_FEE)
            buy_total += money
            if cash is not None:
                cash -= money
            left = f"{cash:,.0f}" if cash is not None else "—"
            if cash is not None and cash < 0:
                left, short = f"⚠ {left}", True
        else:
            money = gross * (1 - vn_market.SELL_FEE - vn_market.SELL_TAX)
            sell_total += money
            left = "—"
        table.append([str(i), "MUA" if o["side"] == "BUY" else "BÁN", o["sym"], f"{o['qty']:,}",
                      f"{o['price']:,.0f}", f"{money:,.0f}", left, o["when"]])
    out = ["**Lệnh đặt cụ thể** (LO, giá đã làm tròn bước giá; tiền gồm phí 0,15%, bán trừ thêm thuế 0,1%):", "",
           _box(["#", "Lệnh", "Mã", "SL (cp)", "Giá LO", "Tiền", "Tiền mặt còn", "Khi nào"],
                table, ["r", "l", "l", "r", "r", "r", "r", "l"]), "",
           f"Tổng mua {buy_total:,.0f}đ · tiền bán về {sell_total:,.0f}đ (T+2, không dùng mua ngay)"]
    if short:
        out.append("> ⚠ Tiền mặt không đủ cho lệnh đánh dấu: chờ tiền bán về, ứng trước tiền bán, hoặc bỏ lệnh đó.")
    return "\n".join(out)


def render_ranking(rows: list[dict]) -> str:
    """Bảng xếp hạng CẢ RỔ (rule-based) — phần giá trị của `recommend`."""
    order = {"BUY": 0, "BUY-WAIT": 1, "HOLD": 2, "SELL": 3}
    good = [r for r in rows if "error" not in r]
    good.sort(key=lambda r: (order.get(r.get("signal"), 9), -(r.get("score") or 0)))
    table_rows = []
    for r in good:
        tag = _held_tag(r)
        table_rows.append([
            f"{r['symbol']}{(' ' + tag) if tag else ''}",
            r.get("signal", "—"),
            f"{r['close'] * 1000:,.0f}" if isinstance(r.get("close"), (int, float)) else "—",
            _num(r.get("rsi"), "{:.0f}"),
            _num(r.get("pe")), _num(r.get("pb")), _pct(r.get("roe")),
            str(r.get("action", "—")),
        ])
    return _box(["Mã", "Tín hiệu", "Giá", "RSI", "P/E", "P/B", "ROE", "Khuyến nghị"],
                table_rows, ["l", "l", "r", "r", "r", "r", "r", "l"])


def render_triggers(triggers: list[dict]) -> str:
    if not triggers:
        return "_Không có cảnh báo — danh mục ổn (không mã nào RSI≥70 / tập trung / thủng SMA50 / tin xấu)._"
    return "\n".join(f"- **{t['symbol']}**: " + "; ".join(t["reasons"]) for t in triggers)


_SENTIMENT_ICON = {"BULLISH": "🟢 tích cực", "BEARISH": "🔴 tiêu cực", "NEUTRAL": "⚪ trung tính"}


_ICON = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪"}


def _date_anchor(date: str, link: str) -> str:
    """`09-07` có link → [`09-07`](url); không link → `09-07`; không ngày → ''."""
    if not date:
        return ""
    return f"[`{date}`]({link}) " if link else f"`{date}` "


def render_macro(macro: dict, title_width: int = 78) -> str:
    sig = macro.get("signal", "NEUTRAL")
    out = [f"**Tâm lý tin thị trường:** {_SENTIMENT_ICON.get(sig, sig)} · "
           f"net {macro.get('net', 0):+d} · {macro.get('n', 0)} tin _(suy từ headline tài chính)_"]
    market = macro.get("market") or []
    if market:
        out += ["", "**Tin thị trường (CafeF · Vietstock · VnEconomy · ĐTCK):**"]
        for m in market:
            src = f" _({m['source']})_" if m.get("source") else ""
            out.append(f"- {_date_anchor(m.get('date', ''), m.get('link', ''))}{_clip(m.get('title', ''), title_width)}{src}")
    return "\n".join(out)


def render_symbol_news(news_map: dict, per: int = 4, title_width: int = 78, summary_width: int = 100) -> str:
    """Block per-symbol: tâm lý + ≤`per` headline ([ngày](link) tiêu đề · nguồn) + trích 1 dòng summary."""
    if not news_map:
        return "_Không lấy được tin per-symbol._"
    blocks = []
    for sym, d in news_map.items():
        icon = _ICON.get(d.get("signal", "NEUTRAL"), "⚪")
        senti = f"{icon} net {d.get('net', 0):+d}" if d.get("n") else "⚪ chưa có tin"
        head = f"**{sym}** — {senti} · {d.get('n', 0)} tin"
        latest = d.get("latest") or []
        if not latest:
            blocks.append(head + "\n- _(không có tin gần đây)_")
            continue
        lines = [head]
        for it in latest[:per]:
            anchor = _date_anchor(it.get("date", ""), it.get("link", ""))
            src = f" _({it['source']})_" if it.get("source") else ""
            lines.append(f"- {anchor}{_clip(it.get('title', ''), title_width)}{src}")
            summ = it.get("summary") or ""
            if summ and _w(summ) > 20:
                lines.append(f"  _{_clip(summ, summary_width)}_")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_portfolio(holdings: list[dict]) -> str:
    """Danh mục đang giữ: SL / giá vốn / giá TT / giá trị / P&L / tỷ trọng (từ everyday)."""
    good = [h for h in holdings if (h.get("marketValue") or 0) > 0]
    if not good:
        return "_Không lấy được danh mục hiện tại._"
    total = sum(h.get("marketValue") or 0 for h in good)
    total_cost = sum(h.get("costBasis") or 0 for h in good)
    good.sort(key=lambda h: -(h.get("marketValue") or 0))
    rows = []
    for h in good:
        qty = h.get("qty") or 0
        cost = h.get("costBasis") or 0
        mv = h.get("marketValue") or 0
        avg = cost / qty if qty else 0
        px = mv / qty if qty else 0
        pnl_pct = h.get("pnlPct")
        pnl_s = f"{pnl_pct:+.1f}%" if isinstance(pnl_pct, (int, float)) else "—"
        w = mv / total * 100 if total else 0
        rows.append([h.get("symbol", "?"), f"{qty:,}", _money(avg), _money(px),
                     _money(mv), pnl_s, f"{w:.1f}%"])
    total_pnl = total - total_cost
    total_pnl_pct = total_pnl / total_cost * 100 if total_cost else 0
    tbl = _box(["Mã", "SL", "Giá vốn", "Giá TT", "Giá trị", "P&L", "Tỷ trọng"],
               rows, ["l", "r", "r", "r", "r", "r", "r"])
    summary = (f"\n\n**Tổng:** {_money(total)} · vốn {_money(total_cost)} · "
               f"P&L {_money(total_pnl)} ({total_pnl_pct:+.1f}%)")
    return tbl + summary


_GLOSSARY = [
    ("NAV / tỷ trọng", "NAV = tổng giá trị danh mục. Tỷ trọng = mã đó chiếm mấy % NAV. Dồn 1 mã quá nhiều = **tập trung**, rủi ro cao."),
    ("Lô", "Đơn vị mua tối thiểu ở VN = 100 cổ phiếu. '6 lô' = 600 cp. Không mua lẻ."),
    ("P/E", "Giá / lợi nhuận mỗi cổ. Thấp thường là 'rẻ', cao là 'đắt' (so trong cùng ngành)."),
    ("P/B", "Giá / giá trị sổ sách. <1 = dưới giá trị sổ sách; cao (vd >3) = thị trường trả giá đắt cho tài sản."),
    ("ROE", "Lợi nhuận / vốn chủ sở hữu — công ty sinh lời hiệu quả cỡ nào trên vốn. Cao thường tốt."),
    ("RSI", "Thước đo 0–100 'nóng/nguội'. ≥70 = mua quá nhiều, dễ điều chỉnh giảm (tránh mua đuổi). ~50–65 = bình thường."),
    ("SMA50", "Giá trung bình 50 phiên gần nhất. Giá 'thủng SMA50' (rớt xuống dưới) thường là dấu hiệu yếu đi."),
    ("Golden / death cross", "Golden = đường MA ngắn cắt LÊN trên MA dài (tín hiệu tăng); death = cắt XUỐNG (tín hiệu giảm)."),
    ("Khối ngoại", "Nhà đầu tư nước ngoài. 'Mua ròng' = mua nhiều hơn bán (dòng tiền vào, thường tích cực); 'bán ròng' = ngược lại."),
    ("YoY", "Year-over-Year — so với cùng kỳ năm trước. 'LNST +28% YoY' = lợi nhuận sau thuế tăng 28% so với năm ngoái."),
    ("net (tâm lý tin)", "Điểm tin tích cực trừ tiêu cực. net dương = tin tốt trội; âm = tin xấu trội."),
    ("T+2 / phí round-trip", "Bán xong ~2 phiên tiền/cổ mới về (T+2). Một vòng mua-bán mất ~0.5% (phí+thuế+trượt giá) → chỉ xoay khi lợi thế rõ hơn mức đó."),
    ("Giải ngân / pha loãng / rotate", "Giải ngân = đem tiền rảnh đi mua. Pha loãng = mua thêm mã khác để tỷ trọng mã đang quá lớn tự giảm. Rotate = bán mã này mua mã khác tốt hơn."),
]


def render_glossary() -> str:
    out = ["## Giải nghĩa thuật ngữ"]
    for term, desc in _GLOSSARY:
        out.append(f"- **{term}** — {desc}")
    return "\n".join(out)


def strip_json(plan: str) -> str:
    """Bỏ khối ```json (chỉ dành cho paper auto-apply) + separator thừa khỏi bản hiển thị."""
    if not plan:
        return ""
    out = re.sub(r"```json.*?```", "", plan, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"(?m)^(#{1,4}) ", r"#\1 ", out)  # demote heading LLM 1 cấp → nằm dưới mục 6
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip().rstrip("-").strip()


def render(res: dict) -> str:
    """Output lệnh `advise`: header + verdict + bảng hành động + bảng chỉ số shortlist."""
    if "error" in res:
        return f"Lỗi advise: {res['error']}"
    table, verdict = _action_block(res)
    ranking = [r for r in res.get("ranking", []) if "error" not in r]
    shortlist = {s.upper() for s in res.get("shortlist", [])} or None
    detail = [r for r in ranking if shortlist is None or r["symbol"].upper() in shortlist]
    detail.sort(key=lambda r: r["symbol"])
    detail_rows = [[r["symbol"],
                    _money((r.get("close") or 0) * 1000) if r.get("close") else "—",
                    _num(r.get("rsi"), "{:.0f}"), _num(r.get("pe")), _num(r.get("pb")),
                    _pct(r.get("roe")), r.get("signal", "—")] for r in detail]
    out = [_header(res), "", verdict, "", table, "",
           "Chỉ số chi tiết (rule-based vnstock — TCBS real-time xem phần phân tích dưới):",
           _box(["Mã", "Giá", "RSI", "P/E", "P/B", "ROE", "Rule"],
                detail_rows, ["l", "r", "r", "r", "r", "r", "l"])]
    if res.get("errors"):
        out += ["", "Mã lỗi dữ liệu (bỏ qua): " + ", ".join(res["errors"][:8])]
    return "\n".join(out)


def render_daily(res: dict, triggers: list[dict], date: str,
                 macro: dict | None = None, news_map: dict | None = None,
                 holdings: list[dict] | None = None, market_line: str | None = None) -> str:
    """Báo cáo NGÀY (markdown): vĩ mô + danh mục + cảnh báo + quyết định/giải ngân + tin
    từng mã + xếp hạng cả rổ + phân tích. Layout deterministic, render đẹp mọi viewer .md."""
    if "error" in res:
        return f"Lỗi daily: {res['error']}"
    table, verdict = _action_block(res)
    budget = _money(_budget(res))
    out = [f"# BÁO CÁO NGÀY {date} · rổ {res.get('group', '?')}", "",
           f"**Nguồn:** {res.get('mode', '?')} · **Ngân sách:** {budget}", ""]
    if market_line:
        out += [market_line, ""]
    if macro:
        out += [render_macro(macro), ""]
    if holdings:
        out += ["## 1. Danh mục hiện tại", render_portfolio(holdings), "",
                "## 2. Cảnh báo danh mục", render_triggers(triggers), "",
                "## 3. Quyết định & giải ngân", f"**{verdict}**", "", table, ""]
        orders = render_orders(res, holdings)
        if orders:
            out += [orders, ""]
        if news_map:
            out += ["## 4. Tin tức từng mã", render_symbol_news(news_map), ""]
        out += ["## 5. Xếp hạng cả rổ (rule-based)", render_ranking(res.get("ranking", []))]
    else:
        out += ["## 1. Cảnh báo danh mục", render_triggers(triggers), "",
                "## 2. Quyết định & giải ngân", f"**{verdict}**", "", table, ""]
        orders = render_orders(res)
        if orders:
            out += [orders, ""]
        if news_map:
            out += ["## 3. Tin tức từng mã", render_symbol_news(news_map), ""]
        out += ["## 4. Xếp hạng cả rổ (rule-based)", render_ranking(res.get("ranking", []))]
    if res.get("errors"):
        out += ["", "_Mã lỗi dữ liệu (bỏ qua): " + ", ".join(res["errors"][:8]) + "_"]
    return "\n".join(out)
