"""Audit trail cho các lần chạy advise/recommend/watch.

Ghi mỗi run thành 1 file .md dưới ``reports/journal/`` (không JSON)
để tra lại "tháng/tuần trước khuyên gì, ra sao". Journal hỏng không được
làm hỏng lệnh chính → mọi lỗi IO bị nuốt, chỉ in cảnh báo.

Tên file CỐ ĐỊNH theo ngày: ``{YYYY-MM-DD}-{cmd}.md``. Chạy lại
cùng lệnh trong ngày → GHI ĐÈ, không đẻ file mới. Timestamp lần chạy cuối vẫn
nằm trong ``ts`` của JSON. Muốn giữ mọi lần chạy → xem git/backup thủ công.
"""

from __future__ import annotations

import datetime
import os

_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports", "journal")


def record(cmd: str, payload: dict, summary_md: str = "") -> str:
    """Chỉ lưu báo cáo .md (không JSON). Trả path file .md, "" nếu không ghi."""
    if not summary_md:
        return ""
    try:
        os.makedirs(_ROOT, exist_ok=True)
        stem = f"{datetime.datetime.now():%Y-%m-%d}-{cmd}"  # cố định theo ngày → chạy lại ghi đè
        path = os.path.join(_ROOT, stem + ".md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(summary_md)
        return path
    except Exception as e:  # journal phụ trợ: không raise ra ngoài
        print(f"[journal] không ghi được: {e}")
        return ""
