---
title: Runbook vận hành vn-trading-agents
scope: sử dụng hàng ngày — quét EOD, kế hoạch tháng, paper-trade
updated: 2026-10-12
---

# Runbook vận hành vn-trading-agents

Chạy từ thư mục `~/dev/vn-trading-agents`. Điều kiện: đã cài đặt xong theo README (môi trường, hồ sơ khẩu vị, đăng nhập TCBS).

## 1. Hàng ngày — cuối phiên (sau ~15:00)

Chạy **1 lệnh duy nhất** → 1 báo cáo ngày gộp cảnh báo + quyết định mua/bán/giữ + xếp hạng cả rổ + phân tích chi tiết:

.venv/bin/python run.py daily --group VN30 --require-mcp

Nếu hay bị timeout (sonnet nặng), chạy model nhanh:

VN_LLM_MODEL=haiku .venv/bin/python run.py daily --group VN30 --require-mcp

`daily` gộp 3 việc cũ (watch + recommend + advise) vào 1 lần gọi LLM. `--require-mcp` bắt buộc dữ liệu TCBS real-time (rating 7 chiều + khối ngoại ròng + đồng thuận CTCK); nếu TCBS chưa đăng nhập / quá hạn, lệnh **báo lỗi** thay vì âm thầm chạy rule-based → đăng nhập lại (mục 5) rồi chạy lại. Bỏ `--require-mcp` nếu chấp nhận fallback text-mode (kém chính xác, có banner cảnh báo).

Danh mục + ngân sách (tiền mặt ví bank) lấy realtime từ everyday, không nhập tay. Báo cáo là **markdown** (render đẹp trên Obsidian/VS Code/GitHub), tự lưu vào `reports/journal/{ngày}-daily.md` — tên **cố định theo ngày**, chạy lại trong ngày thì ghi đè.

### Đọc output — vĩ mô + 5 mục

- **Đầu trang** — tâm lý tin thị trường (net, suy từ headline tài chính) + **tin thị trường đa nguồn** (CafeF · Vietstock · VnEconomy · ĐTCK, xen kẽ nguồn, mới nhất, ngày + link + nhãn nguồn bấm được).
- **`## 1. Danh mục hiện tại`** — SL / giá vốn / giá TT / giá trị / **P&L** từng vị thế + tổng P&L (từ everyday).
- **`## 2. Cảnh báo danh mục`** — mã đang giữ bị trigger (RSI≥70 / tập trung >25% NAV / SELL / thủng SMA50 / tin xấu). Không có → "danh mục ổn".
- **`## 3. Quyết định & giải ngân`** — dòng `▶ QUYẾT ĐỊNH ĐỢT NÀY` (giải ngân bao nhiêu %/hay HOLD TIỀN, kèm bán nếu có) + bảng hành động mua/bán/giữ theo lô. `◆` = mã đang giữ.
- **`## 4. Tin tức từng mã`** — mỗi mã (đang giữ + ứng viên): tâm lý (🟢/🔴/⚪ + net) + tối đa 4 headline kèm ngày, link, nguồn (CafeF/Vietstock/VnEconomy/ĐTCK/vnstock) + trích 1 dòng nội dung.
- **`## 5. Xếp hạng cả rổ`** — toàn rổ xếp theo tín hiệu (BUY→SELL), rule-based, soi cơ hội ngoài danh mục.
- **`## 6. Phân tích chi tiết`** — diễn giải sâu từng mã theo TCBS real-time: rating 7 chiều, khối ngoại, đồng thuận CTCK, điểm vào chia lệnh, rủi ro theo dõi.
- **`## Giải nghĩa thuật ngữ`** (cuối) — NAV, P/E, P/B, ROE, RSI, SMA50, golden/death cross, khối ngoại, YoY, T+2… cho người mới.

(Không truyền `--holdings` → có mục "Danh mục hiện tại" đánh số 1, phân tích chi tiết là mục 6; truyền `--holdings` thủ công thì bỏ mục danh mục, đánh số lùi 1.)

### Ví dụ output (rút gọn)

