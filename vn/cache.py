"""Cache JSON theo ngày cho dữ liệu vnstock (giảm rate-limit)."""
from __future__ import annotations
import json
import os
import re
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent / ".cache"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _no_cache() -> bool:
    return os.environ.get("VN_NO_CACHE", "").strip().lower() not in ("", "0", "false", "no")


def _path(namespace: str, key: str, as_of: str | None) -> Path:
    day = as_of or date.today().isoformat()
    safe = _UNSAFE.sub("_", key)
    return _ROOT / day / namespace / f"{safe}.json"


def memoize(namespace: str, key: str, producer, as_of: str | None = None):
    p = _path(namespace, key, as_of)
    if not _no_cache() and p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    result = producer()
    if _no_cache():
        return result  # VN_NO_CACHE: bỏ qua cache hoàn toàn (không đọc, KHÔNG ghi)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass
    return result
