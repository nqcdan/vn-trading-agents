"""Hiệu suất lệnh mục 3 "Quyết định & giải ngân" của từng báo cáo daily (đọc thẳng file .md trong journal).

Giá thực tế lấy lại từ OHLCV đã điều chỉnh cổ tức/chia tách; giá trong báo cáo (Giá LO, cột Giá mục xếp hạng)
là giá chưa điều chỉnh → quy về cùng hệ trước khi so.
"""
from __future__ import annotations

import datetime as _dt
import glob
import re
import os
import time

import pandas as pd

from . import cache, vn_data, vn_market

_JOURNAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports", "journal")


_ACTIONS = {"MUA MỚI": "BUY", "GOM THÊM": "BUY", "BÁN": "SELL"}


def _num(x: str) -> float | None:
    x = x.strip().replace(",", "")
    try:
        return float(x)
    except ValueError:
        return None


def _table(lines: list[str], title: str) -> list[list[str]]:
    """Các dòng dữ liệu của bảng markdown đầu tiên trong section có tiêu đề chứa `title`."""
    try:
        i = next(k for k, l in enumerate(lines) if l.startswith("## ") and title in l)
    except StopIteration:
        return []
    rows, started = [], False
    for l in lines[i + 1:]:
        if l.startswith("## "):
            break
        if l.startswith("|"):
            started = True
            rows.append([c.strip() for c in l.strip().strip("|").split("|")])
        elif started:
            break
    return rows[2:]


def parse_report(md: str) -> dict:
    """Báo cáo daily .md → {mode, budget, actions (mục 3), ranking (giá mục xếp hạng)}."""
    lines = md.split("\n")
    head = next((l for l in lines if l.startswith("**Nguồn:**")), "")
    m = re.search(r"\*\*Nguồn:\*\*\s*([^·]+)", head)
    b = re.search(r"\*\*Ngân sách:\*\*\s*(\S+)", head)
    actions = []
    for r in _table(lines, "Quyết định"):
        act = _ACTIONS.get(r[1])
        if act and len(r) >= 7:
            actions.append({"action": act, "symbol": r[0].split()[0], "lots": int(_num(r[2]) or 0),
                            "price": _num(r[3]) or 0.0})
    ranking = []
    for r in _table(lines, "Xếp hạng cả rổ"):
        px = _num(r[2]) if len(r) >= 8 else None
        ranking.append({"symbol": r[0].split()[0], "signal": r[1], "close": px / 1000 if px else None})
    return {"mode": m.group(1).strip() if m else "", "budget": b.group(1) if b else None,
            "actions": actions, "ranking": ranking}


def load_journals(since: str | None = None, root: str = _JOURNAL) -> dict[str, dict]:
    out = {}
    for f in sorted(glob.glob(os.path.join(root, "*-daily.md"))):
        day = os.path.basename(f)[:10]
        if since and day < since:
            continue
        if _dt.date.fromisoformat(day).weekday() >= 5:
            continue  # chạy tay cuối tuần = trùng dữ liệu thứ 6
        with open(f, encoding="utf-8") as fh:
            out[day] = parse_report(fh.read())
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


def health(journals: dict[str, dict]) -> dict:
    days = sorted(journals)
    fallback = [d for d in days if str(journals[d].get("mode", "")).startswith("fallback")]
    budgets = [journals[d].get("budget") for d in days]
    return {"days": len(days), "first": days[0] if days else None, "last": days[-1] if days else None,
            "fallback": fallback, "budget_unchanged_since": _unchanged_since(days, budgets)}


def _unchanged_since(days: list[str], vals: list) -> str | None:
    if len(vals) < 2 or vals[-1] is None:
        return None
    k = len(vals) - 1
    while k > 0 and vals[k - 1] == vals[-1]:
        k -= 1
    return days[k] if k < len(vals) - 1 else None


