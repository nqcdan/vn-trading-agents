"""Multi-agent VN — mô phỏng kiến trúc TradingAgents (analyst → bull/bear → trader → risk).

Chạy được KHÔNG cần API key (rule-based). Nếu có ANTHROPIC_API_KEY thì các agent
sẽ dùng LLM để lập luận + tranh luận bằng tiếng Việt.
"""
from __future__ import annotations
import json
import os
import textwrap

from . import vn_data, vn_market, vn_news
from .profile import profile_system

VN_MARKET_RULES = textwrap.dedent(
    """
    RÀNG BUỘC THỊ TRƯỜNG VN (bắt buộc tuân thủ khi khuyến nghị):
    - Biên độ giá/phiên: HOSE ±7%, HNX ±10%, UPCOM ±15%. Không kỳ vọng biến động vượt biên.
    - T+2: cổ/tiền về sau ~2 phiên. KHÔNG lướt sóng trong ngày (không mua-bán cùng mã 1 phiên).
    - Retail KHÔNG bán khống. Khuyến nghị "bearish" = BÁN hoặc ĐỨNG NGOÀI, không phải mở short.
    - Lô 100, thanh khoản midcap có thể mỏng → cân nhắc slippage.
    """
).strip()


import shutil
import subprocess

_DEFAULT_SYS = "Bạn là chuyên gia phân tích chứng khoán VN. Trả lời tiếng Việt, ngắn gọn."


def _backend() -> str:
    """api (ANTHROPIC_API_KEY) | claude-cli (subscription) | off. VN_LLM_BACKEND ép chọn."""
    forced = os.environ.get("VN_LLM_BACKEND", "auto").lower()
    if forced != "auto":
        return forced
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api"
    if shutil.which("claude"):
        return "claude-cli"
    return "off"


def _llm_available() -> bool:
    return _backend() in ("api", "claude-cli")


_CLI_SYS_GUARD = " Chỉ trả lời nội dung phân tích được hỏi. KHÔNG dùng công cụ. " \
                 "KHÔNG nhắc tới code, thư mục, hay môi trường chạy."
_NO_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep",
             "WebSearch", "WebFetch", "Task", "TodoWrite"]


def _llm_via_cli(prompt: str, system: str, timeout: int = 90) -> str:
    model = os.environ.get("VN_LLM_MODEL", "sonnet")
    cmd = ["claude", "-p", prompt, "--model", model,
           "--append-system-prompt", (system or _DEFAULT_SYS) + _CLI_SYS_GUARD,
           "--strict-mcp-config", "--disallowed-tools", *_NO_TOOLS]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       cwd="/tmp")  # /tmp: tránh nạp CLAUDE.md/MCP của project
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "claude cli failed")[:200])
    return r.stdout.strip()


