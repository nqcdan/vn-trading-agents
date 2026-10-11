"""Per-tier LLM model+backend (port upstream #1440 sang lớp VN).

quick tier (analyst/debate) vs deep tier (trader) chạy model/backend riêng;
tier unset → fallback về VN_LLM_MODEL / VN_LLM_BACKEND (back-compat tuyệt đối).
"""
import pytest

from vn import agents

_LLM_ENV = [
    "VN_LLM_BACKEND", "VN_LLM_MODEL",
    "VN_QUICK_BACKEND", "VN_DEEP_BACKEND",
    "VN_QUICK_MODEL", "VN_DEEP_MODEL",
    "ANTHROPIC_API_KEY",
]


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch):
    for k in _LLM_ENV:
        monkeypatch.delenv(k, raising=False)


# ---- model resolution ----

def test_model_fallback_to_single_var(monkeypatch):
    monkeypatch.setenv("VN_LLM_MODEL", "sonnet")
    assert agents._resolve_model("quick", "claude-cli") == "sonnet"
    assert agents._resolve_model("deep", "claude-cli") == "sonnet"


def test_model_tier_override(monkeypatch):
    monkeypatch.setenv("VN_LLM_MODEL", "sonnet")
    monkeypatch.setenv("VN_DEEP_MODEL", "opus")
    assert agents._resolve_model("quick", "claude-cli") == "sonnet"   # fallback
    assert agents._resolve_model("deep", "claude-cli") == "opus"      # override


def test_model_default_when_nothing_set(monkeypatch):
    assert agents._resolve_model("quick", "claude-cli") == "sonnet"
    assert agents._resolve_model("deep", "api") == "claude-sonnet-4-6"


# ---- backend resolution ----

def test_backend_tier_override(monkeypatch):
    monkeypatch.setenv("VN_LLM_BACKEND", "claude-cli")
    monkeypatch.setenv("VN_DEEP_BACKEND", "api")
    assert agents._backend("quick") == "claude-cli"   # fallback VN_LLM_BACKEND
    assert agents._backend("deep") == "api"            # tier override


def test_backend_no_tier_backcompat(monkeypatch):
    monkeypatch.setenv("VN_LLM_BACKEND", "claude-cli")
    assert agents._backend() == "claude-cli"
    assert agents._backend("quick") == "claude-cli"


def test_backend_auto_detect(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert agents._backend("deep") == "api"
