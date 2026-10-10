"""Lệnh `crypto`: báo cáo BTC/ETH qua agent pipeline + danh mục thật (everyday asset_class=crypto).

Giá USD. Không TCBS; dùng full pipeline analyst→bull/bear→trader→risk (market profile crypto).
"""
from __future__ import annotations

from . import agents, crypto_data, market_refs, portfolio as pf

_ICON = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪", "BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪"}


def _parse_holdings(csv: str) -> dict:
    out: dict = {}
    for part in csv.split(","):
        if ":" in part:
            s, q = part.split(":", 1)
            out[s.strip().upper()] = float(q)
    return out


def run_crypto(symbols: list[str] | None = None, holdings_csv: str | None = None,
               cash: str | None = None, as_of: str | None = None) -> dict:
    syms = symbols or crypto_data.get_group_symbols_crypto()
    holdings, held = None, {}
    if holdings_csv:
        held = _parse_holdings(holdings_csv)
    else:
        try:
            holdings = pf.fetch_holdings("crypto")
            held = {h["symbol"].upper(): h.get("qty") for h in holdings}
        except pf.PortfolioError:
            holdings = None
    if cash is not None:
        budget, cash_info = float(cash), None
    else:
        try:
            cash_info = pf.fetch_cash(("bank",))
            budget = cash_info["total"]
        except pf.PortfolioError:
            budget, cash_info = None, None
    analyses = []
    for s in syms:
        try:
            a = agents.analyze(s, as_of=as_of, asset_class="crypto")
        except Exception as e:  # noqa: BLE001
            a = {"symbol": s.upper(), "error": f"{type(e).__name__}: {e}"}
        a["held_qty"] = held.get(s.upper())
        analyses.append(a)
    return {"symbols": syms, "holdings": holdings, "held": held, "budget": budget,
            "cash_info": cash_info, "ref": market_refs.crypto_usd(), "analyses": analyses}


def _fmt_usd(v) -> str:
    if v is None:
        return "—"
    return f"${v:,.2f}" if v < 100 else f"${v:,.0f}"


def render_crypto(res: dict, date: str) -> str:
    out = [f"# BÁO CÁO CRYPTO {date}", ""]
    if res.get("ref"):
        out += [f"**Giá tham chiếu:** {res['ref']}", ""]
    if res.get("budget") is not None:
        out += [f"**Ngân sách (ví bank):** {int(res['budget']):,}đ".replace(",", "."), ""]

    hold = res.get("holdings")
    if hold:
        out += ["## 1. Danh mục crypto hiện tại", "",
                "| Mã | SL | Giá vốn | Giá TT | P&L |", "| :-- | --: | --: | --: | --: |"]
        for h in hold:
            out.append(f"| {h['symbol']} | {h.get('qty')} | {_fmt_usd(h.get('costBasis'))} | "
                       f"{_fmt_usd(h.get('marketValue'))} | {h.get('pnlPct')}% |")
        out.append("")

    out += ["## 2. Tín hiệu & quyết định", "",
            "| Mã | Quyết định | Tín hiệu KT | RSI | Giá | SMA20/50 | Tỷ trọng đề xuất |",
            "| :-- | :-- | :-- | --: | --: | :-- | --: |"]
    for a in res["analyses"]:
        if "error" in a:
            out.append(f"| {a['symbol']} | ⚠️ lỗi | {a['error']} | | | | |")
            continue
        d = a["trader_decision"]
        ta = a["technical"]
        ind = a["indicators"]
        held_mark = " ◆" if a.get("held_qty") else ""
        sma = f"{ind.get('sma20')}/{ind.get('sma50')}"
        out.append(
            f"| {a['symbol']}{held_mark} | {_ICON.get(d['action'],'')} {d['action']} "
            f"({d.get('confidence','')}) | {_ICON.get(ta['signal'],'')} {ta['signal']} | "
            f"{ind.get('rsi14')} | {_fmt_usd(ind.get('close'))} | {sma} | "
            f"{a['risk'].get('target_weight')} |")
    out.append("")

    out += ["## 3. Phân tích từng coin", ""]
    for a in res["analyses"]:
        if "error" in a:
            continue
        d, ind = a["trader_decision"], a["indicators"]
        out += [f"### {a['symbol']} — {_ICON.get(d['action'],'')} {d['action']}", "",
                f"- Giá {_fmt_usd(ind.get('close'))} · RSI {ind.get('rsi14')} · "
                f"ret20d {ind.get('ret20d_pct')}% · vol20d {ind.get('vol20d_pct')}%",
                f"- Kỹ thuật: {a['technical']['signal']} — {'; '.join(a['technical']['notes'])}",
                f"- Lý do: {d.get('reason','')}",
                f"- Rủi ro: {a['risk'].get('note','')}"]
        deb = a.get("debate", {})
        if deb.get("bull") and a.get("llm"):
            out += [f"- BULL: {deb['bull']}", f"- BEAR: {deb['bear']}"]
        out.append("")

    out += ["_Máy chỉ gợi ý; crypto biến động mạnh, tự quyết lệnh. "
            "Dữ liệu OHLC: Binance (fallback CoinGecko)._"]
    return "\n".join(out)
