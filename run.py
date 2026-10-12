#!/usr/bin/env python
"""CLI: phân tích multi-agent + backtest cho cổ phiếu VN.

Ví dụ:
  python run.py analyze FPT
  python run.py backtest VCB --start 2024-01-01 --end 2026-08-29
"""
from __future__ import annotations
import argparse
import datetime
import json

from vn import (agents, vn_backtest, recommend as rec, portfolio as pf, advise as adv,
                tcbs as tcbs_mcp, watch as watch_mod, journal, paper, decision_table, scorecard, snapshot, orders,
                news_digest, market_refs, crypto_cmd)


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
    print(f"Vĩ mô tin thị trường: {mm.get('signal','?')}  ({mm.get('n',0)} tin, net {mm.get('net',0)})")
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
              f"vĩ mô tin: {res['macro']['signal']} (net {res['macro']['net']})")
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
    print("\nNguồn: everyday /api/wallet/holdings. ⚠ = RSI≥70 quá mua.")
    if a.json:
        _print(res)


def _fmt(v, w=6, d=1, suf=""):
    return f"{v:>{w}.{d}f}{suf}" if isinstance(v, (int, float)) else f"{'—':>{w}}{suf}"


def cmd_recommend(a):
    agents.cost_reset()
    res = rec.recommend(a.group, holdings_csv=a.holdings, asset_class=a.asset_class,
                        llm_top=0 if a.no_llm else a.llm_top, throttle=a.throttle)
    snap = agents.cost_snapshot()
    m = res["macro"]
    print(f"\n=== Khuyến nghị {res['group']} + danh mục | {res['n']} mã "
          f"| vĩ mô tin: {m['signal']} (net {m['net']}) ===")
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
    print(f"[LLM: {snap['spawns']} spawn, {snap['wall_s']:.0f}s]")
    journal.record("recommend", {**res, "cost": snap})
    if a.json:
        _print(res)


def cmd_advise(a):
    extra = [s for s in (a.extra or "").split(",") if s.strip()]
    cash_wallet = tuple(s.strip() for s in a.cash_wallet.split(",")) if a.cash_wallet else None
    agents.cost_reset()
    res = adv.advise(a.group, holdings_csv=a.holdings, asset_class=a.asset_class,
                     cash=a.cash, throttle=a.throttle, llm_top=a.llm_top,
                     use_mcp=not a.no_mcp, extra=extra, cash_wallet=cash_wallet,
                     require_mcp=a.require_mcp)
    snap = agents.cost_snapshot()
    if "error" in res:
        print(f"Lỗi: {res['error']}")
        return
    m = res["macro"]
    ci = res.get("cash_info")
    if ci:
        detail = ", ".join(f"{w['name']} {w['balance']:,}" for w in ci["wallets"])
        print(f"\nNgân sách (ví {'+'.join(ci['kinds'])} từ everyday): {ci['total']:,}đ — {detail}")
    if str(res.get("mode", "")).startswith("fallback"):
        print("\n⚠️  TCBS MCP KHÔNG dùng được — đang chạy TEXT-MODE (kém chính xác, thiếu rating/khối ngoại real-time).")
        print("    Khắc phục: claude → /mcp → tcbs → Authenticate. Hoặc dùng --require-mcp để bắt lỗi thay vì fallback.")
    report = (decision_table.render(res)
              + "\n\n--- Phân tích chi tiết từng mã (LLM/TCBS) ---\n\n"
              + res["plan"])
    print("\n" + report)
    if res.get("errors"):
        print(f"\n(rate-limit bỏ qua: {', '.join(e.split(':')[0] for e in res['errors'])})")
    print(f"[LLM: {snap['spawns']} spawn, {snap['wall_s']:.0f}s]")
    saved = journal.record("advise", {**res, "cost": snap}, summary_md=report)
    if saved:
        print(f"→ báo cáo: {saved}")
    if a.json:
        _print(res)


def cmd_crypto(a):
    """Báo cáo crypto (BTC/ETH…): full agent pipeline + danh mục thật everyday (asset_class=crypto).
    Lưu `{date}-crypto.md`, chạy lại ghi đè."""
    agents.cost_reset()
    syms = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else None
    res = crypto_cmd.run_crypto(symbols=syms, holdings_csv=a.holdings, cash=a.cash)
    snap = agents.cost_snapshot()
    date = f"{datetime.datetime.now():%Y-%m-%d}"
    report = crypto_cmd.render_crypto(res, date)
    print("\n" + report)
    print(f"[LLM: {snap['spawns']} spawn, {snap['wall_s']:.0f}s]")
    saved = journal.record("crypto", {**res, "cost": snap}, summary_md=report)
    if saved:
        print(f"→ báo cáo: {saved}")