```
# BÁO CÁO NGÀY 2026-09-07 · rổ VN30

**Nguồn:** tcbs-mcp · **Ngân sách:** 122,7tr

**Tâm lý tin thị trường:** 🟢 tích cực · net +12 · 300 tin _(suy từ headline tài chính)_
> Vingroup lập kỷ lục vốn hóa 2 triệu tỉ đồng trên sàn chứng khoán

## 1. Cảnh báo danh mục
- **FPT**: tỷ trọng 68.2% > 25.0% NAV (tập trung)
- **HAH**: thủng SMA50 (close 47.2 < sma50 47.28); tin xấu mới (net -2, 8 tin)

## 2. Quyết định & giải ngân
**▶ QUYẾT ĐỊNH ĐỢT NÀY: GIẢI NGÂN 34,1tr (28%) · giữ lại 88,5tr (72%) — giải ngân thăm dò. Kèm BÁN 14,6tr.**

| Mã       | Hành động |  Lô |   Tiền |  % NS | Tín hiệu / Lý do        |
| :------- | :-------- | --: | -----: | ----: | :---------------------- |
| VNM ◆10% | GOM THÊM  |   3 | 18,6tr | 15.2% | ROE 34.5%, ngoại +261k  |
| FPT ◆68% | BÁN       |   2 | 14,6tr | 11.9% | giảm tập trung 75%→55%  |

## 3. Tin tức từng mã
| Mã  | Tâm lý | #tin | Tin gần nhất                            |
| :-- | -----: | ---: | :-------------------------------------- |
| FPT |   🟢 +2 |    7 | HBC chuyển nhượng 1 dự án cho FPT (CafeF)|

## 4. Xếp hạng cả rổ (rule-based)
| Mã       | Tín hiệu | RSI |  P/E | P/B | ROE | Khuyến nghị |
| :------- | :------- | --: | ---: | --: | --: | :---------- |
| MBB ◆11% | BUY      |  52 |  7.6 | 1.4 | 19% | GOM THÊM    |

## 5. Phân tích chi tiết (TCBS real-time)
… (rating, khối ngoại, đồng thuận CTCK, điểm vào, rủi ro) …
```

**Việc của bạn:** máy chỉ *gợi ý*. Muốn làm theo thì tự vào app chứng khoán đặt lệnh tay — không có gì tự đặt lệnh thật.

### Quy trình chuẩn: chạy EOD → đặt lệnh phiên hôm sau

Nhịp thiết kế của `daily`: chạy cuối ngày, đọc quyết định, đặt lệnh vào phiên sáng hôm sau (swing theo ngày, không lướt intraday).

1. **~18:00 (sau phiên, tối)** chạy `daily` → đọc báo cáo. Chạy sau ~15:30 để giá đóng cửa, khối ngoại ròng, RSI/SMA của ngày đã chốt; buổi tối có thêm tin phân tích sau phiên.
2. **Chốt danh sách lệnh** — mã + giá LO + số lô, tôn trọng chia đợt trong báo cáo (vd "3 lô ngay + 3 lô khi Stoch bật"). Đừng vào hết 1 lần — chia đợt là kiểm soát rủi ro, không phải trang trí.
3. **Đảm bảo tiền đã ở TK chứng khoán** — ngân sách báo cáo lấy từ ví bank everyday, nhưng đặt lệnh cần tiền nằm sẵn trong TK chứng khoán (chuyển tối trước). Lệnh nào *bán để lấy tiền mua* → tiền bán T+2 mới về, không mua ngay sáng mai bằng tiền đó.
4. **Sáng mai 9:15 (sau ATO)** đặt lệnh **LO** quanh giá tham chiếu — tránh ATO/MP mù. Giá báo cáo là giá đóng cửa hôm trước; nếu sáng mai gap tăng >2–3% so giá báo cáo thì tín hiệu "điểm vào đẹp" không còn đúng → bỏ hoặc chờ.
5. **Lệnh khớp → ghi vào sổ paper** (`paper apply` / `paper advise`) để đối chiếu hiệu quả về sau.

**Ghi đè qua đêm:** trước khi bấm lệnh sáng mai, liếc tin thế giới (mục vĩ mô có tin chứng khoán Mỹ). Đêm DJIA/S&P rơi mạnh → VN dễ đỏ → hoãn lệnh mua chờ ổn định. Tín hiệu EOD vẫn valid cho phiên kế, nhưng tin qua đêm là biến số ghi đè.