def _llm(prompt: str, system: str = "", max_tokens: int = 700) -> str:
    backend = _backend()
    if backend == "claude-cli":
        return _llm_via_cli(prompt, system)
    import anthropic
    client = anthropic.Anthropic()
    model = os.environ.get("VN_LLM_MODEL", "claude-sonnet-4-6")
    msg = client.messages.create(
        model=model, max_tokens=max_tokens,
        system=system or _DEFAULT_SYS,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


# ---------- Analysts ----------

def technical_analyst(ind: dict) -> dict:
    score, notes = 0, []
    c, s20, s50 = ind.get("close"), ind.get("sma20"), ind.get("sma50")
    if s20 and c:
        if c > s20:
            score += 1; notes.append("giá > SMA20 (xu hướng ngắn hạn tăng)")
        else:
            score -= 1; notes.append("giá < SMA20")
    if s20 and s50:
        if s20 > s50:
            score += 1; notes.append("SMA20 > SMA50 (golden alignment)")
        else:
            score -= 1; notes.append("SMA20 < SMA50 (death alignment)")
    rsi = ind.get("rsi14")
    if rsi is not None:
        if rsi > 70:
            score -= 1; notes.append(f"RSI {rsi} quá mua")
        elif rsi < 30:
            score += 1; notes.append(f"RSI {rsi} quá bán (khả năng hồi)")
    signal = "BULLISH" if score > 0 else "BEARISH" if score < 0 else "NEUTRAL"
    return {"agent": "technical", "signal": signal, "score": score, "notes": notes}


def fundamental_analyst(fund: dict) -> dict:
    if "error" in fund or "note" in fund:
        return {"agent": "fundamental", "signal": "NEUTRAL", "score": 0,
                "notes": [fund.get("error") or fund.get("note")]}
    score, notes = 0, []
    roe = fund.get("roe")
    if roe is not None:
        if roe > 0.15:
            score += 1; notes.append(f"ROE {roe:.0%} tốt")
        elif roe < 0.05:
            score -= 1; notes.append(f"ROE {roe:.0%} thấp")
    pe = fund.get("pe")
    if pe is not None:
        if 0 < pe < 12:
            score += 1; notes.append(f"P/E {pe} rẻ")
        elif pe > 25:
            score -= 1; notes.append(f"P/E {pe} cao")
    de = fund.get("debt_equity")
    if de is not None and de > 2:
        score -= 1; notes.append(f"D/E {de} đòn bẩy cao")
    signal = "BULLISH" if score > 0 else "BEARISH" if score < 0 else "NEUTRAL"
    return {"agent": "fundamental", "signal": signal, "score": score, "notes": notes}


def sentiment_analyst(symbol: str, limit: int = 12) -> dict:
    items = vn_news.get_news(symbol, limit=limit)
    base = vn_news.score_sentiment(items)
    headlines = [n["title"] for n in items[:6]]
    if _llm_available() and items:
        joined = "\n".join(f"- {h}" for h in headlines)
        summ = _llm(
            f"Các tiêu đề tin gần đây về mã {symbol} (nguồn CafeF + công bố DN):\n{joined}\n"
            "Đánh giá tâm lý tin tức 1 câu và kết luận BULLISH/BEARISH/NEUTRAL.",
            max_tokens=200,
        )
        base["llm_summary"] = summ.strip()
    base["agent"] = "sentiment"
    base["headlines"] = headlines
    return base


# ---------- Researcher debate ----------

def bull_bear_debate(symbol: str, ta: dict, fa: dict) -> dict:
    context = f"Kỹ thuật: {ta['signal']} ({'; '.join(ta['notes'])}). " \
              f"Cơ bản: {fa['signal']} ({'; '.join(fa['notes'])})."
    if _llm_available():
        bull = _llm(f"Mã {symbol}. {context}\nĐóng vai BULL researcher: nêu 2-3 luận điểm MUA mạnh nhất.")
        bear = _llm(f"Mã {symbol}. {context}\nĐóng vai BEAR researcher: nêu 2-3 rủi ro/lý do TRÁNH mạnh nhất.")
    else:
        bull = "Điểm cộng: " + "; ".join(ta["notes"] + fa["notes"]) or "không rõ"
        bear = "Rủi ro: biên độ VN hẹp, thanh khoản, và các tín hiệu trái chiều nếu có."
    return {"bull": bull.strip(), "bear": bear.strip()}


# ---------- Trader ----------

def trader(symbol: str, ta: dict, fa: dict, debate: dict, se: dict | None = None) -> dict:
    total = ta["score"] + fa["score"] + (se["score"] if se else 0)
    if _llm_available():
        raw = _llm(
            f"Mã {symbol}. Tổng hợp:\n- BULL: {debate['bull']}\n- BEAR: {debate['bear']}\n"
            f"- Điểm kỹ thuật {ta['score']}, cơ bản {fa['score']}"
            + (f", tin tức {se['score']} ({se['signal']})" if se else "") + f".\n{VN_MARKET_RULES}\n"
            "Ra quyết định cuối (hợp khẩu vị hồ sơ NĐT). CHỈ trả JSON: "
            '{\"action\":\"BUY|HOLD|SELL\",\"confidence\":0-1,\"reason\":\"...\"}',
            system=profile_system(_DEFAULT_SYS),
            max_tokens=300,
        )
        try:
            start, end = raw.find("{"), raw.rfind("}")
            d = json.loads(raw[start:end + 1])
            d["action"] = d.get("action", "HOLD").upper()
            return d
        except Exception:
            pass
    action = "BUY" if total >= 2 else "SELL" if total <= -2 else "HOLD"
    conf = min(1.0, abs(total) / 4)
    return {"action": action, "confidence": round(conf, 2),
            "reason": f"tổng điểm tín hiệu = {total} (rule-based)"}


# ---------- Risk manager ----------

def macro_mood() -> dict:
    """Tâm lý thị trường vĩ mô từ voz 'Điểm báo' (cộng đồng retail)."""
    m = vn_news.score_sentiment(vn_news.fetch_voz())
    m["agent"] = "macro"
    return m


def risk_manager(decision: dict, ind: dict, macro: dict | None = None) -> dict:
    vol = ind.get("vol20d_pct") or 2.0
    base = decision.get("confidence", 0.3)
    # Kelly-lite: rủi ro cao → giảm tỷ trọng
    weight = max(0.0, min(0.3, base * (2.0 / max(vol, 1.0))))
    note = f"vol20d={vol}%"
    if macro and macro.get("net", 0) <= -4:
        weight *= 0.7
        note += f" | macro risk-off (voz net {macro['net']}) → haircut 30%"
    if decision["action"] != "BUY":
        weight = 0.0
    approved = decision["action"]
    if decision["action"] == "BUY" and weight < 0.03:
        approved = "HOLD"
    return {"approved_action": approved, "target_weight": round(weight, 3),
            "note": f"{note} → tỷ trọng đề xuất {round(weight*100,1)}% NAV"}


# ---------- Orchestrator ----------

def analyze(symbol: str, as_of: str | None = None) -> dict:
    ind = vn_data.get_indicators(symbol, as_of=as_of)
    fund = vn_data.get_fundamentals(symbol)
    ta = technical_analyst(ind)
    fa = fundamental_analyst(fund)
    se = sentiment_analyst(symbol)
    macro = macro_mood()
    debate = bull_bear_debate(symbol, ta, fa)
    decision = trader(symbol, ta, fa, debate, se)
    risk = risk_manager(decision, ind, macro)
    return {
        "symbol": symbol.upper(), "exchange": vn_market.detect_exchange(symbol),
        "price_limit_pct": round(vn_market.price_limit(symbol) * 100, 1),
        "indicators": ind, "fundamentals": fund,
        "technical": ta, "fundamental": fa, "sentiment": se, "macro": macro,
        "debate": debate, "trader_decision": decision, "risk": risk,
        "llm": _llm_available(),
    }