def cmd_daily(a):
    """Gộp 1+2+3: cảnh báo (watch) + quyết định/giải ngân (advise) + xếp hạng cả rổ (recommend)
    → 1 báo cáo ngày `{date}-daily.md`. Chạy 1 lần advise (đã gồm ranking cả rổ), phủ thêm
    trigger rule-based trên chính dữ liệu ranking (chỉ thêm quét SMA50/tin xấu cho mã đang giữ)."""
    extra = [s for s in (a.extra or "").split(",") if s.strip()]
    cash_wallet = tuple(s.strip() for s in a.cash_wallet.split(",")) if a.cash_wallet else None
    agents.cost_reset()
    res = adv.advise(a.group, holdings_csv=a.holdings, asset_class=a.asset_class,
                     cash=a.cash, throttle=a.throttle, llm_top=0,
                     use_mcp=not a.no_mcp, extra=extra, cash_wallet=cash_wallet,
                     require_mcp=a.require_mcp)
    snap = agents.cost_snapshot()
    if "error" in res:
        print(f"Lỗi: {res['error']}")
        return
    positions = [{"symbol": r["symbol"], "weight_pct": r.get("weight_pct"),
                  "analysis": {"rsi14": r.get("rsi"), "signal": r.get("signal")}}
                 for r in res.get("ranking", []) if r.get("held") and "error" not in r]
    triggers = watch_mod._scan_triggers(positions, a.throttle)

    held_syms = [p["symbol"] for p in positions]
    news_syms = list(dict.fromkeys(held_syms + [s for s in res.get("shortlist", []) if s not in held_syms]))
    macro = news_digest.macro_digest()
    news_map = news_digest.symbols_news(news_syms)
    market_line = market_refs.market_refs_line()
    try:
        holdings = pf.fetch_holdings(a.asset_class) if not a.holdings else None
    except pf.PortfolioError:
        holdings = None

    if str(res.get("mode", "")).startswith("fallback"):
        print("\n⚠️  TCBS MCP KHÔNG dùng được — đang chạy TEXT-MODE (kém chính xác, thiếu rating/khối ngoại real-time).")
        print("    Khắc phục: claude → /mcp → tcbs → Authenticate. Hoặc dùng --require-mcp để bắt lỗi thay vì fallback.")
    date = f"{datetime.datetime.now():%Y-%m-%d}"
    detail_no = 6 if holdings else 5
    report = (decision_table.render_daily(res, triggers, date, macro=macro, news_map=news_map,
                                          holdings=holdings, market_line=market_line)
              + f"\n\n## {detail_no}. Phân tích chi tiết (TCBS real-time)\n\n"
              + decision_table.strip_json(res["plan"])
              + "\n\n" + decision_table.render_glossary())
    print("\n" + report)
    print(f"[LLM: {snap['spawns']} spawn, {snap['wall_s']:.0f}s]")
    saved = journal.record("daily", {**res, "triggers": triggers, "macro_digest": macro,
                                      "news": news_map, "cost": snap}, summary_md=report)
    if saved:
        print(f"→ báo cáo: {saved}")
    if a.json:
        _print(res)


def cmd_tcbs(a):
    try:
        res = tcbs_mcp.analyze_tcbs(a.symbol)
    except tcbs_mcp.TcbsError as e:
        print(f"TCBS MCP lỗi: {e}")
        return
    ok = res.get("tcbs_ok", True)
    src = "TCBS MCP (real-time)" if ok else "RULE-BASED (TCBS ngắt — KHÔNG có real-time)"
    print(f"\n=== {res['symbol']} qua {src} ===\n")
    print(res["analysis"])
    if ok:
        print("\n— Dữ liệu TCBS real-time + PROFILE.md.")
    else:
        print("\n⚠️  TCBS server không kết nối trong phiên — phân tích dựa số liệu EOD sẵn có, "
              "thiếu rating/đồng thuận CTCK/khối ngoại. Đăng nhập lại: claude → /mcp → tcbs → Authenticate.")
    if a.json:
        _print(res)


