"""Snapshot danh mục thật hằng ngày → reports/portfolio/{ngày}.md (so với file .md ngày trước).

Số lượng + giá vốn lấy từ everyday; giá định giá = đóng cửa mới nhất từ vnstock (everyday có thể chưa cập nhật giá).
"""
from __future__ import annotations

import datetime as _dt
import glob
import os
import time

from . import portfolio as pf
from . import vn_data, vn_market

_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
DIR = os.path.join(_ROOT, "portfolio")


def _close(symbol: str) -> tuple[float | None, str | None]:
    try:
        ind = vn_data.get_indicators(symbol)
    except BaseException:
        return None, None
    c = ind.get("close")
    return (float(c) * 1000, ind.get("as_of")) if isinstance(c, (int, float)) else (None, None)


def build(throttle: float = 3.3) -> dict:
    holdings = pf.fetch_holdings("vn_stock")
    cash = pf.fetch_cash()
    try:
        crypto = pf.fetch_holdings("crypto")
    except pf.PortfolioError:
        crypto = []
    rows, as_of = [], None
    for h in holdings:
        qty = int(h.get("qty") or 0)
        if not qty:
            continue
        sym = str(h["symbol"]).upper()
        px, d = _close(sym)
        time.sleep(throttle)
        as_of = max(filter(None, [as_of, d]), default=None)
        if px is None:  # không lấy được giá → dùng định giá everyday
            px = float(h.get("marketValue") or 0) / qty
        cost = float(h.get("costBasis") or 0)
        lots, odd = vn_market.split_lots(qty)
        rows.append({"symbol": sym, "qty": qty, "lots": lots, "odd": odd,
                     "avg_cost": cost / qty if qty else 0.0, "price": px,
                     "value": px * qty, "cost": cost, "pnl": px * qty - cost})
    stock = sum(r["value"] for r in rows)
    for r in rows:
        r["weight"] = r["value"] / stock * 100 if stock else 0.0
    rows.sort(key=lambda r: -r["value"])
    crypto_v = sum(float(c.get("marketValue") or 0) for c in crypto)
    return {"date": _dt.date.today().isoformat(), "as_of": as_of, "positions": rows,
            "stock_value": stock, "stock_cost": sum(r["cost"] for r in rows),
            "cash": float(cash["total"]), "crypto_value": crypto_v,
            "crypto": [{"symbol": c.get("symbol"), "qty": c.get("qty"),
                        "value": float(c.get("marketValue") or 0)} for c in crypto],
            "total": stock + float(cash["total"]) + crypto_v}


def _tr(x: str) -> float:
    return float(x.strip("* ").replace("tr", "").replace(",", "")) * 1e6


def parse(md: str) -> dict:
    """Đọc lại snapshot .md (bảng tài sản + vị thế) để so ngày sau."""
    from .scorecard import _table
    lines = md.split("\n")
    date = lines[0].replace("# Danh mục", "").strip()
    assets = {}
    for l in lines:
        if l.startswith("| ") and l.rstrip(" |*").endswith("tr") and l.count("|") == 3:
            k, v = [c.strip() for c in l.strip().strip("|").split("|")]
            assets[k.strip("* ")] = _tr(v)
    pos = [{"symbol": r[0], "qty": int(r[1].replace(",", "")), "price": float(r[4].replace(",", ""))}
           for r in _table(lines, "Vị thế")]
    return {"date": date, "positions": pos, "stock_value": assets.get("Cổ phiếu", 0.0),
            "cash": assets.get("Tiền mặt (bank)", 0.0), "total": assets.get("Tổng", 0.0)}


def previous(today: str, root: str = DIR) -> dict | None:
    files = sorted(f for f in glob.glob(os.path.join(root, "*.md")) if os.path.basename(f)[:10] < today)
    if not files:
        return None
    with open(files[-1], encoding="utf-8") as f:
        return parse(f.read())


def last_daily_actions(today: str, journal_dir: str = os.path.join(_ROOT, "journal")) -> tuple[str | None, list[dict]]:
    from .scorecard import parse_report
    files = sorted(f for f in glob.glob(os.path.join(journal_dir, "*-daily.md")) if os.path.basename(f)[:10] < today)
    if not files:
        return None, []
    with open(files[-1], encoding="utf-8") as f:
        return os.path.basename(files[-1])[:10], parse_report(f.read())["actions"]


