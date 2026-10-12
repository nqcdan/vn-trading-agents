"""Scorecard hiệu suất tín hiệu: đối chiếu khuyến nghị trong journal daily với giá thực tế sau đó.

Vào lệnh = giá mở cửa phiên kế tiếp sau ngày báo cáo (đặt LO sáng hôm sau), đo lợi nhuận
vượt trội so với trung bình đều cả rổ cùng kỳ. Giá lấy lại từ OHLCV (đã điều chỉnh chia
tách/cổ tức) — không dùng `close` lưu trong journal vì không điều chỉnh.
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import statistics as st
import time

import pandas as pd

from . import cache, paper, vn_data, vn_market

_JOURNAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports", "journal")
HORIZONS = (5, 10, 0)  # 0 = đến phiên gần nhất
SIGNALS = ("BUY", "BUY-WAIT", "HOLD", "SELL")


def load_journals(since: str | None = None, root: str = _JOURNAL) -> dict[str, dict]:
    out = {}
    for f in sorted(glob.glob(os.path.join(root, "*-daily.json"))):
        day = os.path.basename(f)[:10]
        if since and day < since:
            continue
        if _dt.date.fromisoformat(day).weekday() >= 5:
            continue  # chạy tay cuối tuần = trùng dữ liệu thứ 6
        with open(f, encoding="utf-8") as fh:
            out[day] = json.load(fh)
    return out


def _history(symbol: str, start: str, end: str, throttle: float) -> pd.DataFrame | None:
    def _fetch():
        time.sleep(throttle)  # vnstock guest: 20 req/phút, vượt là kill process
        df = vn_data.get_ohlcv(symbol, start, end)
        return [{"date": str(d.date()), "open": float(o), "high": float(h), "low": float(lo), "close": float(c)}
                for d, o, h, lo, c in zip(df["date"], df["open"], df["high"], df["low"], df["close"])]
    try:
        rows = cache.memoize("ohlcv2", f"{symbol}_{start}_{end}", _fetch, as_of=end)
    except Exception:
        return None
    if not rows:
        return None
    return pd.DataFrame(rows).assign(date=lambda d: pd.to_datetime(d["date"])).set_index("date")


def fetch_prices(symbols: set[str], start: str, end: str, throttle: float = 3.3) -> dict[str, pd.DataFrame]:
    out = {}
    for s in sorted(symbols):
        df = _history(s, start, end, throttle)
        if df is not None and not df.empty:
            out[s] = df
    return out


def _ret(df: pd.DataFrame | None, d0, d1) -> float | None:
    if df is None or d0 not in df.index or d1 not in df.index:
        return None
    o = df.at[d0, "open"]
    return (df.at[d1, "close"] / o - 1) * 100 if o else None


def signal_stats(journals: dict[str, dict], prices: dict[str, pd.DataFrame], sessions: pd.DatetimeIndex) -> dict:
    """{horizon: {"rule": {signal: [excess…]}, "llm": {action: [excess…]}}}"""
    out = {}
    for h in HORIZONS:
        rule: dict[str, list[float]] = {}
        llm: dict[str, list[float]] = {}
        for day, d in journals.items():
            nxt = sessions[sessions > pd.Timestamp(day)]
            if not len(nxt):
                continue
            i = sessions.get_loc(nxt[0])
            j = len(sessions) - 1 if h == 0 else i + h
            if j >= len(sessions) or j <= i:
                continue
            d0, d1 = sessions[i], sessions[j]
            basket = [r for r in (_ret(prices.get(x["symbol"]), d0, d1) for x in d["ranking"]) if r is not None]
            if not basket:
                continue
            bm = st.mean(basket)
            for x in d["ranking"]:
                r = _ret(prices.get(x["symbol"]), d0, d1)
                if r is not None and x.get("signal"):
                    rule.setdefault(x["signal"], []).append(r - bm)
            for a in d.get("actions") or []:
                r = _ret(prices.get(a["symbol"]), d0, d1)
                if r is not None:
                    llm.setdefault(str(a["action"]).upper(), []).append(r - bm)
        out[h] = {"rule": rule, "llm": llm}
    return out


def summarize(v: list[float]) -> dict:
    return {"n": len(v), "mean": st.mean(v), "median": st.median(v),
            "hit": sum(x > 0 for x in v) / len(v)}


def health(journals: dict[str, dict]) -> dict:
    days = sorted(journals)
    fallback = [d for d in days if str(journals[d].get("mode", "")).startswith("fallback")]
    stale = []
    for a, b in zip(days, days[1:]):
        pa = {r["symbol"]: r.get("close") for r in journals[a]["ranking"]}
        pb = {r["symbol"]: r.get("close") for r in journals[b]["ranking"]}
        common = [s for s in pa if s in pb and pa[s]]
        if common and all(pa[s] == pb[s] for s in common):
            stale.append(b)
    budgets = [journals[d].get("budget") for d in days]
    return {"days": len(days), "first": days[0] if days else None, "last": days[-1] if days else None,
            "fallback": fallback, "stale": stale,
            "budget_unchanged_since": _unchanged_since(days, budgets)}


def _unchanged_since(days: list[str], vals: list) -> str | None:
    if len(vals) < 2 or vals[-1] is None:
        return None
    k = len(vals) - 1
    while k > 0 and vals[k - 1] == vals[-1]:
        k -= 1
    return days[k] if k < len(vals) - 1 else None


def _nav(positions: dict, cash: float, prices: dict[str, pd.DataFrame]) -> tuple[float, list[str]]:
    nav, missing = cash, []
    for sym, pos in positions.items():
        df = prices.get(sym)
        if df is None:
            missing.append(sym)
            continue
        nav += int(pos["qty"]) * float(df["close"].iloc[-1]) * 1000
    return nav, missing


def paper_curve(prices: dict[str, pd.DataFrame]) -> dict | None:
    """Định giá sổ paper bằng giá đã tải (không gọi thêm API → không dính rate-limit)."""
    try:
        book = paper._load()
    except Exception:
        return None
    start = book.get("created", "")[:10]
    snap = book.get("init_snapshot", {})
    trades = book.get("trades", [])
    injected = sum(float(i.get("amount", 0)) for i in book.get("cash_injections", []))
    agent, m1 = _nav(book.get("positions", {}), float(book["cash"]), prices)
    hold, m2 = _nav(snap.get("positions", {}), float(snap.get("cash", 0)) + injected, prices)
    vni = prices.get("VNINDEX")
    vni_ret = None
    if vni is not None and start:
        after = vni[vni.index > pd.Timestamp(start)]
        if len(after):
            vni_ret = (vni["close"].iloc[-1] / after["open"].iloc[0] - 1) * 100
    return {"start": start, "agent_nav": agent, "hold_nav": hold,
            "edge_pct": (agent / hold - 1) * 100 if hold else None,
            "vnindex_ret": vni_ret, "trades": len(trades),
            "fees": sum(float(t.get("fee", 0)) + float(t.get("tax", 0)) for t in trades),
            "last_trade": trades[-1]["ts"][:10] if trades else "",
            "missing": sorted(set(m1 + m2))}


def decisions(journals: dict[str, dict], prices: dict[str, pd.DataFrame], sessions: pd.DatetimeIndex) -> list[dict]:
    """Mục 3 từng báo cáo: đặt LO đúng giá báo cáo ở phiên kế tiếp → khớp không, lời/lỗ tới phiên gần nhất.

    BUY khớp nếu low ≤ giá LO (giá vào = min(open, LO)); SELL khớp nếu high ≥ giá LO (giá ra = max(open, LO)).
    BUY: lãi/lỗ nếu bán hôm nay (đã trừ phí/thuế/trượt giá). SELL: phần tránh được = tiền bán − giá trị nếu giữ đến nay.
    """
    out = []
    last = sessions[-1]
    for day, d in journals.items():
        nxt = sessions[sessions > pd.Timestamp(day)]
        upto = sessions[sessions <= pd.Timestamp(day)]
        raw = {r["symbol"]: r.get("close") for r in d.get("ranking", [])}
        for a in d.get("actions") or []:
            act = str(a.get("action", "")).upper()
            if act not in ("BUY", "SELL"):
                continue
            row = {"day": day, "action": act, "symbol": a["symbol"], "lots": int(a.get("lots") or 0),
                   "lo": float(a.get("price") or 0), "filled": None}
            out.append(row)
            df = prices.get(a["symbol"])
            if not len(nxt) or df is None or nxt[0] not in df.index or not row["lots"] or not row["lo"]:
                continue
            # Giá trong báo cáo chưa điều chỉnh; OHLCV đã điều chỉnh cổ tức cổ phiếu/thưởng → quy LO về cùng hệ.
            factor = 1.0
            if len(upto) and upto[-1] in df.index and raw.get(a["symbol"]):
                f = float(df.at[upto[-1], "close"]) / float(raw[a["symbol"]])
                if abs(f - 1) > 0.05:
                    factor = f
            row["adjusted"] = factor != 1.0
            bar = df.loc[nxt[0]] * 1000 / factor
            cur = float(df["close"].iloc[-1]) * 1000 / factor
            shares = row["lots"] * vn_market.LOT_SIZE
            if act == "BUY":
                row["filled"] = bool(bar["low"] <= row["lo"])
                fill = min(bar["open"], row["lo"]) if row["filled"] else float(bar["open"])
                pnl = vn_market.sell_proceeds(cur, shares) - vn_market.buy_cost(fill, shares)
                capital = vn_market.buy_cost(fill, shares)
            else:
                row["filled"] = bool(bar["high"] >= row["lo"])
                fill = max(bar["open"], row["lo"]) if row["filled"] else float(bar["open"])
                pnl = vn_market.sell_proceeds(fill, shares) - cur * shares
                capital = cur * shares
            row.update(fill=float(fill), cur=float(df["close"].iloc[-1]) * 1000, pnl=float(pnl), pct=float(pnl / capital * 100),
                       as_of=str(last.date()))
    return out


def build(since: str | None = None, throttle: float = 3.3) -> dict:
    journals = load_journals(since)
    if not journals:
        return {"error": "không có journal daily nào"}
    start = (_dt.date.fromisoformat(min(journals)) - _dt.timedelta(days=7)).isoformat()
    end = _dt.date.today().isoformat()
    syms = {r["symbol"] for d in journals.values() for r in d["ranking"]}
    syms |= {a["symbol"] for d in journals.values() for a in d.get("actions") or []}
    try:
        book = paper._load()
        syms |= set(book.get("positions", {})) | set(book.get("init_snapshot", {}).get("positions", {}))
    except Exception:
        pass
    prices = fetch_prices(syms | {"VNINDEX"}, start, end, throttle)
    ref = prices.get("VNINDEX")
    if ref is None:
        return {"error": "không lấy được lịch phiên (VNINDEX)"}
    sessions = ref.index
    first = sessions[sessions > pd.Timestamp(min(journals))]
    basket_ret = None
    if len(first):
        rs = [r for r in (_ret(prices.get(s), first[0], sessions[-1]) for s in syms) if r is not None]
        basket_ret = st.mean(rs) if rs else None
    vni_ret = _ret(ref, first[0], sessions[-1]) if len(first) else None
    return {"since": min(journals), "until": str(sessions[-1].date()),
            "stats": signal_stats(journals, prices, sessions),
            "decisions": decisions(journals, prices, sessions),
            "basket_ret": basket_ret, "vnindex_ret": vni_ret,
            "health": health(journals), "paper": paper_curve(prices),
            "missing": sorted(syms - set(prices))}


def _row(label: str, v: list[float]) -> str:
    s = summarize(v)
    return f"| {label} | {s['n']} | {s['mean']:+.2f} | {s['median']:+.2f} | {s['hit']:.0%} |"


def _vnd(x: float) -> str:
    return f"{x / 1e6:+,.2f}tr"


def render_decisions(rows: list[dict]) -> list[str]:
    done = [r for r in rows if "pnl" in r]
    if not done:
        return []
    L = [f"## Mục 3 — nếu đặt LO đúng giá báo cáo ở phiên kế tiếp (tới {done[0]['as_of']})", ""]
    buys = [r for r in done if r["action"] == "BUY" and r["filled"]]
    sells = [r for r in done if r["action"] == "SELL" and r["filled"]]
    miss = [r for r in done if not r["filled"]]
    tot = sum(r["pnl"] for r in buys + sells)
    if buys:
        L.append(f"- **MUA khớp {len(buys)} lệnh:** lãi/lỗ {_vnd(sum(r['pnl'] for r in buys))} "
                 f"· {sum(r['pnl'] > 0 for r in buys)}/{len(buys)} lệnh có lãi (đã trừ phí, thuế)")
    if sells:
        L.append(f"- **BÁN khớp {len(sells)} lệnh:** so với giữ đến nay {_vnd(sum(r['pnl'] for r in sells))} "
                 f"(dương = bán đúng)")
    if buys:
        cap = sum(r["pnl"] / r["pct"] * 100 for r in buys if r["pct"])
        L.append(f"- **Tổng giá trị các lệnh MUA (cộng dồn mọi báo cáo):** {cap / 1e6:,.1f}tr → lợi suất {sum(r['pnl'] for r in buys) / cap * 100:+.2f}%")
    L.append(f"- **Tổng nếu làm theo mọi lệnh khớp:** {_vnd(tot)} · {len(miss)} lệnh LO không khớp phiên kế tiếp")
    L += ["", "| Báo cáo | Lệnh | Mã | Lô | LO | Khớp | Giá nay | Lãi/lỗ | % |",
          "| :-- | :-- | :-- | --: | --: | :-- | --: | --: | --: |"]
    by_day: dict[str, float] = {}
    note = any(r.get("adjusted") for r in done)
    for r in done:
        if r["filled"]:
            by_day[r["day"]] = by_day.get(r["day"], 0.0) + r["pnl"]
        sym = r["symbol"] + ("*" if r.get("adjusted") else "")
        L.append(f"| {r['day']} | {'MUA' if r['action'] == 'BUY' else 'BÁN'} | {sym} | {r['lots']} "
                 f"| {r['lo']:,.0f} | {'✓ ' + format(r['fill'], ',.0f') if r['filled'] else '✗ (mở ' + format(r['fill'], ',.0f') + ')'} "
                 f"| {r['cur']:,.0f} | {_vnd(r['pnl']) if r['filled'] else '—'} | {r['pct']:+.1f}% |")
    if note:
        L += ["", "\\* Mã có chia cổ tức cổ phiếu/thưởng sau báo cáo: Khớp tính theo giá cũ, Giá nay là giá thực tế, "
              "lãi/lỗ đã tính cả số cổ phiếu được chia."]
    by_sym: dict[tuple[str, str], list[float]] = {}
    for r in done:
        if r["filled"]:
            by_sym.setdefault((r["symbol"], r["action"]), []).append(r["pnl"])
    L += ["", "| Mã | Lệnh | Số lệnh khớp | Lãi/lỗ |", "| :-- | :-- | --: | --: |"]
    L += [f"| {k[0]} | {'MUA' if k[1] == 'BUY' else 'BÁN'} | {len(v)} | {_vnd(sum(v))} |"
          for k, v in sorted(by_sym.items(), key=lambda kv: -sum(kv[1]))]
    L += ["", "| Báo cáo | Lãi/lỗ cả mục 3 (lệnh khớp) |", "| :-- | --: |"]
    L += [f"| {d} | {_vnd(v)} |" for d, v in sorted(by_day.items())]
    L.append("")
    return L


def render(res: dict) -> str:
    if "error" in res:
        return f"# Scorecard tín hiệu\n\nLỗi: {res['error']}\n"
    L = [f"# Scorecard tín hiệu vn-trading-agents · {res['since']} → {res['until']}", ""]
    if res["vnindex_ret"] is not None:
        L.append(f"**Thị trường cùng kỳ:** VNINDEX {res['vnindex_ret']:+.2f}% · "
                 f"rổ đều {res['basket_ret']:+.2f}%")
        L.append("")
    names = {5: "5 phiên", 10: "10 phiên", 0: f"đến {res['until']}"}
    for h in HORIZONS:
        block = res["stats"][h]
        if not block["rule"] and not block["llm"]:
            continue
        L += [f"## Vượt trội so với rổ — {names[h]}", "",
              "| Tín hiệu | n | TB (pp) | Trung vị (pp) | Tỉ lệ thắng rổ |",
              "| :-- | --: | --: | --: | --: |"]
        for g in SIGNALS:
            if g in block["rule"]:
                L.append(_row(f"rule {g}", block["rule"][g]))
        for g, v in sorted(block["llm"].items()):
            L.append(_row(f"LLM {g}", v))
        L.append("")
    L += render_decisions(res.get("decisions") or [])
    L.append("Đọc bảng: BUY tốt khi TB > 0, SELL tốt khi TB < 0. Mỗi mã lặp tín hiệu nhiều ngày liền "
             "nên các quan sát không độc lập — n thật nhỏ hơn nhiều so với con số hiển thị.")
    L.append("")
    p = res.get("paper")
    if p:
        L += ["## Sổ paper", "",
              f"- Agent: {p['agent_nav']:,.0f}đ · Giữ nguyên: {p['hold_nav']:,.0f}đ · "
              f"chênh {p['edge_pct']:+.2f}%",
              f"- Từ {p['start']}: VNINDEX " + (f"{p['vnindex_ret']:+.2f}%" if p["vnindex_ret"] is not None else "—")
              + f" · {p['trades']} lệnh · phí+thuế {p['fees']:,.0f}đ · lệnh cuối {p['last_trade'] or '—'}"]
        if p["missing"]:
            L.append(f"- Thiếu giá (bỏ khỏi NAV): {', '.join(p['missing'])}")
        L.append("")
    h = res["health"]
    warn = []
    if h["fallback"]:
        warn.append(f"Chạy fallback (không TCBS): {', '.join(h['fallback'])}")
    if h["stale"]:
        warn.append(f"Giá trùng phiên trước (dữ liệu cũ): {', '.join(h['stale'])}")
    if h["budget_unchanged_since"]:
        warn.append(f"Ngân sách tiền mặt không đổi từ {h['budget_unchanged_since']} — lệnh thật có được đặt không?")
    if res.get("missing"):
        warn.append(f"Không lấy được giá: {', '.join(res['missing'])}")
    L += ["## Sức khoẻ pipeline", "", f"- {h['days']} báo cáo ({h['first']} → {h['last']})"]
    L += [f"- {w}" for w in warn]
    return "\n".join(L) + "\n"


def save(md: str) -> str:
    d = os.path.join(os.path.dirname(_JOURNAL), "scorecard")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{_dt.date.today():%Y-%m-%d}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return path
