"""Render bảng quyết định deterministic từ kết quả `advise()`.

Không phụ thuộc LLM tự bịa layout: gộp ranking rule-based + actions (JSON đã parse)
+ ngân sách → bảng cố định + dòng "giải ngân hay hold". `render()` = output lệnh
`advise`; `render_daily()` = báo cáo gộp (cảnh báo + quyết định + xếp hạng cả rổ) cho
lệnh `daily`. Phần diễn giải sâu để nguyên plan LLM/TCBS bên dưới.
"""
from __future__ import annotations

import re
import unicodedata

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


def _verdict(deploy: float, budget: float | None, has_acts: bool, macro: dict) -> str:
    if not has_acts or deploy <= 0:
        tail = " (vĩ mô yếu, không mã nào đủ hấp dẫn)" if macro.get("signal") == "BEARISH" else ""
        return f"▶ QUYẾT ĐỊNH ĐỢT NÀY: HOLD TIỀN — agent không đề xuất mua{tail}."
    if not budget:
        return f"▶ QUYẾT ĐỊNH ĐỢT NÀY: GIẢI NGÂN {_money(deploy)}."
    pct = deploy / budget * 100
    reserve = budget - deploy
    lean = ("giải ngân phần lớn" if pct >= 60
            else "giải ngân một phần, giữ đệm tiền mặt lớn" if pct >= 30
            else "giải ngân thăm dò, phần lớn hold tiền")
    return (f"▶ QUYẾT ĐỊNH ĐỢT NÀY: GIẢI NGÂN {_money(deploy)} ({pct:.0f}%) · "
            f"giữ lại {_money(reserve)} ({100 - pct:.0f}%) — {lean}.")


def _header(res: dict, title: str = "Kế hoạch") -> str:
    macro = res.get("macro", {})
    macro_s = f"{macro.get('signal', '—')} (net {macro.get('net', 0)})"
    return (f"=== {title} {res.get('group', '?')} | nguồn: {res.get('mode', '?')} "
            f"| vĩ mô voz: {macro_s} | ngân sách: {_money(_budget(res))} ===")


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
            pct_s = f"{tien / budget * 100:.1f}%" if budget else "—"
            (deploy, sell) = (deploy + tien, sell) if a["action"] == "BUY" else (deploy, sell + tien)
        else:
            lots_s = tien_s = pct_s = "—"
        tag = _held_tag(row)
        rows.append([f"{sym}{(' ' + tag) if tag else ''}", label, lots_s, tien_s, pct_s,
                     _clip(a.get("reason"), reason_width)])

    for sym, row in ranking.items():  # mã đang giữ không có lệnh → GIỮ
        if row.get("held") and sym not in acted:
            tag = _held_tag(row)
            rows.append([f"{sym}{(' ' + tag) if tag else ''}", "GIỮ", "—", "—", "—",
                         _clip(_rule_note(row), reason_width)])

    rows.sort(key=lambda r: (_ACTION_ORDER.get(r[1], 5), -_parse_money(r[3])))
    verdict = _verdict(deploy, budget, bool(all_acts), res.get("macro", {}))
    if sell > 0:
        verdict += f" Kèm BÁN {_money(sell)}."
    table = _box(["Mã", "Hành động", "Lô", "Tiền", "% NS", "Tín hiệu / Lý do"],
                 rows, ["l", "l", "r", "r", "r", "l"])
    return table, verdict


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
            _num(r.get("rsi"), "{:.0f}"),
            _num(r.get("pe")), _num(r.get("pb")), _pct(r.get("roe")),
            str(r.get("action", "—")),
        ])
    return _box(["Mã", "Tín hiệu", "RSI", "P/E", "P/B", "ROE", "Khuyến nghị"],
                table_rows, ["l", "l", "r", "r", "r", "r", "l"])


def render_triggers(triggers: list[dict]) -> str:
    if not triggers:
        return "_Không có cảnh báo — danh mục ổn (không mã nào RSI≥70 / tập trung / thủng SMA50 / tin xấu)._"
    return "\n".join(f"- **{t['symbol']}**: " + "; ".join(t["reasons"]) for t in triggers)


_SENTIMENT_ICON = {"BULLISH": "🟢 tích cực", "BEARISH": "🔴 tiêu cực", "NEUTRAL": "⚪ trung tính"}


def render_macro(macro: dict) -> str:
    sig = macro.get("signal", "NEUTRAL")
    head = f"**Tâm lý vĩ mô (voz Điểm báo):** {_SENTIMENT_ICON.get(sig, sig)} · net {macro.get('net', 0):+d} · {macro.get('n', 0)} tin"
    titles = macro.get("titles") or []
    if not titles:
        return head
    return head + "\n" + "\n".join(f"> {t}" for t in titles)


def render_symbol_news(news_map: dict, title_width: int = 60) -> str:
    if not news_map:
        return "_Không lấy được tin per-symbol._"
    rows = []
    for sym, d in news_map.items():
        sig = d.get("signal", "NEUTRAL")
        icon = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪"}.get(sig, "⚪")
        senti = f"{icon} {d.get('net', 0):+d}" if d.get("n") else "—"
        latest = d.get("latest") or []
        if latest:
            headline = latest[0][0]
            src = latest[0][1]
            head = _clip(headline, title_width) + (f" ({src})" if src else "")
        else:
            head = "—"
        rows.append([sym, senti, str(d.get("n", 0)), head])
    return _box(["Mã", "Tâm lý", "#tin", "Tin gần nhất"], rows, ["l", "r", "r", "l"])


def strip_json(plan: str) -> str:
    """Bỏ khối ```json (chỉ dành cho paper auto-apply) + separator thừa khỏi bản hiển thị."""
    if not plan:
        return ""
    out = re.sub(r"```json.*?```", "", plan, flags=re.DOTALL | re.IGNORECASE)
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
                 macro: dict | None = None, news_map: dict | None = None) -> str:
    """Báo cáo NGÀY (markdown): vĩ mô + cảnh báo + quyết định/giải ngân + tin từng mã
    + xếp hạng cả rổ + phân tích chi tiết. Layout deterministic, render đẹp mọi viewer .md."""
    if "error" in res:
        return f"Lỗi daily: {res['error']}"
    table, verdict = _action_block(res)
    budget = _money(_budget(res))
    out = [f"# BÁO CÁO NGÀY {date} · rổ {res.get('group', '?')}", "",
           f"**Nguồn:** {res.get('mode', '?')} · **Ngân sách:** {budget}", ""]
    if macro:
        out += [render_macro(macro), ""]
    out += ["## 1. Cảnh báo danh mục", render_triggers(triggers), "",
            "## 2. Quyết định & giải ngân", f"**{verdict}**", "", table, ""]
    if news_map:
        out += ["## 3. Tin tức từng mã", render_symbol_news(news_map), ""]
    out += ["## 4. Xếp hạng cả rổ (rule-based)", render_ranking(res.get("ranking", []))]
    if res.get("errors"):
        out += ["", "_Mã lỗi dữ liệu (bỏ qua): " + ", ".join(res["errors"][:8]) + "_"]
    return "\n".join(out)
