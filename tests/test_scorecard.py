import json

import pandas as pd
import pytest

from vn import paper, scorecard


def _px(opens_closes):
    idx = pd.to_datetime(["2026-09-08", "2026-09-09", "2026-09-10"])
    return pd.DataFrame(opens_closes, columns=["open", "close"], index=idx)


def test_signal_stats_excess_vs_basket_from_next_open():
    sessions = pd.to_datetime(["2026-09-08", "2026-09-09", "2026-09-10"])
    prices = {
        "AAA": _px([(10, 10), (10, 11), (11, 12)]),   # +20% từ open 08/09
        "BBB": _px([(10, 10), (10, 9), (9, 8)]),      # -20%
    }
    journals = {"2026-09-07": {"ranking": [{"symbol": "AAA", "signal": "BUY"},
                                           {"symbol": "BBB", "signal": "SELL"}],
                               "actions": [{"action": "BUY", "symbol": "AAA"}]}}
    out = scorecard.signal_stats(journals, prices, sessions)[0]
    assert out["rule"]["BUY"] == [pytest.approx(20.0)]
    assert out["rule"]["SELL"] == [pytest.approx(-20.0)]
    assert out["llm"]["BUY"] == [pytest.approx(20.0)]
    assert scorecard.signal_stats(journals, prices, sessions)[5] == {"rule": {}, "llm": {}}


def test_health_flags_stale_fallback_and_frozen_budget():
    j = {
        "2026-09-08": {"mode": "tcbs-mcp", "budget": 100, "ranking": [{"symbol": "A", "close": 1.0}]},
        "2026-09-09": {"mode": "fallback-mcp-offline", "budget": 50, "ranking": [{"symbol": "A", "close": 1.1}]},
        "2026-09-10": {"mode": "tcbs-mcp", "budget": 50, "ranking": [{"symbol": "A", "close": 1.1}]},
    }
    h = scorecard.health(j)
    assert h["fallback"] == ["2026-09-09"]
    assert h["stale"] == ["2026-09-10"]
    assert h["budget_unchanged_since"] == "2026-09-09"


def test_load_journals_skips_weekend(tmp_path):
    for day in ("2026-10-09", "2026-10-11"):
        (tmp_path / f"{day}-daily.json").write_text(json.dumps({"ranking": []}))
    assert list(scorecard.load_journals(root=str(tmp_path))) == ["2026-10-09"]


def test_paper_apply_journal_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paper._save({"cash": 10_000_000, "positions": {}, "trades": []}, paper.BOOK_PATH)
    jd = tmp_path / "j"
    jd.mkdir()
    (jd / "2026-10-12-daily.json").write_text(json.dumps(
        {"actions": [{"action": "BUY", "symbol": "HPG", "lots": 1, "price": 20000.0}]}))
    out = paper.apply_journal("2026-10-12", journal_dir=str(jd))
    assert out["book"]["positions"]["HPG"]["qty"] == 100
    assert paper.apply_journal("2026-10-12", journal_dir=str(jd))["skipped"]
    assert paper._load()["positions"]["HPG"]["qty"] == 100
