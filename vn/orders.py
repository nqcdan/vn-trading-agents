"""Phiếu lệnh buổi sáng: lấy bảng "Lệnh đặt cụ thể" của báo cáo daily gần nhất → text gọn gửi Telegram (không LLM)."""
from __future__ import annotations

import datetime as _dt
import glob
import os

_JOURNAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports", "journal")


def latest_report(before: str, root: str = _JOURNAL) -> str | None:
    files = sorted(f for f in glob.glob(os.path.join(root, "*-daily.md")) if os.path.basename(f)[:10] < before)
    return files[-1] if files else None


def order_rows(md: str) -> list[list[str]]:
    lines = md.split("\n")
    try:
        i = next(k for k, l in enumerate(lines) if l.startswith("**Lệnh đặt cụ thể**"))
    except StopIteration:
        return []
    rows = []
    for l in lines[i + 1:]:
        if l.startswith("|"):
            rows.append([c.strip() for c in l.strip().strip("|").split("|")])
        elif rows:
            break
    return rows[2:]


def morning_text(today: str | None = None, root: str = _JOURNAL) -> str:
    today = today or _dt.date.today().isoformat()
    path = latest_report(today, root)
    if not path:
        return f"🧾 Lệnh {today}: chưa có báo cáo daily nào."
    day = os.path.basename(path)[:10]
    with open(path, encoding="utf-8") as f:
        md = f.read()
    rows = order_rows(md)
    head = f"🧾 Lệnh đặt trước 9:00 hôm nay ({today}) — theo báo cáo tối {day}"
    if not rows:
        return f"{head}\nKhông có lệnh mua/bán. Giữ nguyên danh mục."
    out = [head, "Lệnh LO, đặt sẵn trước giờ mở cửa; không đuổi giá trong phiên.", ""]
    for r in rows:
        num, side, sym, qty, price, money, left, when = r[:8]
        line = f"{num}. {side} {sym} {qty} cp @ {price} — {money}đ"
        if left not in ("", "—"):
            line += f" (còn {left})"
        out.append(line + f"\n   {when}")
    tail = next((l for l in md.split("\n") if l.startswith("Tổng mua ")), "")
    if tail:
        out += ["", tail]
    if any("⚠" in r[6] for r in rows):
        out.append("⚠ Thiếu tiền cho lệnh đánh dấu: chờ tiền bán về, ứng trước, hoặc bỏ lệnh đó.")
    return "\n".join(out)
