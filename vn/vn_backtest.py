"""Backtest long-only cho VN: phí + thuế + slippage + biên độ + T+2.

Dùng tín hiệu rule-based (nhanh, miễn phí) để walk-forward. LLM để dành cho
phân tích one-shot (đắt, không hợp chạy mỗi phiên nhiều năm).
"""
from __future__ import annotations
from datetime import date, timedelta

import pandas as pd

from . import vn_data, vn_market
from .agents import technical_analyst, fundamental_analyst


def _signal_at(df: pd.DataFrame, i: int, fund: dict) -> str:
    window = df.iloc[: i + 1]
    close = window["close"]
    ind = {"close": float(close.iloc[-1])}
    ind["sma20"] = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else None
    ind["sma50"] = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    delta = close.diff().dropna()
    if len(delta) >= 14:
        gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
        loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
        ind["rsi14"] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    else:
        ind["rsi14"] = None
    ta = technical_analyst(ind)
    fa = fundamental_analyst(fund)
    total = ta["score"] + fa["score"]
    # Thoát theo xu hướng: thủng SMA50 → bán (cắt lỗ trend-following)
    if ind["sma50"] and ind["close"] < ind["sma50"]:
        return "SELL"
    return "BUY" if total >= 2 else "SELL" if total <= -2 else "HOLD"


def _index_regime(start: str, end: str, index: str = "VNINDEX") -> dict:
    """Chế độ thị trường theo ngày: risk_off = VNINDEX đóng cửa < SMA50.

    Đây là proxy BACKTEST-ĐƯỢC thay cho macro-mood của voz (voz chỉ có tin
    hiện tại, không có kho lịch sử → không thể tái dựng theo ngày quá khứ).
    """
    from datetime import date, timedelta
    warm = (date.fromisoformat(start) - timedelta(days=120)).isoformat()
    idx = vn_data.get_ohlcv(index, warm, end)
    sma50 = idx["close"].rolling(50).mean()
    regime = {}
    for i in range(len(idx)):
        d = idx["date"].iloc[i].date()
        s = sma50.iloc[i]
        regime[d] = bool(s == s and idx["close"].iloc[i] < s)  # False khi NaN
    return regime