def cmd_watch(a):
    extra = [s for s in (a.extra or "").split(",") if s.strip()]
    agents.cost_reset()
    res = watch_mod.watch(asset_class=a.asset_class, holdings_csv=a.holdings,
                          require_mcp=a.require_mcp, throttle=a.throttle,
                          extra=extra, group=a.group)
    snap = agents.cost_snapshot()
    if "error" in res:
        print(f"Lỗi: {res['error']}")
        return
    if res.get("silent"):
        print("✓ Không có tín hiệu hành động hôm nay (danh mục ổn, không có tiền rảnh đáng kể).")
        print(f"[LLM: {snap['spawns']} spawn, {snap['wall_s']:.0f}s]")
        journal.record("watch", {**res, "cost": snap})
        return
    print(f"\n=== Watch EOD | rổ {res.get('group')} | nguồn: {res.get('mode')} ===")
    for t in res.get("triggers", []):
        print(f"• {t['symbol']}: " + "; ".join(t.get("reasons", [])))
    if res.get("proposal"):
        print(f"\n{res['proposal']}")
    b = res.get("budget")
    if b:
        print(f"\nNgân sách (ví bank realtime): {b:,}đ")
    if str(res.get("mode", "")).startswith("fallback"):
        print("\n⚠️  TCBS MCP KHÔNG dùng được — đang chạy TEXT-MODE (kém chính xác, thiếu rating/khối ngoại real-time).")
        print("    Khắc phục: claude → /mcp → tcbs → Authenticate. Hoặc dùng --require-mcp để bắt lỗi thay vì fallback.")
    print(f"[LLM: {snap['spawns']} spawn, {snap['wall_s']:.0f}s]")
    journal.record("watch", {**res, "cost": snap}, summary_md=res.get("proposal") or "")
    if a.json:
        _print(res)


def _print_mark(m):
    print(f"NAV: {m['nav']:,.0f}đ  (tiền mặt {m['cash']:,.0f}đ + cổ phiếu {m['market_value']:,.0f}đ)")
    if m["positions"]:
        print(f"{'MÃ':6} {'SL':>7} {'giá vốn':>10} {'giá':>10} {'thị giá':>14} {'lãi/lỗ':>14}")
        for p in m["positions"]:
            print(f"{p['symbol']:6} {p['qty']:>7} {p['avg_cost']:>10,.0f} {p['price']:>10,.0f} "
                  f"{p['market_value']:>14,.0f} {p['unrealized_pnl']:>+14,.0f}")
    for n in m.get("notes", []):
        print(f"  · {n}")


def _paper_agent(a, kind):
    agents.cost_reset()
    if kind == "advise":
        extra = [s for s in (a.extra or "").split(",") if s.strip()]
        res = adv.advise(a.group, holdings_csv=a.holdings, asset_class=a.asset_class,
                         use_mcp=not a.no_mcp, extra=extra)
        text = res.get("plan") or ""
    else:
        extra = [s for s in (a.extra or "").split(",") if s.strip()]
        res = watch_mod.watch(asset_class=a.asset_class, holdings_csv=a.holdings,
                              extra=extra, group=a.group)
        text = res.get("proposal") or ""
    snap = agents.cost_snapshot()
    if "error" in res:
        print(f"Lỗi: {res['error']}")
        return
    acts = res.get("actions") or []
    print(f"\n=== paper {kind} | nguồn: {res.get('mode')} ===\n")
    if text:
        print(text.strip())
    if not acts:
        print("\nagent không đề xuất hành động nào (giữ nguyên).")
        print(f"[LLM: {snap['spawns']} spawn, {snap['wall_s']:.0f}s]")
        journal.record(f"paper-{kind}", {**res, "cost": snap, "applied": []})
        return
    out = paper.apply(acts)
    print("\n— Đã áp vào sổ paper:")
    for act in acts:
        print(f"  {act.get('action')} {act.get('symbol')} {act.get('lots')} lô @ {act.get('price'):,.0f}"
              + (f"  ({act.get('reason')})" if act.get('reason') else ""))
    for w in out.get("warnings", []):
        print(f"  ⚠ {w}")
    print()
    _print_mark(paper.mark())
    print(f"[LLM: {snap['spawns']} spawn, {snap['wall_s']:.0f}s]")
    journal.record(f"paper-{kind}", {**res, "cost": snap, "applied": acts})


