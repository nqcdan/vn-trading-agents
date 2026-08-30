"""Lớp dữ liệu VN qua vnstock — thay cho yfinance/alpha_vantage của upstream."""
from __future__ import annotations
import contextlib
import io
import math
from datetime import date, timedelta

import pandas as pd


def _quiet():
    return contextlib.redirect_stdout(io.StringIO())


def get_ohlcv(symbol: str, start: str, end: str, source: str = "VCI") -> pd.DataFrame:
    with _quiet():
        from vnstock.api.quote import Quote
        df = Quote(symbol=symbol.upper(), source=source).history(
            start=start, end=end, interval="1D"
        )
    df = df.rename(columns={"time": "date"})
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff().dropna()
    if len(delta) < period:
        return float("nan")
    gain = delta.clip(lower=0).rolling(period).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).rolling(period).mean().iloc[-1]
    if loss == 0:
        return 100.0
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def get_indicators(symbol: str, as_of: str | None = None, lookback_days: int = 200) -> dict:
    end = as_of or date.today().isoformat()
    start = (date.fromisoformat(end) - timedelta(days=lookback_days * 2)).isoformat()
    df = get_ohlcv(symbol, start, end)
    if df.empty:
        return {"error": "no price data"}
    close = df["close"]
    last = float(close.iloc[-1])
    sma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else float("nan")
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else float("nan")
    ret20 = float(last / close.iloc[-21] - 1) if len(close) > 21 else float("nan")
    vol20 = float(close.pct_change().rolling(20).std().iloc[-1]) if len(close) >= 21 else float("nan")
    avg_vol = float(df["volume"].tail(20).mean())
    return {
        "symbol": symbol.upper(),
        "as_of": str(df["date"].iloc[-1].date()),
        "close": round(last, 2),
        "sma20": round(sma20, 2) if not math.isnan(sma20) else None,
        "sma50": round(sma50, 2) if not math.isnan(sma50) else None,
        "rsi14": round(_rsi(close), 1),
        "ret20d_pct": round(ret20 * 100, 1) if not math.isnan(ret20) else None,
        "vol20d_pct": round(vol20 * 100, 2) if not math.isnan(vol20) else None,
        "avg_vol20": int(avg_vol),
    }


def get_fundamentals(symbol: str, source: str = "VCI") -> dict:
    """Trích vài chỉ số cơ bản mới nhất từ báo cáo tài chính."""
    try:
        with _quiet():
            from vnstock.api.financial import Finance
            r = Finance(symbol=symbol.upper(), source=source).ratio(period="year", lang="en")
    except Exception as e:
        return {"error": f"fundamentals unavailable: {type(e).__name__}"}

    # vnstock trả bảng dài: cột 0..2 = item/item_en/item_id, còn lại là các năm
    # (tên cột năm có thể trùng lặp → truy cập theo vị trí, không theo nhãn).
    if isinstance(r.columns, pd.MultiIndex):
        r.columns = ["_".join(str(x) for x in c if str(x) != "") for c in r.columns]
    label_idx = 1 if len(r.columns) > 1 else 0
    year_start = 3

    def latest_val(row):
        for j in range(len(row) - 1, year_start - 1, -1):
            try:
                f = float(row.iloc[j])
                if f == f:
                    return f
            except (ValueError, TypeError):
                continue
        return None

    wanted = {"pe": ["p/e"], "pb": ["p/b"], "roe": ["roe (%)", "roe"],
              "roa": ["roa (%)", "roa"], "debt_equity": ["debt/equity"]}
    out: dict = {"symbol": symbol.upper()}
    for _, row in r.iterrows():
        name = str(row.iloc[label_idx]).lower().strip()
        for key, needles in wanted.items():
            if key in out:
                continue
            if any(name == n or name.startswith(n) for n in needles):
                v = latest_val(row)
                if v is not None:
                    out[key] = round(v, 3)
                break
    return out


def get_group_symbols(group: str = "VN30") -> list[str]:
    with _quiet():
        from vnstock.api.listing import Listing
        syms = Listing().symbols_by_group(group)
    return [str(s).upper() for s in list(syms)]
