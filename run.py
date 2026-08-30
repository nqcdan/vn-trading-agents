#!/usr/bin/env python
"""CLI: phân tích multi-agent + backtest cho cổ phiếu VN.

Ví dụ:
  python run.py analyze FPT
  python run.py backtest VCB --start 2024-01-01 --end 2026-08-29
"""
from __future__ import annotations
import argparse
import json

from vn import agents, vn_backtest, recommend as rec, portfolio as pf, advise as adv, tcbs as tcbs_mcp


def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_analyze(a):
    res = agents.analyze(a.symbol, as_of=a.as_of)
    d = res["trader_decision"]
    r = res["risk"]
    print(f"\n=== {res['symbol']} ({res['exchange']}, biên độ ±{res['price_limit_pct']}%) "
          f"| LLM={'on' if res['llm'] else 'off (rule-based)'} ===")
    print(f"Kỹ thuật : {res['technical']['signal']}  ({'; '.join(res['technical']['notes'])})")
    print(f"Cơ bản   : {res['fundamental']['signal']}  ({'; '.join(res['fundamental']['notes'])})")
    se = res.get("sentiment", {})
    print(f"Tin tức  : {se.get('signal','?')}  (CafeF+DN: {se.get('n',0)} tin, +{se.get('pos',0)}/-{se.get('neg',0)})")
    for h in se.get("headlines", [])[:3]:
        print(f"           • {h[:90]}")
    mm = res.get("macro", {})
    print(f"Vĩ mô voz: {mm.get('signal','?')}  (Điểm báo: {mm.get('n',0)} tin, net {mm.get('net',0)})")
    print(f"BULL     : {res['debate']['bull'][:300]}")
    print(f"BEAR     : {res['debate']['bear'][:300]}")
    print(f"TRADER   : {d['action']}  (conf {d.get('confidence')}) — {d.get('reason','')}")
    print(f"RISK     : {r['approved_action']}  | {r['note']}")
    if a.json:
        _print(res)


def cmd_backtest(a):
    _print(vn_backtest.backtest(a.symbol, a.start, a.end, capital=a.capital,
                                use_macro=not a.no_macro, macro_haircut=a.haircut))


def cmd_screen(a):
    res = vn_backtest.screen_group(a.group, a.start, a.end,
                                   use_macro=not a.no_macro, macro_haircut=a.haircut,
                                   throttle=a.throttle)
    hc = "off" if a.no_macro else f"{int(a.haircut*100)}%"
    print(f"\n=== Xếp hạng {res['group']} | {res['period']} | macro haircut {hc} "
          f"| {res['n']} mã ===")
    def fmt(v, suf=""):
        return f"{v:>6.1f}{suf}" if isinstance(v, (int, float)) else f"{'—':>6}{suf}"
    print("  (P/E, P/B, RSI = HIỆN TẠI để đánh giá bây giờ; return/alpha = quá khứ)")
    print(f"{'#':>2} {'MÃ':5} {'alpha':>8} {'return':>8} {'B&H':>8} {'maxDD':>7} "
          f"{'P/E':>6} {'P/B':>6} {'RSI':>6} {'lệnh':>4}")
    for r in res["ranking"]:
        flag = " ←quá mua" if isinstance(r.get("rsi_now"), (int, float)) and r["rsi_now"] >= 70 else ""
        print(f"{r['rank']:>2} {r['symbol']:5} {r['alpha_pct']:7.2f}% {r['total_return_pct']:7.2f}% "
              f"{r['buy_hold_return_pct']:7.2f}% {r['max_drawdown_pct']:6.1f}% "
              f"{fmt(r.get('pe_now'))} {fmt(r.get('pb_now'))} {fmt(r.get('rsi_now'))} {r['trades']:>4}{flag}")
    if res.get("no_entry"):
        print(f"\nKhông có lệnh (không xếp hạng): {', '.join(res['no_entry'])}")
    if res["errors"]:
        errs = [e.split(':')[0] for e in res["errors"]]
        print(f"Rate-limit/lỗi ({len(errs)}): {', '.join(errs)} — chạy lại hoặc tăng throttle")
    print("\nalpha = return chiến lược − buy&hold. Dương = chiến lược thắng nắm giữ.")
    if a.json:
        _print(res)


