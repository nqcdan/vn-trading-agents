"""Render bảng quyết định deterministic từ kết quả `advise()`.

Không phụ thuộc LLM tự bịa layout: gộp ranking rule-based + actions (JSON đã parse)
+ ngân sách → 1 bảng cố định (Mã | Hành động | Lô | Tiền | % | Tín hiệu) + bảng chỉ số
+ dòng "giải ngân hay hold tiền". Phần diễn giải sâu để nguyên plan LLM/TCBS bên dưới.
"""
from __future__ import annotations

import re
import unicodedata


def _w(s: str) -> int:
    """Bề rộng hiển thị: chuẩn hoá NFC, bỏ combining marks (dấu tiếng Việt = 0 rộng)."""
    s = unicodedata.normalize("NFC", s)
    return sum(0 if unicodedata.combining(c) else 1 for c in s)


def _pad(s: str, width: int, align: str) -> str:
    gap = max(0, width - _w(s))
    return (" " * gap + s) if align == "r" else (s + " " * gap)

_ACTION_ORDER = {"MUA MỚI": 0, "GOM THÊM": 1, "GIỮ": 2, "GIẢM": 3, "BÁN": 4}
_LOT = 100


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


def _budget(res: dict) -> float | None:
    b = res.get("budget")
    if isinstance(b, (int, float)):
        return float(b)
    info = res.get("cash_info") or {}
    if isinstance(info.get("total"), (int, float)):
        return float(info["total"])
    m = re.search(r"([\d.,]{6,})", res.get("cash_txt", ""))  # lấy số dài đầu tiên
    if m:
        try:
            return float(m.group(1).replace(".", "").replace(",", ""))
        except ValueError:
            return None
    return None


def _box(headers: list[str], rows: list[list[str]], aligns: list[str]) -> str:
    cols = len(headers)
    widths = [_w(headers[i]) for i in range(cols)]
    for r in rows:
        for i in range(cols):
            widths[i] = max(widths[i], _w(r[i]))

    def _cell(txt: str, i: int) -> str:
        return _pad(txt, widths[i], aligns[i])

    def _line(l: str, m: str, r: str) -> str:
        return l + m.join("─" * (widths[i] + 2) for i in range(cols)) + r

    def _row(vals: list[str]) -> str:
        return "│ " + " │ ".join(_cell(vals[i], i) for i in range(cols)) + " │"

    out = [_line("┌", "┬", "┐"), _row(headers), _line("├", "┼", "┤")]
    out += [_row(r) for r in rows]
    out.append(_line("└", "┴", "┘"))
    return "\n".join(out)


def _classify(held: bool, act: str | None) -> str:
    if act == "SELL":
        return "BÁN"
    if act == "BUY":
        return "GOM THÊM" if held else "MUA MỚI"
    return "GIỮ"


def _rule_note(row: dict) -> str:
    """Tín hiệu rule-based gọn cho mã GIỮ (không có reason LLM)."""
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


def render(res: dict, reason_width: int = 46) -> str:
    if "error" in res:
        return f"Lỗi advise: {res['error']}"
    ranking = {r["symbol"].upper(): r for r in res.get("ranking", []) if "error" not in r}
    acts = {a["symbol"].upper(): a for a in res.get("actions", [])}
    budget = _budget(res)

    symbols = [s for s, r in ranking.items() if r.get("held")]
    symbols += [s for s in acts if s not in symbols]

    table_rows, deploy, sell_proceeds = [], 0.0, 0.0
    detail_rows = []
    for sym in symbols:
        row = ranking.get(sym, {})
        a = acts.get(sym)
        act = a["action"] if a else None
        label = _classify(bool(row.get("held")), act)

        if a and act in ("BUY", "SELL") and a.get("lots"):
            tien = a["lots"] * a["price"] * _LOT
            lots_s, tien_s = str(a["lots"]), _money(tien)
            pct_s = f"{tien / budget * 100:.1f}%" if budget else "—"
            if act == "BUY":
                deploy += tien
            else:
                sell_proceeds += tien
            reason = (a.get("reason") or "").strip().replace("\n", " ")
        else:
            lots_s = tien_s = pct_s = "—"
            reason = _rule_note(row)
        if _w(reason) > reason_width:
            reason = reason[: reason_width - 1] + "…"

        w = row.get("weight_pct")
        held_tag = f"◆{w:.0f}%" if isinstance(w, (int, float)) else ("◆" if row.get("held") else "")
        table_rows.append([f"{sym}{(' ' + held_tag) if held_tag else ''}",
                           label, lots_s, tien_s, pct_s, reason])
        detail_rows.append([sym, _money((row.get("close") or 0) * 1000) if row.get("close") else "—",
                            _num(row.get("rsi"), "{:.0f}"), _num(row.get("pe")),
                            _num(row.get("pb")),
                            f"{row['roe']:.0%}" if isinstance(row.get("roe"), (int, float)) else "—",
                            row.get("signal", "—")])

    table_rows.sort(key=lambda r: (_ACTION_ORDER.get(r[1], 5),
                                   -(_parse_money(r[3]))))

    macro = res.get("macro", {})
    macro_s = f"{macro.get('signal', '—')} (net {macro.get('net', 0)})"
    header = (f"=== Kế hoạch {res.get('group', '?')} | nguồn: {res.get('mode', '?')} "
              f"| vĩ mô voz: {macro_s} | ngân sách: {_money(budget)} ===")

    verdict = _verdict(deploy, budget, bool(acts), macro)

    out = [header, "", verdict, ""]
    out.append(_box(["Mã", "Hành động", "Lô", "Tiền", "% NS", "Tín hiệu / Lý do"],
                    table_rows, ["l", "l", "r", "r", "r", "l"]))
    out += ["", "Chỉ số chi tiết (rule-based vnstock — TCBS real-time xem phần phân tích dưới):"]
    detail_rows.sort(key=lambda r: r[0])
    out.append(_box(["Mã", "Giá", "RSI", "P/E", "P/B", "ROE", "Rule"],
                    detail_rows, ["l", "r", "r", "r", "r", "r", "l"]))
    if res.get("errors"):
        out += ["", "Mã lỗi dữ liệu (bỏ qua): " + ", ".join(res["errors"][:8])]
    return "\n".join(out)


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
    lean = "giải ngân phần lớn" if pct >= 60 else "giải ngân một phần, giữ đệm tiền mặt lớn" if pct >= 30 else "giải ngân thăm dò, phần lớn hold tiền"
    return (f"▶ QUYẾT ĐỊNH ĐỢT NÀY: GIẢI NGÂN {_money(deploy)} ({pct:.0f}%) · "
            f"giữ lại {_money(reserve)} ({100 - pct:.0f}%) — {lean}.")