def backtest(symbol: str, start: str, end: str, capital: float = 100_000_000,
             use_macro: bool = True, macro_haircut: float = 0.30,
             regime: dict | None = None) -> dict:
    df = vn_data.get_ohlcv(symbol, start, end)
    if len(df) < 55:
        return {"error": "cần ≥55 phiên dữ liệu để chạy SMA50"}
    fund = vn_data.get_fundamentals(symbol)
    if not use_macro:
        regime = {}
    elif regime is None:
        regime = _index_regime(start, end)
    risk_off_days = 0

    cash = capital
    shares = 0
    pending = []  # (settle_index, kind, amount_or_shares) — mô phỏng T+2
    equity_curve, peak, max_dd = [], capital, 0.0
    trades = 0

    for i in range(50, len(df)):
        px = float(df["close"].iloc[i])
        ref = float(df["close"].iloc[i - 1])

        # Giải phóng khoản T+2 đến hạn
        still = []
        for settle_i, kind, val in pending:
            if i >= settle_i:
                if kind == "cash":
                    cash += val
                else:
                    shares += val
            else:
                still.append((settle_i, kind, val))
        pending = still

        sig = _signal_at(df, i, fund)
        fill = vn_market.clamp_to_band(ref, px, symbol)
        cur_date = df["date"].iloc[i].date()
        risk_off = regime.get(cur_date, False)
        if risk_off:
            risk_off_days += 1

        if sig == "BUY" and cash > fill * vn_market.LOT_SIZE * 1.02 and shares == 0:
            budget = cash * 0.95 * (1 - macro_haircut if risk_off else 1.0)
            qty = vn_market.round_lot(budget / (fill * (1 + vn_market.BUY_FEE + vn_market.SLIPPAGE)))
            if qty >= vn_market.LOT_SIZE:
                cost = vn_market.buy_cost(fill, qty)
                cash -= cost
                pending.append((i + vn_market.SETTLE_DAYS, "shares", qty))
                trades += 1
        elif sig == "SELL" and shares > 0:
            proceeds = vn_market.sell_proceeds(fill, shares)
            pending.append((i + vn_market.SETTLE_DAYS, "cash", proceeds))
            shares = 0
            trades += 1

        settled_shares = shares + sum(v for _, k, v in pending if k == "shares")
        settled_cash = cash + sum(v for _, k, v in pending if k == "cash")
        equity = settled_cash + settled_shares * px
        equity_curve.append(equity)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)

    final = equity_curve[-1]
    days = len(equity_curve)
    total_ret = final / capital - 1
    bh_ret = float(df["close"].iloc[-1]) / float(df["close"].iloc[50]) - 1
    cagr = (final / capital) ** (252 / days) - 1 if days > 0 else 0
    # Định giá + RSI HIỆN TẠI (để đánh giá bây giờ, tách khỏi hiệu năng quá khứ)
    close = df["close"]
    delta = close.diff().dropna()
    g = delta.clip(lower=0).rolling(14).mean().iloc[-1]
    l = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
    rsi_now = round(100.0 if l == 0 else 100 - 100 / (1 + g / l), 1)
    return {
        "symbol": symbol.upper(),
        "period": f"{start} → {end}",
        "sessions": days,
        "final_nav": round(final),
        "total_return_pct": round(total_ret * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "buy_hold_return_pct": round(bh_ret * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "trades": trades,
        "pe_now": fund.get("pe"),
        "pb_now": fund.get("pb"),
        "rsi_now": rsi_now,
        "macro_haircut": macro_haircut if use_macro else 0,
        "risk_off_sessions": risk_off_days,
        "note": "đã tính phí+thuế+slippage+biên độ+T+2"
                + (f" + macro haircut {int(macro_haircut*100)}% khi VNINDEX<SMA50" if use_macro else "")
                + ". So sánh buy_hold + chạy --no-macro để thấy tác dụng haircut.",
    }


def _run_one(sym, start, end, use_macro, macro_haircut, regime, throttle):
    """Backtest 1 mã với retry backoff khi nguồn rate-limit (vnstock raise SystemExit)."""
    import time
    for attempt in range(4):
        try:
            time.sleep(throttle)
            return backtest(sym, start, end, use_macro=use_macro,
                            macro_haircut=macro_haircut, regime=regime)
        except BaseException as e:  # SystemExit("Rate limit exceeded") lọt vào đây
            if "rate limit" in str(e).lower() and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            return {"error": f"{type(e).__name__}: {str(e)[:60]}"}


def screen_group(group: str = "VN30", start: str = "2024-01-01", end: str = "2026-08-29",
                 use_macro: bool = True, macro_haircut: float = 0.30,
                 throttle: float = 1.2) -> dict:
    """Backtest toàn rổ, xếp hạng theo alpha (chiến lược − buy&hold)."""
    symbols = vn_data.get_group_symbols(group)
    regime = _index_regime(start, end) if use_macro else {}
    rows, no_entry, errs = [], [], []
    for sym in symbols:
        r = _run_one(sym, start, end, use_macro, macro_haircut, regime, throttle)
        if "error" in r:
            errs.append(f"{sym}: {r['error']}")
            continue
        r["alpha_pct"] = round(r["total_return_pct"] - r["buy_hold_return_pct"], 2)
        # Mã không có lệnh (mới niêm yết/đổi sàn/thiếu SMA) → không xếp hạng
        if r["trades"] == 0:
            no_entry.append(r)
        else:
            rows.append(r)
    rows.sort(key=lambda x: x["alpha_pct"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return {"group": group, "period": f"{start} → {end}", "n": len(rows),
            "macro_haircut": macro_haircut if use_macro else 0,
            "ranking": rows, "no_entry": [r["symbol"] for r in no_entry], "errors": errs}
