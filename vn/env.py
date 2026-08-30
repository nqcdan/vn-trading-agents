"""Nạp .env ở root repo vào os.environ — stdlib, không thêm dependency.

Không override biến đã có sẵn trong môi trường (giống python-dotenv mặc định), nên
`FOO=bar ./run.py …` vẫn thắng .env. Gọi tự động khi import package `vn`.
"""
from __future__ import annotations
import os

_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")


def load_dotenv(path: str = _ENV_PATH) -> None:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key:
            os.environ.setdefault(key, val)
