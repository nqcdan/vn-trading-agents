"""Audit trail cho các lần chạy advise/recommend/watch.

Ghi mỗi run thành 1 file JSON (kèm .md tuỳ chọn) dưới ``reports/journal/``
để tra lại "tháng/tuần trước khuyên gì, ra sao". Journal hỏng không được
làm hỏng lệnh chính → mọi lỗi IO bị nuốt, chỉ in cảnh báo.

Tên file CỐ ĐỊNH theo ngày: ``{YYYY-MM-DD}-{cmd}.json`` (+ ``.md``). Chạy lại
cùng lệnh trong ngày → GHI ĐÈ, không đẻ file mới. Timestamp lần chạy cuối vẫn
nằm trong ``ts`` của JSON. Muốn giữ mọi lần chạy → xem git/backup thủ công.
"""

from __future__ import annotations

import datetime
import json
import os

_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports", "journal")


def record(cmd: str, payload: dict, summary_md: str = "") -> str:
    """Ghi 1 bản ghi run. Trả path file JSON (hoặc "" nếu ghi lỗi)."""
    try:
        os.makedirs(_ROOT, exist_ok=True)
        now = datetime.datetime.now()
        stem = f"{now:%Y-%m-%d}-{cmd}"  # cố định theo ngày → chạy lại ghi đè
        json_path = os.path.join(_ROOT, stem + ".json")
        rec = {"ts": now.isoformat(), "cmd": cmd, **payload}
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2, default=str)
        if summary_md:
            with open(os.path.join(_ROOT, stem + ".md"), "w", encoding="utf-8") as f:
                f.write(summary_md)
        return json_path
    except Exception as e:  # journal phụ trợ: không raise ra ngoài
        print(f"[journal] không ghi được: {e}")
        return ""
