"""Cô lập cache: mọi test ghi/đọc cache vào tmp, không đụng `.cache` thật của repo."""
import pytest

from vn import cache


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_ROOT", tmp_path / ".cache")
