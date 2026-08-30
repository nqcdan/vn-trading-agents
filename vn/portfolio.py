"""Đọc portfolio thật từ everyday API rồi phân tích từng vị thế.

Cấu hình qua env:
  EVERYDAY_API_BASE   vd http://localhost:3900 hoặc URL server admin
  EVERYDAY_ADMIN_TOKEN  Bearer token (ADMIN_TOKEN của everyday)

Endpoint everyday: GET /api/wallet/holdings?class=vn_stock  (cần Bearer token).
"""
from __future__ import annotations
import json
import os
import urllib.request

from . import vn_data, vn_news
from .agents import technical_analyst, fundamental_analyst, macro_mood


class PortfolioError(RuntimeError):
    pass


def fetch_holdings(asset_class: str = "vn_stock",
                   base: str | None = None, token: str | None = None) -> list[dict]:
    base = (base or os.environ.get("EVERYDAY_API_BASE", "")).rstrip("/")
    token = token or os.environ.get("EVERYDAY_ADMIN_TOKEN", "")
    if not base:
        raise PortfolioError("thiếu EVERYDAY_API_BASE")
    hdr = {"Authorization": f"Bearer {token}"}
    url = f"{base}/api/wallet/holdings"
    if asset_class:
        url += f"?class={asset_class}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=20) as r:
            return json.loads(r.read().decode("utf-8")).get("holdings", [])
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise PortfolioError(f"HTTP {e.code} từ everyday: {e.reason}") from e
        # Fallback: server chưa deploy endpoint /holdings → dùng /api/wallet + shape client-side
        return _holdings_from_wallet(base, hdr, asset_class)
    except Exception as e:
        raise PortfolioError(f"không gọi được everyday API: {type(e).__name__}") from e


def fetch_cash(kinds: tuple[str, ...] = ("bank",),
               base: str | None = None, token: str | None = None) -> dict:
    """Tổng số dư ví khả dụng theo kind (mặc định 'bank') từ everyday /api/wallet.

    → {'total': int VND, 'wallets': [{name, kind, balance}...]}. Đây là 'tiền có thể tiêu'.
    """
    base = (base or os.environ.get("EVERYDAY_API_BASE", "")).rstrip("/")
    token = token or os.environ.get("EVERYDAY_ADMIN_TOKEN", "")
    if not base:
        raise PortfolioError("thiếu EVERYDAY_API_BASE")
    hdr = {"Authorization": f"Bearer {token}"}
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{base}/api/wallet", headers=hdr), timeout=20) as r:
            rows = json.loads(r.read().decode("utf-8")).get("rows", [])
    except urllib.error.HTTPError as e:
        raise PortfolioError(f"HTTP {e.code} từ everyday: {e.reason}") from e
    except Exception as e:
        raise PortfolioError(f"không gọi được everyday API: {type(e).__name__}") from e
    picked = [w for w in rows if w.get("kind") in kinds and w.get("assetSymbol") is None]
    total = sum(int(w.get("balance") or 0) for w in picked)
    return {"total": total, "kinds": list(kinds),
            "wallets": [{"name": w.get("name"), "kind": w.get("kind"),
                         "balance": int(w.get("balance") or 0)} for w in picked]}


def _holdings_from_wallet(base: str, hdr: dict, asset_class: str) -> list[dict]:
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{base}/api/wallet", headers=hdr), timeout=20) as r:
            rows = json.loads(r.read().decode("utf-8")).get("rows", [])
    except Exception as e:
        raise PortfolioError(f"fallback /api/wallet lỗi: {type(e).__name__}") from e
    out = []
    for w in rows:
        if not w.get("assetSymbol") or w.get("qty") is None:
            continue
        if asset_class and w.get("assetClass") != asset_class:
            continue
        mv, cost = w.get("balance"), w.get("costBasis")
        pnl = None if cost is None else mv - cost
        out.append({
            "symbol": w["assetSymbol"], "assetClass": w.get("assetClass"), "name": w.get("name"),
            "qty": w.get("qty"), "costBasis": cost, "marketValue": mv, "currency": w.get("currency"),
            "pnl": pnl, "pnlPct": round(pnl / cost * 1000) / 10 if cost else None,
        })
    return out


def _position_signal(symbol: str) -> dict:
    """Phân tích nhẹ 1 vị thế (không LLM, không news) — nhanh cho cả danh mục."""
    ind = vn_data.get_indicators(symbol)
    fund = vn_data.get_fundamentals(symbol)
    ta = technical_analyst(ind)
    fa = fundamental_analyst(fund)
    total = ta["score"] + fa["score"]
    action = "BUY" if total >= 2 else "SELL" if total <= -2 else "HOLD"
    rsi = ind.get("rsi14")
    return {
        "signal": action,
        "technical": ta["signal"], "fundamental": fa["signal"],
        "rsi14": rsi, "overbought": isinstance(rsi, (int, float)) and rsi >= 70,
        "pe": fund.get("pe"), "pb": fund.get("pb"), "roe": fund.get("roe"),
        "close": ind.get("close"), "ret20d_pct": ind.get("ret20d_pct"),
    }


def analyze_portfolio(asset_class: str = "vn_stock",
                      base: str | None = None, token: str | None = None) -> dict:
    holdings = fetch_holdings(asset_class, base, token)
    macro = macro_mood()
    positions = []
    for h in holdings:
        sym = str(h.get("symbol", "")).upper()
        if not sym:
            continue
        try:
            sig = _position_signal(sym)
        except BaseException as e:  # gồm SystemExit rate-limit của vnstock
            sig = {"error": f"{type(e).__name__}"}
        positions.append({
            "symbol": sym, "qty": h.get("qty"), "cost_basis": h.get("costBasis"),
            "market_value": h.get("marketValue"), "pnl": h.get("pnl"),
            "pnl_pct": h.get("pnlPct"), "analysis": sig,
        })
    total_mv = sum(p["market_value"] or 0 for p in positions)
    total_cost = sum(p["cost_basis"] or 0 for p in positions)
    total_pnl = total_mv - total_cost if total_cost else None
    # đóng góp tỷ trọng
    for p in positions:
        p["weight_pct"] = round((p["market_value"] or 0) / total_mv * 100, 1) if total_mv else None
    counts = {"BUY": 0, "HOLD": 0, "SELL": 0, "overbought": 0}
    for p in positions:
        a = p["analysis"]
        if a.get("signal") in counts:
            counts[a["signal"]] += 1
        if a.get("overbought"):
            counts["overbought"] += 1
    return {
        "asset_class": asset_class, "n": len(positions),
        "total_market_value": total_mv, "total_cost": total_cost,
        "total_pnl": total_pnl,
        "total_pnl_pct": round(total_pnl / total_cost * 100, 1) if total_pnl is not None and total_cost else None,
        "macro": {"signal": macro.get("signal"), "net": macro.get("net")},
        "signal_counts": counts,
        "positions": sorted(positions, key=lambda x: x["market_value"] or 0, reverse=True),
    }