### Các lệnh lẻ (khi cần, không bắt buộc chạy hàng ngày)

`daily` đã gộp cả 3, nhưng vẫn chạy riêng được nếu muốn:

.venv/bin/python run.py watch --group VN30       # chỉ quét cảnh báo, im lặng khi ổn
.venv/bin/python run.py recommend --group VN30   # chỉ xếp hạng cả rổ
.venv/bin/python run.py advise --group VN30 --require-mcp   # chỉ kế hoạch giải ngân

### Giải nghĩa từ ngữ trong output

- **NAV / tỷ trọng** — NAV = tổng giá trị danh mục. "FPT 75.3% NAV" = FPT chiếm 75.3% tổng tài sản cổ phiếu. Càng dồn 1 mã càng rủi ro (mã đó rớt là cả danh mục rớt theo) → gọi là **tập trung**.
- **Pha loãng / giải ngân** — dùng tiền mới mua thêm mã khác để tỷ trọng mã đang quá lớn tự giảm xuống. "Giải ngân" = đem tiền rảnh đi mua.
- **Rotate (xoay)** — bán mã này để mua mã khác được cho là tốt hơn.
- **Lô** — ở VN mua cổ phiếu theo lô 100 cổ. "16 lô" = 1.600 cổ. Không mua lẻ được.
- **RSI** — thước đo 0–100 cho biết cổ phiếu đang "nóng" hay "nguội". ≥70 = mua nhiều quá, dễ điều chỉnh giảm → tránh mua đuổi. ~50–65 = bình thường.
- **SMA50** — giá trung bình 50 ngày gần nhất. Giá "thủng SMA50" (rớt xuống dưới) thường là dấu hiệu yếu đi.
- **P/E** — giá cổ phiếu so với lợi nhuận công ty. Thấp thường là "rẻ", cao là "đắt" (so trong cùng ngành).
- **ROE** — công ty sinh lời hiệu quả cỡ nào trên vốn. Cao thường tốt.
- **Score** — điểm tổng rule-based của máy; cao = hấp dẫn hơn theo tiêu chí kỹ thuật + cơ bản.
- **Phí round-trip ~0.5% / T+2** — một vòng mua-rồi-bán mất ~0.5% (phí + thuế + trượt giá), và bán xong phải chờ ~2 ngày tiền/cổ mới về (T+2). Vì vậy máy chỉ khuyên xoay khi lợi thế rõ ràng hơn 0.5%, tránh giao dịch thừa ăn mòn lời.

## 2. Hàng tuần — rà danh mục và rổ

Xếp hạng cả danh mục lẫn rổ VN30, gợi ý gom thêm / mua mới / giữ / giảm / bán theo bối cảnh danh mục.

.venv/bin/python run.py recommend --group VN30

Soi sâu 1 mã real-time khi cần quyết nhanh:

.venv/bin/python run.py tcbs VCB

Đọc bảng: dấu ◆ = mã đang giữ; BUY-WAIT = đáng mua nhưng đang nóng (chờ hạ nhiệt); cột LLM cuối là phán quyết sâu, ưu tiên khi lệch với xếp hạng nhanh.

## 3. Hàng tháng — kế hoạch rót tiền

Ra kế hoạch tháng: tiền mới rót vào đâu, bán hoặc xoay mã nào. Mặc định lấy ngân sách theo số dư ví thật.

.venv/bin/python run.py advise --group VN30

Đặt ngân sách tháng này:

.venv/bin/python run.py advise --group VN30 --cash 20000000

Cân nhắc thêm mã ngoài rổ:

.venv/bin/python run.py advise --group VN30 --extra GMD,VNM

## 4. Theo dõi hiệu quả — sổ paper-trade

Sổ giao dịch giấy chạy song song thực tế để đo agent có thật sự tốt hơn không. Chỉ đo được thất bại thô, chi phí và độ ổn định — 2–3 tháng chưa đủ kết luận.

Lập sổ một lần từ danh mục thật:

.venv/bin/python run.py paper init

Cho agent tự đặt lệnh vào sổ (chạy cùng nhịp với hàng tháng, hoặc hàng ngày):

.venv/bin/python run.py paper advise --group VN30
.venv/bin/python run.py paper watch --group VN30

Khi bơm/rút vốn thật, cập nhật sổ cho khớp:

.venv/bin/python run.py paper cash 10000000

Xem giá trị và chấm điểm định kỳ:

.venv/bin/python run.py paper mark
.venv/bin/python run.py paper score

Điểm số so 3 đường: agent (đã giao dịch) — giữ nguyên (không đụng) — VNINDEX. Agent thua "giữ nguyên" nghĩa là phí và giao dịch thừa đang ăn mòn lời.

Tự động: slot EOD (launchd 15:30) chạy `paper journal` sau báo cáo — áp các hành động của báo cáo daily hôm đó vào sổ (không gọi LLM, mỗi ngày 1 lần). Chạy tay cho ngày cụ thể:

.venv/bin/python run.py paper journal --date 2026-10-12

### Scorecard tín hiệu

Đo khuyến nghị trong các báo cáo daily so với giá thực tế sau đó. Phần "Mục 3" chấm từng lệnh MUA/BÁN của mục Quyết định & giải ngân: đặt LO đúng giá báo cáo ở phiên kế tiếp → khớp hay không, lãi/lỗ tới nay (đã trừ phí, đã quy đổi khi có chia cổ tức cổ phiếu), gộp theo báo cáo và theo mã. Phần tín hiệu: vào lệnh = giá mở cửa phiên kế tiếp, đo vượt trội so với trung bình đều cả rổ sau 5 / 10 phiên / đến nay, tách rule-based (BUY/HOLD/SELL) và LLM (actions). Kèm sổ paper và sức khoẻ pipeline (ngày fallback, ngân sách đứng yên). Giá lấy từ OHLCV đã điều chỉnh cổ tức/chia tách, ~2 phút vì giới hạn 20 req/phút của vnstock.

.venv/bin/python run.py scorecard
.venv/bin/python run.py scorecard --since 2026-10-01

Lưu `reports/scorecard/{ngày}.md`. Thứ 6 slot EOD tự chạy và gửi Telegram.

## 5. Khi gặp trục trặc

Muốn dữ liệu TCBS real-time cho `watch` / `advise` / `tcbs` — đăng nhập lại: mở `claude`, gõ `/mcp`, chọn tcbs → Authenticate (đăng nhập TCBS + iOTP), rồi chạy lệnh ngay sau đó. Lưu ý: các lệnh này có thể in `nguồn: mcp` nhưng nếu trong kết quả có dòng "Server TCBS chưa kết nối" thì thực chất đang chạy rule-based — nhãn `mcp` chỉ nghĩa là đã thử, không đảm bảo TCBS thật sự trả dữ liệu.

Lệnh MCP báo `timeout` (LLM gọi nhiều tool TCBS lâu hơn ngưỡng mặc định 240s, tự rớt về text-mode) — nới ngưỡng qua env `VN_MCP_TIMEOUT` (giây):

VN_MCP_TIMEOUT=600 .venv/bin/python run.py daily --group VN30 --require-mcp

Báo lỗi lấy dữ liệu / bị chặn tần suất — giãn nhịp rồi chạy lại:

.venv/bin/python run.py screen --group VN30 --throttle 3.0

Kiểm tra kết nối tới danh mục thật:

.venv/bin/python run.py portfolio

## Tóm tắt nhịp

- Cuối mỗi phiên: `daily --group VN30 --require-mcp` — 1 báo cáo gộp cảnh báo + quyết định mua/bán/giữ + xếp hạng cả rổ. Lưu `{ngày}-daily.md`, chạy lại ghi đè.
- Mỗi tuần: `paper mark` (định giá lại sổ paper).
- Mỗi tháng: `paper score` (chấm điểm agent vs giữ-nguyên vs VNINDEX).
- Thứ 6 (tự động): `scorecard` gửi Telegram — tín hiệu có thắng rổ không.
- Khi bơm/rút vốn thật: `paper cash` cho khớp sổ.
