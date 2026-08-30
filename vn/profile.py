"""Nạp investor profile (PROFILE.md ở root repo) để inject vào prompt LLM."""
from __future__ import annotations
import os

_CACHE: str | None = None
_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "PROFILE.md")


def load_profile() -> str:
    """Nội dung PROFILE.md (rỗng nếu không có). Cache trong process."""
    global _CACHE
    if _CACHE is None:
        try:
            with open(_PATH, encoding="utf-8") as f:
                _CACHE = f.read().strip()
        except OSError:
            _CACHE = ""
    return _CACHE


def profile_system(base: str = "") -> str:
    """Ghép profile vào system prompt (để khuyến nghị hợp khẩu vị)."""
    prof = load_profile()
    if not prof:
        return base
    header = ("HỒ SƠ NĐT (khuyến nghị PHẢI hợp khẩu vị này):\n" + prof
              + "\n\nTuân thủ ràng buộc cứng của hồ sơ khi ra khuyến nghị.")
    return f"{base}\n\n{header}" if base else header