def cmd_paper(a):
    act = a.action
    ac = getattr(a, "asset_class", "vn_stock")
    unit = "đ"  # hạch toán chung VND (crypto quy đổi giá USD→VND theo tỷ giá)
    if act == "init":
        try:
            book = paper.init(ac, seed_cash=a.seed_cash)
        except paper.PaperError as e:
            print(f"Lỗi: {e}")
            print(f"Xoá sổ cũ nếu muốn init lại: rm {paper._book_path(ac)}")
            return
        print(f"✓ Khởi tạo sổ paper ({ac}).")
        print(f"Tiền mặt seed: {book['cash']:,.0f}{unit} | {len(book['positions'])} vị thế")
        for s, v in book["positions"].items():
            print(f"  {s}: {v['qty']} @ {v['avg_cost']:,.4f}")
    elif act == "cash":
        book = paper.inject_cash(a.amount, asset_class=ac)
        print(f"✓ Nạp {a.amount:,.0f}{unit}. Tiền mặt mới: {book['cash']:,.0f}{unit}")
    elif act == "mark":
        _print_mark(paper.mark(asset_class=ac))
    elif act == "score":
        s = paper.score(ac)
        print("\n=== Scorecard paper (3 đường benchmark) ===")
        print(f"{'Agent (đã giao dịch)':28} {s['agent_nav']:>16,.0f}{unit}")
        print(f"{'Giữ nguyên (không đụng)':28} {s['hold_nav']:>16,.0f}{unit}")
        bench = ("BTC", s.get("btc")) if ac != "vn_stock" else ("VNINDEX (điểm)", s.get("vnindex"))
        print(f"{bench[0]:28} " + (f"{bench[1]:>16,.0f}" if bench[1] is not None else f"{'—':>16}"))
        print(f"\nTiền mặt: {s['cash_now']:,.0f}đ | đã nạp thêm: {s['cash_injected']:,.0f}đ")
        print(f"Tổng phí+thuế: {s['total_fees_tax']:,.0f}đ | số lệnh (turnover): {s['turnover_trades']}")
        for n in s.get("notes", []):
            print(f"  · {n}")
        print("\nCaveat: 2–3 tháng KHÔNG đủ kết luận alpha — chỉ đo thất bại thô + chi phí + độ ổn định.")
    elif act == "advise":
        _paper_agent(a, "advise")
    elif act == "watch":
        _paper_agent(a, "watch")


def cmd_orders(a):
    print(orders.morning_text(a.date))


def cmd_snapshot(a):
    try:
        path, md = snapshot.run(a.throttle)
    except pf.PortfolioError as e:
        print(f"Lỗi everyday: {e}")
        raise SystemExit(1)
    print(md)
    print(f"→ snapshot: {path}")