def decisions(journals: dict[str, dict], prices: dict[str, pd.DataFrame], sessions: pd.DatetimeIndex) -> list[dict]:
    """Mục 3 từng báo cáo: đặt LO đúng giá báo cáo ở phiên kế tiếp → khớp không, lời/lỗ tới phiên gần nhất.

    LO chỉ hiệu lực trong phiên. MUA khớp chắc nếu low < LO, "chạm" nếu low = LO (phụ thuộc hàng chờ);
    BÁN ngược lại với high. LO ngoài biên độ ±7% (HOSE) so tham chiếu → sàn từ chối. Giá làm tròn bước giá.
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
            ex = vn_market.detect_exchange(a["symbol"])
            lo = vn_market.round_tick(row["lo"], ex, act)
            ref = float(df.at[upto[-1], "close"]) * 1000 / factor if len(upto) and upto[-1] in df.index else None
            shares = row["lots"] * vn_market.LOT_SIZE
            tick = vn_market.tick_size(lo, ex)
            if ref and abs(lo / ref - 1) > vn_market.PRICE_LIMIT.get(ex, 0.07) + 1e-6:
                state = "band"  # ngoài biên độ trần/sàn → sàn từ chối lệnh
            elif act == "BUY":
                state = "khop" if bar["low"] < lo - tick / 2 else "cham" if bar["low"] <= lo + tick / 2 else "khong"
            else:
                state = "khop" if bar["high"] > lo + tick / 2 else "cham" if bar["high"] >= lo - tick / 2 else "khong"
            # Chạm đúng giá LO: chỉ khớp nếu tới lượt trong hàng chờ → không chắc, vẫn tính lãi/lỗ nhưng đánh dấu.
            row["state"] = state
            row["filled"] = state in ("khop", "cham")
            if act == "BUY":
                fill = min(bar["open"], lo) if row["filled"] else float(bar["open"])
                fill = vn_market.round_tick(fill, ex, "SELL")
                pnl = vn_market.sell_proceeds(cur, shares) - vn_market.buy_cost(fill, shares)
                capital = vn_market.buy_cost(fill, shares)
            else:
                fill = max(bar["open"], lo) if row["filled"] else float(bar["open"])
                fill = vn_market.round_tick(fill, ex, "BUY")
                pnl = vn_market.sell_proceeds(fill, shares) - cur * shares
                capital = cur * shares
            row.update(lo=lo, fill=float(fill), cur=float(df["close"].iloc[-1]) * 1000, pnl=float(pnl),
                       pct=float(pnl / capital * 100), as_of=str(last.date()))
    return out


def build(since: str | None = None, throttle: float = 3.3) -> dict:
    journals = load_journals(since)
    if not journals:
        return {"error": "không có báo cáo daily nào"}
    start = (_dt.date.fromisoformat(min(journals)) - _dt.timedelta(days=7)).isoformat()
    end = _dt.date.today().isoformat()
    syms = {a["symbol"] for d in journals.values() for a in d["actions"]}
    prices = fetch_prices(syms | {"VNINDEX"}, start, end, throttle)
    ref = prices.get("VNINDEX")
    if ref is None:
        return {"error": "không lấy được lịch phiên (VNINDEX)"}
    sessions = ref.index
    first = sessions[sessions > pd.Timestamp(min(journals))]
    return {"since": min(journals), "until": str(sessions[-1].date()),
            "decisions": decisions(journals, prices, sessions),
            "vnindex_ret": _ret(ref, first[0], sessions[-1]) if len(first) else None,
            "health": health(journals), "missing": sorted(syms - set(prices))}


def _vnd(x: float) -> str:
    return f"{x / 1e6:+,.2f}tr"


def _state(r: dict) -> str:
    f = format(r["fill"], ",.0f")
    return {"khop": f"✓ {f}", "cham": f"~ {f} (chạm giá)", "band": "✗ ngoài biên độ"}.get(r["state"], f"✗ (mở {f})")


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
    touch = sum(r["state"] == "cham" for r in done)
    L.append(f"- **Tổng nếu làm theo mọi lệnh khớp:** {_vnd(tot)} · {len(miss)} lệnh LO không khớp phiên kế tiếp"
             + (f" · {touch} lệnh chỉ chạm đúng giá LO (~, có thể không tới lượt)" if touch else ""))
    L += ["", "| Báo cáo | Lệnh | Mã | Lô | LO | Khớp | Giá nay | Lãi/lỗ | % |",
          "| :-- | :-- | :-- | --: | --: | :-- | --: | --: | --: |"]
    by_day: dict[str, float] = {}
    note = any(r.get("adjusted") for r in done)
    for r in done:
        if r["filled"]:
            by_day[r["day"]] = by_day.get(r["day"], 0.0) + r["pnl"]
        sym = r["symbol"] + ("*" if r.get("adjusted") else "")
        L.append(f"| {r['day']} | {'MUA' if r['action'] == 'BUY' else 'BÁN'} | {sym} | {r['lots']} "
                 f"| {r['lo']:,.0f} | {_state(r)} "
                 f"| {r['cur']:,.0f} | {_vnd(r['pnl']) if r['filled'] else '—'} | {r['pct']:+.1f}% |")
    if note:
        L += ["", "\\* Mã có chia cổ tức cổ phiếu/thưởng sau báo cáo: Khớp tính theo giá cũ, Giá nay là giá thực tế, "
              "lãi/lỗ đã tính cả cổ phiếu được chia (thực tế cổ mới về tài khoản sau vài tuần, phần lẻ dưới 100cp "
              "chỉ bán được ở bảng lô lẻ)."]
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
        return f"# Hiệu suất lệnh mục 3\n\nLỗi: {res['error']}\n"
    L = [f"# Hiệu suất lệnh mục 3 · {res['since']} → {res['until']}", ""]
    if res["vnindex_ret"] is not None:
        L += [f"**Thị trường cùng kỳ:** VNINDEX {res['vnindex_ret']:+.2f}%", ""]
    L += render_decisions(res.get("decisions") or [])
    h = res["health"]
    warn = []
    if h["fallback"]:
        warn.append(f"Chạy fallback (không TCBS): {', '.join(h['fallback'])}")
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