def diff(snap: dict, prev: dict | None, acts: list[dict]) -> dict:
    """So với snapshot trước: thay đổi tài sản, biến động giá, lệnh thật phát sinh (đối chiếu mục 3)."""
    if not prev:
        return {}
    now = {r["symbol"]: r for r in snap["positions"]}
    old = {r["symbol"]: r for r in prev["positions"]}
    price_pnl = sum(r["qty"] * (r["price"] - old[s]["price"]) for s, r in now.items()
                    if s in old and old[s]["qty"] == r["qty"])
    trades = []
    planned = {(str(a["symbol"]).upper(), str(a["action"]).upper()): a for a in acts
               if str(a.get("action", "")).upper() in ("BUY", "SELL")}
    for s in sorted(set(now) | set(old)):
        dq = now.get(s, {}).get("qty", 0) - old.get(s, {}).get("qty", 0)
        if not dq:
            continue
        side = "BUY" if dq > 0 else "SELL"
        p = planned.get((s, side))
        trades.append({"symbol": s, "side": side, "qty": abs(dq),
                       "planned_lots": p.get("lots") if p else None, "planned_price": p.get("price") if p else None})
    done = {(t["symbol"], t["side"]) for t in trades}
    skipped = [{"symbol": s, "side": side, "lots": a.get("lots"), "price": a.get("price")}
               for (s, side), a in planned.items() if (s, side) not in done]
    return {"prev_date": prev["date"], "total_delta": snap["total"] - prev["total"],
            "stock_delta": snap["stock_value"] - prev["stock_value"],
            "cash_delta": snap["cash"] - prev["cash"], "price_pnl": price_pnl,
            "trades": trades, "skipped": skipped}


def _m(x: float) -> str:
    return f"{x / 1e6:,.2f}tr"


def _sm(x: float) -> str:
    return f"{x / 1e6:+,.2f}tr"


def render(snap: dict, d: dict, plan_day: str | None) -> str:
    pnl = snap["stock_value"] - snap["stock_cost"]
    pct = pnl / snap["stock_cost"] * 100 if snap["stock_cost"] else 0.0
    L = [f"# Danh mục {snap['date']}", "",
         f"Giá đóng cửa phiên {snap['as_of'] or '—'} · số lượng, giá vốn từ everyday", "",
         "| Tài sản | Giá trị |", "| :-- | --: |",
         f"| Cổ phiếu | {_m(snap['stock_value'])} |",
         f"| Tiền mặt (bank) | {_m(snap['cash'])} |"]
    if snap["crypto_value"]:
        L.append(f"| Crypto | {_m(snap['crypto_value'])} |")
    L += [f"| **Tổng** | **{_m(snap['total'])}** |", "",
          f"**Lãi/lỗ cổ phiếu:** {_sm(pnl)} ({pct:+.1f}%) trên vốn {_m(snap['stock_cost'])}", ""]
    if d:
        L += [f"## Thay đổi so với {d['prev_date']}", "",
              f"- Tổng tài sản {_sm(d['total_delta'])} · cổ phiếu {_sm(d['stock_delta'])} · tiền mặt {_sm(d['cash_delta'])}",
              f"- Do biến động giá (mã không đổi số lượng): {_sm(d['price_pnl'])}"]
        for t in d["trades"]:
            side = "MUA" if t["side"] == "BUY" else "BÁN"
            ref = (f" — theo mục 3 ngày {plan_day}: {t['planned_lots']} lô @ {t['planned_price']:,.0f}"
                   if t["planned_lots"] else " — không có trong mục 3")
            L.append(f"- {side} {t['symbol']} {t['qty']:,} cp{ref}")
        for k in d["skipped"]:
            side = "MUA" if k["side"] == "BUY" else "BÁN"
            L.append(f"- Chưa làm theo mục 3 ngày {plan_day}: {side} {k['symbol']} {k['lots']} lô @ {k['price']:,.0f}")
        L.append("")
    L += ["## Vị thế", "",
          "| Mã | SL | Lô chẵn + lẻ | Giá vốn | Giá đóng cửa | Giá trị | Lãi/lỗ | % | Tỷ trọng |",
          "| :-- | --: | :-- | --: | --: | --: | --: | --: | --: |"]
    for r in snap["positions"]:
        lots = f"{r['lots']} lô" + (f" + {r['odd']} lẻ" if r["odd"] else "")
        p = r["pnl"] / r["cost"] * 100 if r["cost"] else 0.0
        L.append(f"| {r['symbol']} | {r['qty']:,} | {lots} | {r['avg_cost']:,.0f} | {r['price']:,.0f} "
                 f"| {_m(r['value'])} | {_sm(r['pnl'])} | {p:+.1f}% | {r['weight']:.1f}% |")
    if any(r["odd"] for r in snap["positions"]):
        L += ["", "Lô lẻ (dưới 100cp, thường do cổ tức cổ phiếu) chỉ bán được ở bảng lô lẻ, giá thường kém hơn lô chẵn."]
    if snap["crypto"]:
        L += ["", "## Crypto", "", "| Mã | SL | Giá trị |", "| :-- | --: | --: |"]
        L += [f"| {c['symbol']} | {c['qty']} | {_m(c['value'])} |" for c in snap["crypto"]]
    return "\n".join(L) + "\n"


def run(throttle: float = 3.3) -> tuple[str, str]:
    snap = build(throttle)
    plan_day, acts = last_daily_actions(snap["date"])
    md = render(snap, diff(snap, previous(snap["date"]), acts), plan_day)
    os.makedirs(DIR, exist_ok=True)
    path = os.path.join(DIR, f"{snap['date']}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return path, md