def cmd_scorecard(a):
    md = scorecard.render(scorecard.build(a.since, a.throttle))
    print(md)
    print(f"→ scorecard: {scorecard.save(md)}")


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
    pd.add_argument("--require-mcp", action="store_true",
                    help="bắt lỗi nếu TCBS MCP không dùng được (không âm thầm fallback text)")
    pd.add_argument("--extra", default=None, help="ép thêm mã vào shortlist, vd 'GMD,VNM' (ngoài rổ)")
    pd.add_argument("--throttle", type=float, default=2.2)
    pd.add_argument("--json", action="store_true")
    pd.set_defaults(func=cmd_advise)

    pdl = sub.add_parser("daily", help="BÁO CÁO NGÀY gộp: cảnh báo + quyết định/giải ngân + xếp hạng cả rổ → 1 report")
    pdl.add_argument("--group", default="VN30", help="rổ quét")
    pdl.add_argument("--holdings", default=None, help="'FPT:75,MBB:12' (không có → everyday API)")
    pdl.add_argument("--asset-class", default="vn_stock")
    pdl.add_argument("--cash", default=None, help="tiền mới (ghi đè; mặc định = ví bank realtime)")
    pdl.add_argument("--cash-wallet", default=None, help="ngân sách = số dư ví everyday, vd 'bank'")
    pdl.add_argument("--no-mcp", action="store_true", help="tắt TCBS MCP, dùng text-mode")
    pdl.add_argument("--require-mcp", action="store_true",
                     help="bắt lỗi nếu TCBS MCP không dùng được (khuyến nghị cho báo cáo ngày)")
    pdl.add_argument("--extra", default=None, help="ép thêm mã vào shortlist, vd 'GMD,VNM'")
    pdl.add_argument("--throttle", type=float, default=2.2)
    pdl.add_argument("--json", action="store_true")
    pdl.set_defaults(func=cmd_daily)

    pcr = sub.add_parser("crypto", help="BÁO CÁO CRYPTO (BTC/ETH): agent pipeline + danh mục thật everyday")
    pcr.add_argument("--symbols", default=None, help="'BTC,ETH,SOL' (không có → VN_CRYPTO_SYMBOLS hoặc BTC,ETH)")
    pcr.add_argument("--holdings", default=None, help="'BTC:0.1,ETH:2' (không có → everyday asset_class=crypto)")
    pcr.add_argument("--cash", default=None, help="ngân sách (không có → ví bank realtime everyday)")
    pcr.set_defaults(func=cmd_crypto)

    pw = sub.add_parser("watch", help="máy quét EOD: im lặng khi không có việc, đề xuất rotate/giải ngân")
    pw.add_argument("--asset-class", default="vn_stock", help="vn_stock | vn_fund | crypto")
    pw.add_argument("--holdings", default=None, help="'FPT:75,MBB:12' (không có → everyday API)")
    pw.add_argument("--group", default="VN30", help="rổ quét ứng viên rotate/giải ngân")
    pw.add_argument("--extra", default=None, help="ép thêm mã vào ứng viên, vd 'GMD,VNM'")
    pw.add_argument("--require-mcp", action="store_true",
                    help="bắt lỗi nếu TCBS MCP không dùng được (không âm thầm fallback text)")
    pw.add_argument("--throttle", type=float, default=2.2)
    pw.add_argument("--json", action="store_true")
    pw.set_defaults(func=cmd_watch)

    pt = sub.add_parser("tcbs", help="phân tích 1 mã qua TCBS MCP (real-time, cần auth OAuth 1 lần)")
    pt.add_argument("symbol")
    pt.add_argument("--json", action="store_true")
    pt.set_defaults(func=cmd_tcbs)

    ppa = sub.add_parser("paper", help="paper-trade forward: agent trần auto-apply + scorecard 3 đường")
    psub = ppa.add_subparsers(dest="action", required=True)
    pi = psub.add_parser("init", help="khởi tạo sổ từ portfolio everyday (seed cash + vị thế)")
    pi.add_argument("--asset-class", default="vn_stock")
    pi.add_argument("--seed-cash", type=float, default=None, help="tiền mặt seed (mặc định số dư ví bank)")
    pc = psub.add_parser("cash", help="nạp thêm tiền mặt vào sổ")
    pc.add_argument("amount", type=float)
    pc.add_argument("--asset-class", default="vn_stock")
    pm = psub.add_parser("mark", help="định giá sổ hiện tại: NAV + P&L từng vị thế")
    pm.add_argument("--asset-class", default="vn_stock")
    psc = psub.add_parser("score", help="scorecard: agent vs giữ nguyên vs VNINDEX/BTC + phí/turnover")
    psc.add_argument("--asset-class", default="vn_stock")
    for name in ("advise", "watch"):
        pag = psub.add_parser(name, help=f"agent {name} → auto-apply vào sổ paper + đo chi phí LLM")
        pag.add_argument("--group", default="VN30")
        pag.add_argument("--holdings", default=None)
        pag.add_argument("--asset-class", default="vn_stock")
        pag.add_argument("--extra", default=None, help="ép thêm mã vào shortlist, vd 'GMD,VNM'")
        pag.add_argument("--no-mcp", action="store_true", help="tắt TCBS MCP, dùng text-mode")
    ppa.set_defaults(func=cmd_paper)

    psc2 = sub.add_parser("scorecard", help="hiệu suất lệnh mục 3 từng báo cáo daily (LO khớp, lãi/lỗ sau phí) + sức khoẻ pipeline")
    psc2.add_argument("--since", default=None, help="YYYY-MM-DD")
    psc2.add_argument("--throttle", type=float, default=3.3)
    psc2.set_defaults(func=cmd_scorecard)

    po = sub.add_parser("orders", help="phiếu lệnh buổi sáng từ bảng 'Lệnh đặt cụ thể' của báo cáo gần nhất (không LLM)")
    po.add_argument("--date", default=None, help="hôm nay (YYYY-MM-DD) — lấy báo cáo trước ngày này")
    po.set_defaults(func=cmd_orders)

    psn = sub.add_parser("snapshot", help="chụp danh mục thật hôm nay → reports/portfolio/{ngày}.md (so ngày trước + đối chiếu mục 3)")
    psn.add_argument("--throttle", type=float, default=3.3)
    psn.set_defaults(func=cmd_snapshot)

    pv = sub.add_parser("serve", help="chạy HTTP API đọc chỉ số hiện tại")
    pv.add_argument("--host", default="127.0.0.1")
    pv.add_argument("--port", type=int, default=8787)
    pv.set_defaults(func=lambda a: __import__("vn.vn_api", fromlist=["serve"]).serve(a.host, a.port))

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
