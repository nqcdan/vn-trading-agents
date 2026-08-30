# vn-trading-agents

TradingAgents (multi-agent LLM trading) thích ứng cho **chứng khoán VN** (HOSE/HNX/UPCOM).
Lõi kiến trúc giữ nguyên tinh thần upstream: `analyst → bull/bear debate → trader → risk`.
Lớp dữ liệu thay bằng [`vnstock`](https://github.com/thinh-vu/vnstock); thêm ràng buộc
vi cấu trúc thị trường VN (biên độ, T+2, phí/thuế, không bán khống lẻ).

**Chạy được ngay không cần API key** (agent chạy rule-based). Có LLM (Claude qua
`claude` CLI hoặc `ANTHROPIC_API_KEY`) thì bull/bear/trader lập luận + tranh luận tiếng Việt.

## Cấu trúc

```
vn-trading-agents/
├── vn/
│   ├── vn_market.py     # biên độ ±7/10/15%, phí, thuế, slippage, lô 100, T+2
│   ├── vn_data.py       # adapter vnstock: OHLCV, indicators, fundamentals, rổ (VN30…)
│   ├── vn_news.py       # tin + sentiment: CafeF RSS, vnstock Company.news(), voz "Điểm báo"
│   ├── agents.py        # technical/fundamental/sentiment analyst, bull/bear, trader, risk, macro
│   ├── vn_backtest.py   # backtest long-only có phí+biên độ+T+2; screen cả rổ + xếp hạng
│   ├── recommend.py     # rank (danh mục ∪ rổ) → mua/bán/rotate, có LLM-verify top BUY
│   ├── advise.py        # kế hoạch tháng theo PROFILE.md: rót tiền mới + bán/rotate (1 lần LLM)
│   ├── tcbs.py          # phân tích qua TCBS MCP real-time (rating 7 chiều, đồng thuận CTCK, khối ngoại)
│   ├── profile.py       # nạp PROFILE.md, inject vào system prompt LLM
│   ├── portfolio.py     # đọc danh mục thật từ everyday API rồi phân tích từng vị thế
│   └── vn_api.py        # HTTP API (stdlib http.server) đọc chỉ số hiện tại
├── PROFILE.md           # hồ sơ NĐT cá nhân hoá (LLM đọc để khuyến nghị hợp khẩu vị)
├── run.py               # CLI: analyze | backtest | screen | recommend | advise | watch | paper | portfolio | serve
├── requirements.txt
└── TradingAgents/       # clone upstream (tham chiếu kiến trúc, gitignored)
```

## Cài đặt

```bash
cd ~/dev/vn-trading-agents
uv venv --python 3.10 .venv
VIRTUAL_ENV=.venv uv pip install -r requirements.txt
cp .env.example .env    # rồi điền: VN_LLM_BACKEND, EVERYDAY_API_BASE + token…
```

Cấu hình qua **`.env` ở root** (gitignored) — `vn` tự nạp khi import (`vn/env.py`, stdlib,
không override biến shell đã có). Không cần export vào `~/.zshrc`.

## Dùng

```bash
# Phân tích multi-agent một mã (one-shot)
.venv/bin/python run.py analyze FPT
.venv/bin/python run.py analyze VCB --json

# Backtest có phí/biên độ/T+2, so với buy&hold
.venv/bin/python run.py backtest VCB --start 2024-01-01 --end 2026-08-29

# Backtest cả rổ VN30 rồi xếp hạng theo alpha (vs buy&hold)
.venv/bin/python run.py screen --group VN30 --throttle 2.2

# Rank danh mục + rổ → khuyến nghị mua/bán/rotate (LLM-verify top BUY)
.venv/bin/python run.py recommend --holdings "FPT:75,MBB:12,HAH:8,HPG:4" --group VN30

# Kế hoạch tháng theo PROFILE.md: rót tiền mới vào đâu + bán/rotate (1 lần LLM)
.venv/bin/python run.py advise --holdings "FPT:75,MBB:12,HAH:8,HPG:4" --group VN30

# Máy quét EOD: im lặng khi không có việc, chỉ báo khi cần rotate/giải ngân
.venv/bin/python run.py watch --group VN30

# Phân tích qua TCBS MCP: dữ liệu real-time + rating 7 chiều + đồng thuận CTCK + khối ngoại
.venv/bin/python run.py tcbs FPT

# HTTP API đọc chỉ số hiện tại (local-only, stdlib)
.venv/bin/python run.py serve --port 8787

# Đọc portfolio thật từ everyday + phân tích từng vị thế
EVERYDAY_API_BASE=http://<host>:3900 EVERYDAY_ADMIN_TOKEN=<token> \
  .venv/bin/python run.py portfolio
```

### Portfolio từ everyday (`portfolio`)

Đọc danh mục thật từ dự án `everyday` (bảng `fin.wallet`) qua endpoint
`GET /api/wallet/holdings?class=vn_stock` (cần Bearer `ADMIN_TOKEN`), rồi phân tích
từng vị thế (tín hiệu + RSI + P/E + P/B) và tính P&L danh mục + tỷ trọng + macro.

Cấu hình env:
- `EVERYDAY_API_BASE` — vd `http://localhost:3900` hoặc URL server admin
- `EVERYDAY_ADMIN_TOKEN` — `ADMIN_TOKEN` của everyday (KHÔNG hardcode; truyền qua env)

Cũng có qua API: `GET /portfolio?class=vn_stock` (khi chạy `serve`). Portfolio là dữ
liệu nhạy cảm — bên everyday endpoint vẫn yêu cầu token, không public.

**Kết nối everyday thật (SSH tunnel — an toàn, không phơi net-worth ra internet):**
Admin :3900 chỉ mở trong VM (Oracle firewall chặn từ ngoài). Dùng SSH tunnel qua oracle key:

```bash
./portfolio.sh --asset-class vn_stock   # tự mở tunnel + lấy token từ VM + phân tích
```

`portfolio.sh` tự mở `ssh -L 3900:localhost:3900` (nếu chưa có), đọc `ADMIN_TOKEN` từ
`~/everyday/.env` trên VM (không lưu ra file), rồi chạy `run.py portfolio`. Consumer có
fallback `/api/wallet/holdings` → `/api/wallet` nên chạy được cả khi server chưa deploy
endpoint mới.

### HTTP API (`serve`)

Server stdlib (không thêm dependency), bind `127.0.0.1`. Endpoint trả JSON:

| Route | Nội dung |
|---|---|
| `GET /health` | trạng thái + backend LLM |
| `GET /analyze/{SYM}` | phân tích multi-agent đầy đủ (kỹ thuật+cơ bản+sentiment+macro+quyết định) |
| `GET /indicators/{SYM}` | chỉ số kỹ thuật + định giá hiện tại (P/E, P/B, ROE, RSI, SMA…) |
| `GET /sentiment/{SYM}` | tin CafeF/DN + điểm sentiment |
| `GET /macro` | tâm lý vĩ mô voz "Điểm báo" |
| `GET /screen?group=VN30&throttle=2.2` | backtest rổ + xếp hạng (chậm ~1 phút) |

```bash
curl http://127.0.0.1:8787/indicators/FPT
curl http://127.0.0.1:8787/analyze/HPG
```

### TCBS MCP — dữ liệu real-time + tín hiệu độc quyền (`tcbs`)

Khác các lệnh khác (nhồi số vnstock vào prompt), `tcbs` để **LLM tự gọi tool TCBS MCP**
lấy dữ liệu real-time + tín hiệu tool *không tự tính được*: `getGeneralRating` (điểm 7
chiều), `getHistoryRecommendation` (đồng thuận CTCK + giá mục tiêu), `getVolumeAndForeign`
(mua/bán ròng khối ngoại + RS rank), cùng P/E/P/B/ROE/RSI/MACD real-time. Reasoning theo
`PROFILE.md`.

**Cài đặt 1 lần** (cần tài khoản TCBS miễn phí):
```bash
claude mcp add --transport http tcbs https://mcp.tcbs.com.vn/mcp/tcinvest/ --scope user
claude            # phiên tương tác → gõ /mcp → chọn tcbs → Authenticate (login TCBS + iOTP)
claude mcp list | grep tcbs        # thấy "✔ Connected" là xong
```
Sau đó headless `claude -p` **tái dùng token OAuth** đã cache:
```bash
.venv/bin/python run.py tcbs FPT
```

`vn/tcbs.py::_llm_mcp()` bật `--allowedTools mcp__tcbs__*` (vẫn cấm Bash/Read/Write). MCP
chỉ dùng cho track LLM — `backtest`/`screen` giữ vnstock vì MCP không gọi được ngoài LLM
turn. Token OAuth có thể hết hạn → khi `tcbs` báo cần auth, chạy lại bước Authenticate.

### Hồ sơ NĐT (`PROFILE.md`) + kế hoạch tháng (`advise`)

`PROFILE.md` ở root là **hồ sơ đầu tư cá nhân hoá** (khẩu vị rủi ro, DCA hàng tháng, trần
số mã, ràng buộc không margin, chỉ dẫn tối ưu). `vn/profile.py` inject nó vào **system
prompt** của `trader()` → mọi quyết định LLM (`analyze`/`recommend`) tự cân theo khẩu vị.

`advise` ra kế hoạch hành động tháng, tối ưu TOÀN BỘ danh mục + dòng tiền mới. **Mặc định
dùng TCBS MCP**: rank rule-based chỉ để lọc shortlist (danh mục + top ứng viên), rồi LLM
lấy **rating 7 chiều + đồng thuận CTCK + khối ngoại real-time từ TCBS** cho shortlist và
lập kế hoạch. Tự fallback text-mode nếu TCBS chưa auth.

```bash
.venv/bin/python run.py advise --holdings "FPT:75.3,MBB:12.3,HAH:8.2,HPG:4.2" --group VN30
.venv/bin/python run.py advise --cash "30tr"          # ghi đè ngân sách tháng này
.venv/bin/python run.py advise --cash-wallet cash     # ngân sách = số dư ví cash thật (everyday)
.venv/bin/python run.py advise --group VN30 --extra "GMD,VNM"  # ép thêm mã ngoài rổ vào shortlist
.venv/bin/python run.py advise --no-mcp               # text-mode (rule-based + LLM-verify, không TCBS)
.venv/bin/python run.py advise --require-mcp          # bắt lỗi nếu TCBS chưa auth (không fallback)
```

Ngân sách **mặc định = số dư ví bank realtime từ everyday** (bỏ hardcode 23tr): `--cash`
(gõ tay) > `--cash-wallet bank[,cash]` (chỉ định ví) > ví bank mặc định. `--cash-wallet`
cần env `EVERYDAY_API_BASE` (URL API everyday, vd HTTPS public) + `EVERYDAY_ADMIN_TOKEN`.
Kế hoạch tính **theo lô 100 cp** trong ngân sách + in tiền mặt dư. `--extra` ép mã không
thuộc rổ (vd GMD ngoài VN30) vào shortlist.

Trả lời 4 phần: (1) rót tiền mới vào mã nào + tỷ lệ, (2) bán/giảm/rotate, (3) xử lý tập
trung (bán bớt vs pha loãng bằng tiền mới), (4) điểm vào (chia lệnh, tránh RSI≥70). Header
in `nguồn: tcbs-mcp | text | fallback-text`. Khi fallback text-mode có **banner cảnh báo
nổi bật** (mất rating/khối ngoại real-time) — dùng `--require-mcp` để bắt lỗi thay vì âm
thầm fallback. Cần `tcbs` MCP đã auth (xem mục trên) cho MCP-mode; `--no-mcp` chạy được
không cần TCBS.

### Máy quét EOD (`watch`)

`watch` quét cuối phiên: đọc danh mục + số dư **ví bank realtime** từ everyday, chỉ báo
khi CÓ VIỆC — **im lặng** khi danh mục ổn và không có tiền rảnh đáng kể. Khi có trigger
(RSI≥70, tập trung >25% NAV, tín hiệu SELL, thủng SMA50, tin xấu mới) hoặc đủ tiền mua ≥1
lô, LLM (TCBS MCP, fallback text) đề xuất GIỮ/GIẢM/BÁN + rotate/giải ngân, có **guard chống
churn** (chỉ xoay khi lợi thế vượt ~0.5% round-trip + bù T+2).

```bash
.venv/bin/python run.py watch --group VN30
.venv/bin/python run.py watch --holdings "FPT:75,MBB:12" --extra "GMD,VNM"
.venv/bin/python run.py watch --require-mcp           # bắt lỗi nếu TCBS chưa auth
```

Ngân sách mua = số dư ví bank realtime (không hardcode). Fallback text-mode cũng có banner
cảnh báo như `advise`.

### Paper-trade forward (`paper`)

`paper` chạy **forward-only**: khởi tạo một sổ ảo từ portfolio thật (everyday), rồi để agent
tự đề xuất **và tự áp** lệnh (agent trần, không lọc tay) vào sổ để đo xem quyết định LLM
theo thời gian ra sao. Sổ ở `reports/paper/portfolio.json`. KHÔNG backtest LLM lịch sử — chỉ
tiến về phía trước.

```bash
.venv/bin/python run.py paper init                       # seed sổ từ portfolio + số dư ví bank
.venv/bin/python run.py paper init --seed-cash 100000000 # seed tiền mặt thủ công
.venv/bin/python run.py paper cash 23000000              # nạp thêm tiền (DCA tháng)
.venv/bin/python run.py paper advise --group VN30        # agent advise → auto-apply vào sổ
.venv/bin/python run.py paper watch  --group VN30         # agent watch  → auto-apply vào sổ
.venv/bin/python run.py paper mark                       # định giá: NAV + P&L từng vị thế
.venv/bin/python run.py paper score                      # scorecard 3 đường benchmark
```

`paper advise`/`paper watch` in đề xuất, các lệnh đã áp (kèm cảnh báo thiếu tiền / cắt lô),
NAV mới sau khi áp, và **chi phí LLM lượt đó** dạng `[LLM: N spawn, Xs]` (đo số lần spawn
`claude` + wall-time — cùng dòng cost đã thêm vào `advise`/`watch`/`recommend`). Nếu agent
không đề xuất gì → in "giữ nguyên", sổ không đổi.

`paper score` là **scorecard 3 đường benchmark**: NAV của agent (đã giao dịch) vs *giữ nguyên*
(snapshot lúc init, không đụng) vs *VNINDEX*; kèm tổng phí+thuế, turnover (số lệnh), tiền mặt
hiện tại và tiền đã nạp thêm.

**Caveat:** 2–3 tháng KHÔNG đủ kết luận alpha. Cửa sổ ngắn này chỉ đo được **thất bại thô**
(agent thua giữ nguyên/VNINDEX rõ rệt), **chi phí** (phí+thuế+token) và **độ ổn định** hành
vi — không phải bằng chứng thống kê về edge.

### Cache & journal

Dữ liệu vnstock được **cache theo ngày** ở `.cache/<YYYY-MM-DD>/…` (giảm rate-limit); đặt
`VN_NO_CACHE=1` để bỏ qua cache (bust). Mỗi lần chạy `advise`/`recommend`/`watch` ghi
**audit trail** vào `reports/journal/` (JSON + `.md` tóm tắt) để tra lại "tuần/tháng trước
khuyên gì".

### Khuyến nghị danh mục (`recommend`)

Rank chung **(danh mục ∪ rổ)** theo tín hiệu *hiện tại* rồi ra khuyến nghị theo bối cảnh
danh mục. Hai tầng để cân tốc độ vs độ tin:

1. **Sàng rule-based nhanh** cả universe (technical + fundamental + **phạt P/B > 3.0** —
   mã hoá bài học "đúng chất, sai giá" của VCB).
2. **LLM-verify top BUY** (`--llm-top N`, mặc định 4): chạy `analyze()` đầy đủ để bác các
   BUY thổi phồng bởi rule-based; cột LLM in phán quyết sâu thắng khi lệch.

Cột **KHUYẾN NGHỊ** map theo vị thế: `GOM THÊM` / `MUA MỚI` / `GIỮ` / `GIẢM TỶ TRỌNG`
(mã > 25% NAV) / `BÁN` / `THEO DÕI` (BUY nhưng RSI ≥ 70, đang nóng).

```bash
# Danh mục thủ công 'SYM:tỷ_trọng' (tỷ trọng để bật cờ tập trung)
.venv/bin/python run.py recommend --holdings "FPT:75.3,MBB:12.3,HAH:8.2,HPG:4.2" --group VN30
.venv/bin/python run.py recommend --holdings "FPT,MBB" --no-llm          # nhanh, chỉ rule-based
EVERYDAY_API_BASE=http://localhost:3900 EVERYDAY_ADMIN_TOKEN=<token> \
  .venv/bin/python run.py recommend --group VN100                        # danh mục lấy từ everyday
```

Không truyền `--holdings` → đọc danh mục thật từ everyday (kèm tỷ trọng → cờ tập trung tự
bật). `--group` là rổ quét thêm ứng viên mua mới. Rate-limit vnstock → chỉnh `--throttle`.

### Screen cả rổ (`screen`)

Backtest mọi mã trong nhóm (VN30, VN100, HNX30…) với cùng chiến lược + macro haircut,
xếp hạng theo **alpha = return chiến lược − buy&hold**. Mã 0 lệnh (mới niêm yết/đổi sàn)
tách riêng, không xếp hạng. Nguồn VCI rate-limit khi gọi dồn → có `--throttle` (giây nghỉ
giữa mã) + tự retry backoff. Ví dụ VN30 2024→2026: chỉ 3/26 mã thắng buy&hold
(MCH +62%, BID +11%, SSI +4%) — minh hoạ chiến lược trend-following đơn giản thường
**thua nắm giữ** trong bull market (bỏ lỡ các mã tăng 100-284%).

### Bật LLM (bull/bear tranh luận tiếng Việt) — 2 cách

**Cách 1: subscription Claude (KHÔNG cần API key, không tính tiền per-token).**
Dùng `claude` CLI (Claude Code) đã đăng nhập sẵn — auth theo gói Pro/Max của bạn:

```bash
export VN_LLM_BACKEND=claude-cli      # dùng subscription qua claude CLI
export VN_LLM_MODEL=sonnet            # sonnet | haiku | opus
.venv/bin/python run.py analyze FPT
```

**Cách 2: API key (tính tiền theo token).**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
export VN_LLM_MODEL=claude-sonnet-4-6
.venv/bin/python run.py analyze FPT
```

Backend chọn tự động (`VN_LLM_BACKEND=auto`): có `ANTHROPIC_API_KEY` → API; nếu không
mà có `claude` CLI → subscription; nếu không có gì → rule-based (vẫn chạy). Ép cứng bằng
`VN_LLM_BACKEND=api|claude-cli|off`. Bản subscription tự tắt MCP + cấm tool để chỉ lấy
text phân tích.

## Ràng buộc thị trường VN đã mã hoá (`vn_market.py`)

| Yếu tố | Giá trị |
|---|---|
| Biên độ/phiên | HOSE ±7%, HNX ±10%, UPCOM ±15% |
| Phí mua/bán | 0.15% mỗi chiều |
| Thuế bán | 0.1% giá trị bán |
| Slippage giả định | 0.1% mỗi chiều |
| Lô | 100 |
| Thanh toán | T+2 (tiền/cổ khoá 2 phiên) |
| Bán khống | Không (bear = bán/đứng ngoài) |

## Backtest — đọc kết quả cho đúng

Backtest dùng tín hiệu **rule-based** (SMA20/50 + RSI + ROE/PE, thoát khi thủng SMA50)
để walk-forward nhanh & miễn phí. Kết quả đã trừ **phí + thuế + slippage + kẹp biên độ
+ khoá T+2**, nên đường equity KHÔNG "vô ma sát". Luôn so với cột `buy_hold_return_pct`:
thua buy&hold nghĩa là phí + whipsaw đang ăn mòn alpha (đúng bài học live-vs-backtest).

LLM để dành cho `analyze` (one-shot). Không gọi LLM mỗi phiên trong backtest vì tốn kém
và dễ dính look-ahead bias (LLM đã "biết" tương lai của dữ liệu lịch sử).

### Macro haircut theo thời gian (regime từ VNINDEX)

**Quan trọng — vì sao KHÔNG dùng voz trong backtest:** voz "Điểm báo" RSS chỉ có ~20 tin
GẦN NHẤT, không có kho lịch sử → không thể tái dựng "tâm lý voz ngày X trong quá khứ".
Nên trong backtest, macro-mood của voz được thay bằng một **proxy chế độ thị trường
backtest-được**: `risk_off = VNINDEX đóng cửa < SMA50`. Khi risk-off, lệnh MUA bị **cắt
size** theo `--haircut` (mặc định 30%). (Live thì `analyze` vẫn dùng voz thật cho macro.)

```bash
.venv/bin/python run.py backtest HPG --start 2024-01-01 --end 2026-08-29           # có haircut 30%
.venv/bin/python run.py backtest HPG --start 2024-01-01 --end 2026-08-29 --no-macro # tắt để so sánh
.venv/bin/python run.py backtest HPG --haircut 0.6                                  # cắt mạnh hơn
```

Ví dụ thực (HPG 2024-01 → 2026-08, 216/646 phiên risk-off):

| haircut | return | max_dd | CAGR |
|---:|---:|---:|---:|
| 0% (tắt) | -25.67% | 33.3% | -10.93% |
| 30% | -24.87% | 32.5% | -10.55% |
| 60% | -23.77% | 31.4% | -10.05% |
| 90% | -22.37% | 29.9% | -9.41% |

Haircut càng mạnh → **drawdown càng thấp, lỗ càng ít** ở giai đoạn chỉ số downtrend.
Đây là position-sizing theo bối cảnh, không phải cỗ máy sinh lời — xem giải thích bên dưới.

## News + Sentiment (đã nối — `vn/vn_news.py`)

Ba nguồn, chỉ dùng stdlib (không thêm dependency):

| Nguồn | Vai trò | Cần login? |
|---|---|---|
| **CafeF RSS** (3 feed: CK, doanh nghiệp, tài chính-ngân hàng) | Tin per-symbol (lọc theo mã) | Không |
| **vnstock Company.news()** (VCI) | Công bố DN + tin per-symbol (chiều sâu) | Không |
| **voz "Điểm báo"** (`f/diem-bao.33/index.rss`) | Tâm lý vĩ mô/retail cộng đồng | Không (RSS public; trang HTML bị Cloudflare chặn nhưng RSS thì không) |

Luồng:
- `sentiment_analyst(symbol)` → gom CafeF + vnstock lọc theo mã, chấm điểm bằng **lexicon tiếng Việt**
  (tăng/lãi/kỷ lục… vs giảm/lỗ/bán ròng…), tiêu đề nhân đôi trọng số → BULLISH/BEARISH/NEUTRAL,
  cộng vào điểm trader.
- `macro_mood()` → đọc voz "Điểm báo", chấm tâm lý thị trường chung. Nếu **risk-off mạnh** (net ≤ -4)
  thì `risk_manager` **cắt 30% tỷ trọng** đề xuất (position sizing theo bối cảnh vĩ mô).
- Có `ANTHROPIC_API_KEY` → sentiment agent tóm tắt tin bằng LLM tiếng Việt thay cho lexicon.

Mở rộng thêm nguồn: thêm URL RSS vào `CAFEF_FEEDS`/`VOZ_FEEDS`, hoặc viết `fetch_*()` mới
theo mẫu `_parse_feed(url, source)`. FireAnt/Vietstock/TCBS nối tương tự.

## Nối thẳng vào upstream TradingAgents (tuỳ chọn nâng cao)

Upstream (`TradingAgents/`) dùng hệ vendor-routing (`dataflows/interface.py` →
`route_to_vendor`, cấu hình qua `data_vendors` trong config). Để chạy full pipeline
upstream trên data VN: đăng ký một "vendor" mới trỏ các hàm lấy giá/fundamentals về
`vn.vn_data`, rồi set `data_vendors.core_stock_apis = "vnstock"`. Package `vn/` ở đây
là bản độc lập, chạy ngay; hướng tích hợp upstream là bước mở rộng khi cần bộ debate
đầy đủ nhiều tầng của họ.