def cmd_portfolio(a):
    res = pf.analyze_portfolio(a.asset_class)
    print(f"\n=== Danh mục {a.asset_class} | {res['n']} vị thế "
          f"| tổng {res['total_market_value']:,.0f}đ ===")
    pnl = res.get("total_pnl")
    if pnl is not None:
        print(f"P&L: {pnl:+,.0f}đ ({res['total_pnl_pct']:+.1f}%) | "
              f"vĩ mô voz: {res['macro']['signal']} (net {res['macro']['net']})")
    c = res["signal_counts"]
    print(f"Tín hiệu: {c['BUY']} BUY / {c['HOLD']} HOLD / {c['SELL']} SELL "
          f"| {c['overbought']} mã quá mua")
    print(f"\n{'MÃ':5} {'tỷ trọng':>8} {'P&L%':>7} {'tín hiệu':>9} {'RSI':>6} {'P/E':>6} {'P/B':>6}")
    for p in res["positions"]:
        an = p["analysis"]
        if "error" in an:
            print(f"{p['symbol']:5} {'':>8} {'':>7} {'lỗi:'+an['error']:>9}")
            continue
        ob = "⚠" if an.get("overbought") else " "
        def num(v, w=6, d=1):
            return f"{v:>{w}.{d}f}" if isinstance(v, (int, float)) else f"{'—':>{w}}"
        print(f"{p['symbol']:5} {num(p.get('weight_pct'),8)}% {num(p.get('pnl_pct'),6)}% "
              f"{an['signal']:>9} {num(an.get('rsi14'))}{ob} {num(an.get('pe'))} {num(an.get('pb'))}")
    print("\nNguồn: everyday /api/wallet/holdings. ⚠ = RSI≥70 quá mua. Không phải khuyến nghị đầu tư.")
    if a.json:
        _print(res)


def _fmt(v, w=6, d=1, suf=""):
    return f"{v:>{w}.{d}f}{suf}" if isinstance(v, (int, float)) else f"{'—':>{w}}{suf}"


def cmd_recommend(a):
    res = rec.recommend(a.group, holdings_csv=a.holdings, asset_class=a.asset_class,
                        llm_top=0 if a.no_llm else a.llm_top, throttle=a.throttle)
    m = res["macro"]
    print(f"\n=== Khuyến nghị {res['group']} + danh mục | {res['n']} mã "
          f"| vĩ mô voz: {m['signal']} (net {m['net']}) ===")
    if res["llm_verified"]:
        print(f"LLM-verified: {', '.join(res['llm_verified'])}")
    print(f"\n{'MÃ':5} {'giữ':>4} {'tín hiệu':>9} {'align':>6} {'RSI':>5} {'P/E':>6} {'P/B':>5} "
          f"{'ROE':>5} {'KHUYẾN NGHỊ':<22} {'LLM':>10}")
    for r in res["ranking"]:
        if r["action"] == "—" and not r["held"]:
            continue  # bỏ mã mới không đáng mua để bảng gọn
        hold = "◆" if r["held"] + 0 else " "
        w = f"{r['weight_pct']:.0f}%" if isinstance(r.get("weight_pct"), (int, float)) else ""
        roe = f"{r['roe']:.0%}" if isinstance(r.get("roe"), (int, float)) else "—"
        llm = ""
        if r.get("llm_action"):
            lc = r.get("llm_conf")
            llm = f"{r['llm_action']}" + (f" {lc:.2f}" if isinstance(lc, (int, float)) else "")
        print(f"{r['symbol']:5} {hold}{w:>3} {r['signal']:>9} {r['align']:>6} "
              f"{_fmt(r.get('rsi'),5)} {_fmt(r.get('pe'),6)} {_fmt(r.get('pb'),5)} {roe:>5} "
              f"{r['action']:<22} {llm:>10}")
    if res["errors"]:
        print(f"\nLỗi/rate-limit ({len(res['errors'])}): "
              f"{', '.join(e.split(':')[0] for e in res['errors'])}")
    print("\n◆ = mã đang giữ. BUY-WAIT = tín hiệu mua nhưng RSI≥70 (chờ hạ nhiệt).")
    print("LLM cột cuối = phán quyết sâu (thắng rule-based khi lệch, vd định giá đắt).")
    print("Công cụ giáo dục — KHÔNG phải khuyến nghị đầu tư.")
    if a.json:
        _print(res)


def cmd_advise(a):
    extra = [s for s in (a.extra or "").split(",") if s.strip()]
    cash_wallet = tuple(s.strip() for s in a.cash_wallet.split(",")) if a.cash_wallet else None
    res = adv.advise(a.group, holdings_csv=a.holdings, asset_class=a.asset_class,
                     cash=a.cash, throttle=a.throttle, llm_top=a.llm_top,
                     use_mcp=not a.no_mcp, extra=extra, cash_wallet=cash_wallet)
    if "error" in res:
        print(f"Lỗi: {res['error']}")
        return
    m = res["macro"]
    ci = res.get("cash_info")
    if ci:
        detail = ", ".join(f"{w['name']} {w['balance']:,}" for w in ci["wallets"])
        print(f"\nNgân sách (ví {'+'.join(ci['kinds'])} từ everyday): {ci['total']:,}đ — {detail}")
    print(f"\n=== Kế hoạch tháng | rổ {res['group']} | nguồn: {res.get('mode')} "
          f"| vĩ mô voz: {m['signal']} (net {m['net']}) ===\n")
    print(res["plan"])
    if res.get("errors"):
        print(f"\n(rate-limit bỏ qua: {', '.join(e.split(':')[0] for e in res['errors'])})")
    print("\n— Phân tích tham khảo theo PROFILE.md, KHÔNG phải khuyến nghị đầu tư.")
    if a.json:
        _print(res)


