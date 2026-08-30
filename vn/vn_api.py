"""HTTP API đọc chỉ số hiện tại — stdlib http.server, không thêm dependency.

Chạy: python run.py serve --port 8787
  GET /health
  GET /analyze/{SYM}       phân tích multi-agent đầy đủ (indicators+fundamentals+sentiment+macro+quyết định)
  GET /indicators/{SYM}    chỉ số kỹ thuật + định giá hiện tại (P/E, P/B, ROE, RSI…)
  GET /sentiment/{SYM}     tin CafeF/DN + điểm sentiment
  GET /macro               tâm lý vĩ mô từ voz "Điểm báo"
  GET /screen?group=VN30&throttle=2.2&haircut=0.3&no_macro=0   backtest cả rổ + xếp hạng
"""
from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import agents, vn_data, vn_news, vn_backtest, portfolio as pf

ROUTES_DOC = {
    "GET /health": "trạng thái + backend LLM",
    "GET /analyze/{SYM}": "phân tích multi-agent đầy đủ",
    "GET /indicators/{SYM}": "kỹ thuật + định giá hiện tại",
    "GET /sentiment/{SYM}": "tin + sentiment",
    "GET /macro": "tâm lý vĩ mô voz",
    "GET /portfolio?class=vn_stock": "đọc portfolio từ everyday + phân tích vị thế",
    "GET /screen?group=VN30": "backtest rổ + xếp hạng (chậm ~1 phút)",
}


def _indicators(sym: str) -> dict:
    ind = vn_data.get_indicators(sym)
    fund = vn_data.get_fundamentals(sym)
    return {"symbol": sym.upper(), "indicators": ind, "fundamentals": fund}


def _sentiment(sym: str) -> dict:
    items = vn_news.get_news(sym)
    return {"symbol": sym.upper(), "sentiment": vn_news.score_sentiment(items),
            "items": items}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # tắt log ồn ào
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if not parts:
                return self._send({"service": "vn-trading-agents API", "routes": ROUTES_DOC})
            head = parts[0].lower()
            if head == "health":
                return self._send({"ok": True, "llm_backend": agents._backend(),
                                   "llm_available": agents._llm_available()})
            if head == "macro":
                return self._send(agents.macro_mood())
            if head == "portfolio":
                try:
                    return self._send(pf.analyze_portfolio(q.get("class", "vn_stock")))
                except pf.PortfolioError as e:
                    return self._send({"error": str(e)}, 502)
            if head in ("analyze", "indicators", "sentiment"):
                if len(parts) < 2:
                    return self._send({"error": f"thiếu mã: /{head}/FPT"}, 400)
                sym = parts[1].upper()
                if head == "analyze":
                    return self._send(agents.analyze(sym))
                if head == "indicators":
                    return self._send(_indicators(sym))
                return self._send(_sentiment(sym))
            if head == "screen":
                return self._send(vn_backtest.screen_group(
                    group=q.get("group", "VN30"),
                    use_macro=q.get("no_macro", "0") not in ("1", "true"),
                    macro_haircut=float(q.get("haircut", "0.30")),
                    throttle=float(q.get("throttle", "2.2"))))
            return self._send({"error": "not found", "routes": ROUTES_DOC}, 404)
        except BaseException as e:  # gồm SystemExit của vnstock khi rate-limit
            return self._send({"error": f"{type(e).__name__}: {str(e)[:200]}"}, 500)


def serve(host: str = "127.0.0.1", port: int = 8787):
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"vn-trading-agents API → http://{host}:{port}  (Ctrl-C để dừng)")
    for r, d in ROUTES_DOC.items():
        print(f"  {r:32} {d}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
