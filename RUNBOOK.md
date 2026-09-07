---
title: Runbook vận hành vn-trading-agents
scope: sử dụng hàng ngày — quét EOD, kế hoạch tháng, paper-trade
updated: 2026-09-07
---

# Runbook vận hành vn-trading-agents

Chạy từ thư mục `~/dev/vn-trading-agents`. Điều kiện: đã cài đặt xong theo README (môi trường, hồ sơ khẩu vị, đăng nhập TCBS).

## 1. Hàng ngày — cuối phiên (sau ~15:00)

Chạy **1 lệnh duy nhất** → 1 báo cáo ngày gộp cảnh báo + quyết định mua/bán/giữ + xếp hạng cả rổ + phân tích chi tiết:

.venv/bin/python run.py daily --group VN30 --require-mcp

Nếu hay bị timeout (sonnet nặng), chạy model nhanh:

VN_LLM_MODEL=haiku .venv/bin/python run.py daily --group VN30 --require-mcp

`daily` gộp 3 việc cũ (watch + recommend + advise) vào 1 lần gọi LLM. `--require-mcp` bắt buộc dữ liệu TCBS real-time (rating 7 chiều + khối ngoại ròng + đồng thuận CTCK); nếu TCBS chưa đăng nhập / quá hạn, lệnh **báo lỗi** thay vì âm thầm chạy rule-based → đăng nhập lại (mục 5) rồi chạy lại. Bỏ `--require-mcp` nếu chấp nhận fallback text-mode (kém chính xác, có banner cảnh báo).

Danh mục + ngân sách (tiền mặt ví bank) lấy realtime từ everyday, không nhập tay. Báo cáo tự lưu vào `reports/journal/{ngày}-daily.md` — tên **cố định theo ngày**, chạy lại trong ngày thì ghi đè.

### Đọc output — 4 khối

1. **`## 1. CẢNH BÁO DANH MỤC`** — mã đang giữ bị trigger (RSI≥70 / tập trung >25% NAV / SELL / thủng SMA50 / tin xấu). Không có → "danh mục ổn".
2. **`## 2. QUYẾT ĐỊNH & GIẢI NGÂN`** — dòng `▶ QUYẾT ĐỊNH ĐỢT NÀY` (giải ngân bao nhiêu %/hay HOLD TIỀN) + bảng hành động mua/bán/giữ theo lô. `◆` = mã đang giữ.
3. **`## 3. XẾP HẠNG CẢ RỔ`** — toàn bộ rổ xếp theo tín hiệu (BUY→SELL), rule-based, để soi cơ hội ngoài danh mục.
4. **`## 4. PHÂN TÍCH CHI TIẾT`** — diễn giải sâu từng mã theo TCBS real-time: rating, khối ngoại, đồng thuận CTCK, điểm vào chia lệnh.

### Ví dụ output (rút gọn)

```
=== BÁO CÁO NGÀY 2026-09-07 — VN30 | nguồn: tcbs-mcp | vĩ mô voz: BULLISH (net 4) | ngân sách: 122,7tr ===

## 1. CẢNH BÁO DANH MỤC
• FPT: tỷ trọng 68.2% > 25.0% NAV (tập trung)
• HAH: thủng SMA50 (close 47.2 < sma50 47.28); tin xấu mới (net -2, 8 tin)

## 2. QUYẾT ĐỊNH & GIẢI NGÂN
▶ QUYẾT ĐỊNH ĐỢT NÀY: GIẢI NGÂN 84,5tr (69%) · giữ lại 38,2tr (31%) — giải ngân phần lớn.

┌──────────┬───────────┬────┬────────┬───────┬──────────────────────────────────┐
│ Mã       │ Hành động │ Lô │   Tiền │  % NS │ Tín hiệu / Lý do                 │
├──────────┼───────────┼────┼────────┼───────┼──────────────────────────────────┤
│ HDB      │ MUA MỚI   │  8 │ 21,8tr │ 17.7% │ NH mid-cap, P/E 7.1, ROE 25.8%   │
│ FPT ◆68% │ GOM THÊM  │  5 │ 36,4tr │ 29.7% │ khối ngoại MUA +960k, rating 3/5 │
│ VNM ◆10% │ GIỮ       │  — │      — │     — │ RSI 54 · P/E 11.8 · ROE 34%      │
└──────────┴───────────┴────┴────────┴───────┴──────────────────────────────────┘

## 3. XẾP HẠNG CẢ RỔ (rule-based)
┌──────────┬──────────┬─────┬──────┬─────┬─────┬─────────────┐
│ Mã       │ Tín hiệu │ RSI │  P/E │ P/B │ ROE │ Khuyến nghị │
├──────────┼──────────┼─────┼──────┼─────┼─────┼─────────────┤
│ MBB ◆11% │ BUY      │  52 │  7.6 │ 1.4 │ 19% │ GOM THÊM    │
│ …        │          │     │      │     │     │             │
└──────────┴──────────┴─────┴──────┴─────┴─────┴─────────────┘

## 4. PHÂN TÍCH CHI TIẾT (LLM/TCBS)
### FPT — GOM THÊM … (khối ngoại mua ròng, rating, điểm vào chia lệnh…)
…
[LLM: 1 spawn, 124s]
→ báo cáo: reports/journal/2026-09-07-daily.md
```

**Việc của bạn:** máy chỉ *gợi ý*. Muốn làm theo thì tự vào app chứng khoán đặt lệnh tay — không có gì tự đặt lệnh thật.

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

## 5. Khi gặp trục trặc

Muốn dữ liệu TCBS real-time cho `watch` / `advise` / `tcbs` — đăng nhập lại: mở `claude`, gõ `/mcp`, chọn tcbs → Authenticate (đăng nhập TCBS + iOTP), rồi chạy lệnh ngay sau đó. Lưu ý: các lệnh này có thể in `nguồn: mcp` nhưng nếu trong kết quả có dòng "Server TCBS chưa kết nối" thì thực chất đang chạy rule-based — nhãn `mcp` chỉ nghĩa là đã thử, không đảm bảo TCBS thật sự trả dữ liệu.

Báo lỗi lấy dữ liệu / bị chặn tần suất — giãn nhịp rồi chạy lại:

.venv/bin/python run.py screen --group VN30 --throttle 3.0

Kiểm tra kết nối tới danh mục thật:

.venv/bin/python run.py portfolio

## Tóm tắt nhịp

- Cuối mỗi phiên: `daily --group VN30 --require-mcp` — 1 báo cáo gộp cảnh báo + quyết định mua/bán/giữ + xếp hạng cả rổ. Lưu `{ngày}-daily.md`, chạy lại ghi đè.
- Mỗi tuần: `paper mark` (định giá lại sổ paper).
- Mỗi tháng: `paper score` (chấm điểm agent vs giữ-nguyên vs VNINDEX).
- Khi bơm/rút vốn thật: `paper cash` cho khớp sổ.