def cmd_tcbs(a):
    try:
        res = tcbs_mcp.analyze_tcbs(a.symbol)
    except tcbs_mcp.TcbsError as e:
        print(f"TCBS MCP lỗi: {e}")
        return
    print(f"\n=== {res['symbol']} qua TCBS MCP (real-time) ===\n")
    print(res["analysis"])
    print("\n— Dữ liệu TCBS real-time + PROFILE.md. KHÔNG phải khuyến nghị đầu tư.")
    if a.json:
        _print(res)


def main():
    p = argparse.ArgumentParser(description="VN TradingAgents")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("analyze", help="phân tích multi-agent 1 mã (one-shot)")
    pa.add_argument("symbol")
    pa.add_argument("--as-of", default=None, help="YYYY-MM-DD (mặc định hôm nay)")
    pa.add_argument("--json", action="store_true", help="in full JSON")
    pa.set_defaults(func=cmd_analyze)

    pb = sub.add_parser("backtest", help="backtest walk-forward có phí/biên độ/T+2")
    pb.add_argument("symbol")
    pb.add_argument("--start", default="2024-01-01")
    pb.add_argument("--end", default="2026-08-29")
    pb.add_argument("--capital", type=float, default=100_000_000)
    pb.add_argument("--no-macro", action="store_true", help="tắt macro haircut (để so sánh)")
    pb.add_argument("--haircut", type=float, default=0.30, help="tỷ lệ cắt size khi risk-off")
    pb.set_defaults(func=cmd_backtest)

    ps = sub.add_parser("screen", help="backtest cả rổ (VN30…) rồi xếp hạng")
    ps.add_argument("--group", default="VN30", help="VN30 | VN100 | HNX30 …")
    ps.add_argument("--start", default="2024-01-01")
    ps.add_argument("--end", default="2026-08-29")
    ps.add_argument("--no-macro", action="store_true")
    ps.add_argument("--haircut", type=float, default=0.30)
    ps.add_argument("--throttle", type=float, default=1.2, help="giây nghỉ giữa mã (tránh rate limit)")
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=cmd_screen)

    pp = sub.add_parser("portfolio", help="đọc portfolio từ everyday + phân tích từng vị thế")
    pp.add_argument("--asset-class", default="vn_stock", help="vn_stock | vn_fund | crypto")
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_portfolio)

    pr = sub.add_parser("recommend", help="rank danh mục + rổ → mua/bán/rotate (có LLM-verify top)")
    pr.add_argument("--group", default="VN30", help="rổ quét thêm: VN30 | VN100 | HNX30 …")
    pr.add_argument("--holdings", default=None,
                    help="danh mục thủ công 'FPT,MBB,HAH,HPG' (không có → đọc từ everyday API)")
    pr.add_argument("--asset-class", default="vn_stock")
    pr.add_argument("--llm-top", type=int, default=4, help="số ứng viên BUY đem LLM-verify")
    pr.add_argument("--no-llm", action="store_true", help="chỉ rule-based, không gọi LLM")
    pr.add_argument("--throttle", type=float, default=2.2, help="giây nghỉ giữa mã (tránh rate limit)")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=cmd_recommend)

    pd = sub.add_parser("advise", help="kế hoạch tháng theo PROFILE.md: rót tiền mới + bán/rotate")
    pd.add_argument("--group", default="VN30", help="rổ quét ứng viên")
    pd.add_argument("--holdings", default=None, help="'FPT:75,MBB:12' (không có → everyday API)")
    pd.add_argument("--asset-class", default="vn_stock")
    pd.add_argument("--cash", default=None, help="tiền mới tháng này (ghi đè; mặc định theo hồ sơ)")
    pd.add_argument("--cash-wallet", default=None,
                    help="lấy ngân sách = số dư ví everyday theo kind, vd 'bank' hoặc 'bank,cash'")
    pd.add_argument("--llm-top", type=int, default=5, help="số ứng viên BUY LLM-verify (text-mode)")
    pd.add_argument("--no-mcp", action="store_true", help="tắt TCBS MCP, dùng text-mode (rule-based+LLM)")
    pd.add_argument("--extra", default=None, help="ép thêm mã vào shortlist, vd 'GMD,VNM' (ngoài rổ)")
    pd.add_argument("--throttle", type=float, default=2.2)
    pd.add_argument("--json", action="store_true")
    pd.set_defaults(func=cmd_advise)

    pt = sub.add_parser("tcbs", help="phân tích 1 mã qua TCBS MCP (real-time, cần auth OAuth 1 lần)")
    pt.add_argument("symbol")
    pt.add_argument("--json", action="store_true")
    pt.set_defaults(func=cmd_tcbs)

    pv = sub.add_parser("serve", help="chạy HTTP API đọc chỉ số hiện tại")
    pv.add_argument("--host", default="127.0.0.1")
    pv.add_argument("--port", type=int, default=8787)
    pv.set_defaults(func=lambda a: __import__("vn.vn_api", fromlist=["serve"]).serve(a.host, a.port))

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
