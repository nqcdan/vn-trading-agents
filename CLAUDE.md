# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Mục đích

TradingAgents (multi-agent LLM trading) thích ứng cho **chứng khoán VN** (HOSE/HNX/UPCOM). Giữ tinh thần pipeline upstream (`analyst → bull/bear debate → trader → risk`) nhưng thay lớp dữ liệu bằng [`vnstock`](https://github.com/thinh-vu/vnstock) và mã hoá vi cấu trúc thị trường VN (biên độ, T+2, phí/thuế, không bán khống lẻ). Công cụ **nghiên cứu/giáo dục**, không phải khuyến nghị đầu tư.

## Setup & Commands

```bash
uv venv --python 3.10 .venv
VIRTUAL_ENV=.venv uv pip install -r requirements.txt

.venv/bin/python run.py analyze FPT                 # multi-agent một mã (one-shot)
.venv/bin/python run.py analyze VCB --json          # + full JSON
.venv/bin/python run.py backtest VCB --start 2024-01-01 --end 2026-08-29
.venv/bin/python run.py screen --group VN30 --throttle 2.2   # backtest cả rổ rồi xếp hạng
.venv/bin/python run.py recommend --holdings "FPT:75,MBB:12" --group VN30  # rank DM+rổ → mua/bán/rotate
.venv/bin/python run.py advise --holdings "FPT:75,MBB:12" --group VN30     # kế hoạch tháng theo PROFILE.md
.venv/bin/python run.py tcbs FPT                     # phân tích qua TCBS MCP (real-time, tín hiệu giàu)
.venv/bin/python run.py serve --port 8787            # HTTP API đọc chỉ số hiện tại
```

**TCBS MCP** (`vn/tcbs.py`, lệnh `tcbs`): LLM tự gọi tool `mcp__tcbs__*` lấy dữ liệu TCBS **real-time** + tín hiệu độc quyền không tự tính được — `getGeneralRating` (điểm 7 chiều), `getHistoryRecommendation` (đồng thuận CTCK + giá mục tiêu), `getVolumeAndForeign` (khối ngoại + RS rank). Điều kiện: đã `claude mcp add --transport http tcbs https://mcp.tcbs.com.vn/mcp/tcinvest/ --scope user` + auth OAuth **1 lần** tương tác (`claude` → `/mcp` → tcbs → Authenticate, login TCBS + iOTP); sau đó headless `claude -p` tái dùng token. Khác `_llm_via_cli` (tắt hết tool), `_llm_mcp` BẬT `mcp__tcbs__*` nhưng vẫn cấm Bash/Read/Write. MCP chỉ dùng cho track LLM (`analyze`/`advise`/`tcbs`) — `backtest`/`screen` vẫn vnstock (MCP không gọi được ngoài LLM turn).

**`PROFILE.md`** (root) = hồ sơ NĐT cá nhân hoá (khẩu vị rủi ro, DCA ~23tr/tháng về ngày 1, trần ≤8–10 mã, không margin, chỉ dẫn tối ưu). `vn/profile.py::profile_system()` inject nó vào system prompt của `trader()` → mọi quyết định LLM hợp khẩu vị. `advise` gói (profile + rank rule-based + vĩ mô) thành **1 lần gọi LLM** ra kế hoạch: rót tiền mới vào đâu, bán/rotate gì, xử lý tập trung FPT.

`recommend` sàng rule-based nhanh cả (danh mục ∪ rổ) rồi **LLM-verify top BUY** (`--llm-top N`, mặc định 4) để chống rule-based thổi phồng; khuyến nghị theo bối cảnh danh mục: GOM THÊM / MUA MỚI / GIỮ / GIẢM TỶ TRỌNG (mã >25% NAV) / BÁN. Danh mục lấy từ `--holdings "SYM:tỷ_trọng,…"` hoặc everyday API (khi không truyền `--holdings`). Mã hoá bài học VCB: P/B > 3.0 bị phạt điểm (đúng chất, sai giá).

Bảng `screen` có cột **P/E, P/B, RSI HIỆN TẠI** (đánh giá bây giờ) tách khỏi `return/alpha` (quá khứ); RSI ≥ 70 gắn cờ `←quá mua`. Mã 0 lệnh (mới niêm yết/đổi sàn) tách riêng, không xếp hạng.

Không có test suite trong package `vn/`. Chạy CLI là cách verify chính.

### Bật LLM (tùy chọn — không có thì agent chạy rule-based)

Backend chọn tự động qua `VN_LLM_BACKEND=auto` (mặc định): có `ANTHROPIC_API_KEY` → API (tính token); nếu không mà có `claude` CLI đã login → subscription (miễn phí per-token); nếu không có gì → rule-based. Ép cứng: `VN_LLM_BACKEND=api|claude-cli|off`. Model: `VN_LLM_MODEL` (`sonnet|haiku|opus` cho CLI, `claude-sonnet-4-6…` cho API). Backend `claude-cli` tự tắt MCP + cấm tool để chỉ lấy text.

## Kiến trúc

Package độc lập nằm ở `vn/` (chạy ngay, không phụ thuộc thư mục `TradingAgents/` — cái đó chỉ là clone upstream tham chiếu, gitignored). Luồng qua các file:

- **`vn/vn_market.py`** — single source of truth cho ràng buộc thị trường: biên độ HOSE ±7% / HNX ±10% / UPCOM ±15%, phí 0.15%/chiều, thuế bán 0.1%, slippage 0.1%, lô 100, khoá T+2, không bán khống. Mọi tính toán giá/lệnh phải kẹp qua đây.
- **`vn/vn_data.py`** — adapter `vnstock`: OHLCV, indicators (SMA/RSI), fundamentals (ROE/PE). Có rate limit → `screen` dùng `--throttle`.
- **`vn/vn_news.py`** — 3 nguồn stdlib-only: CafeF RSS + `vnstock Company.news()` (tin per-symbol), voz "Điểm báo" RSS (tâm lý vĩ mô). Chấm điểm bằng lexicon tiếng Việt; mở rộng nguồn qua `_parse_feed(url, source)`.
- **`vn/agents.py`** — các agent: `technical_analyst`, `fundamental_analyst`, `sentiment_analyst`, `bull_bear_debate`, `trader`, `macro_mood`, `risk_manager`, gom bởi `analyze()`. LLM gate qua `_backend()`/`_llm()`; agent luôn có nhánh rule-based fallback.
- **`vn/vn_backtest.py`** — walk-forward long-only, tín hiệu **rule-based** (SMA20/50 + RSI + ROE/PE, thoát khi thủng SMA50), đã trừ phí+thuế+slippage+biên độ+T+2. `screen_group()` chạy cả rổ.
- **`vn/tcbs.py`** — `analyze_tcbs()` + `_llm_mcp()`: phân tích qua TCBS MCP real-time. Bật `mcp__tcbs__*`, cấm Bash/Read/Write, không `--strict-mcp-config` (để nạp tcbs user-scope). `TcbsError` khi chưa auth. Inject `profile_system()`.
- **`vn/profile.py`** — nạp `PROFILE.md` (root), `profile_system()` ghép vào system prompt LLM. `trader()` dùng nó → khuyến nghị hợp khẩu vị.
- **`vn/advise.py`** — `advise()` 2 chế độ: **MCP (mặc định)** rank rule-based chỉ để lọc shortlist (danh mục + top `MAX_CANDIDATES` ứng viên) → `_llm_mcp` để LLM lấy rating/đồng thuận CTCK/khối ngoại TCBS thật rồi lập kế hoạch; fallback text-mode nếu `TcbsError`. **Text (`--no-mcp`)**: rank + LLM-verify top → 1 prompt `_llm`. `mode` in ở header (`tcbs-mcp` | `text` | `fallback-text`).
- **`vn/recommend.py`** — rank (danh mục ∪ rổ) 2 tầng: sàng rule-based nhanh (`_screen_one`, có P/B penalty) → LLM-verify top BUY (`analyze()`); `_action()` map tín hiệu → khuyến nghị theo bối cảnh danh mục (concentration cap 25% NAV).
- **`vn/portfolio.py`** — đọc portfolio thật từ dự án `everyday` (`GET /api/wallet/holdings?class=vn_stock`, Bearer `ADMIN_TOKEN`) rồi phân tích từng vị thế + P&L danh mục. Env: `EVERYDAY_API_BASE`, `EVERYDAY_ADMIN_TOKEN` (KHÔNG hardcode token). Portfolio nhạy cảm → endpoint everyday giữ auth, không public.
- **`vn/vn_api.py`** — HTTP API stdlib (`http.server`, không thêm dependency). Endpoint: `/health`, `/analyze/{SYM}`, `/indicators/{SYM}`, `/sentiment/{SYM}`, `/macro`, `/screen?group=VN30&throttle=2.2&haircut=0.3&no_macro=0`. Trả JSON; bind `127.0.0.1` mặc định (local-only). Bắt `BaseException` để nuốt `SystemExit` rate-limit của vnstock.
- **`run.py`** — CLI argparse, 8 subcommand `analyze|backtest|screen|recommend|advise|tcbs|serve|portfolio`.

### Bất biến quan trọng khi sửa code

- **LLM chỉ dùng ở `analyze` (one-shot), KHÔNG gọi trong backtest** — tránh look-ahead bias (LLM đã "biết" tương lai của data lịch sử) và chi phí.
- **Macro trong backtest ≠ macro trong live.** voz RSS chỉ có ~20 tin gần nhất, không tái dựng được lịch sử → backtest thay bằng proxy regime `risk_off = VNINDEX < SMA50`, cắt size lệnh MUA theo `--haircut` (mặc định 0.30). Live `analyze` vẫn dùng voz thật.
- **Đọc backtest luôn so `buy_hold_return_pct`** (cột `alpha` = return − buy&hold). Thua buy&hold = phí + whipsaw ăn mòn alpha.
- Mọi agent phải giữ nhánh rule-based fallback để chạy được khi không có LLM.

Note: `AGENTS.md` ở root là bootstrap tự sinh của vnstock (gitignored), không liên quan kiến trúc dự án này.
