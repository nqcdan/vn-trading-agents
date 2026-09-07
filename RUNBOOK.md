---
title: Runbook vận hành vn-trading-agents
scope: sử dụng hàng ngày — quét EOD, kế hoạch tháng, paper-trade
updated: 2026-09-07
---

# Runbook vận hành vn-trading-agents

Chạy từ thư mục `~/dev/vn-trading-agents`. Điều kiện: đã cài đặt xong theo README (môi trường, hồ sơ khẩu vị, đăng nhập TCBS).

## 1. Hàng ngày — cuối phiên (sau ~15:00)

Chạy 1 lệnh, ra bảng quyết định đầy đủ: mã nào mua / bán / giữ, đợt này nên giải ngân hay hold tiền.

.venv/bin/python run.py advise --group VN30 --require-mcp

Nếu hay bị timeout (sonnet nặng), chạy model nhanh:

VN_LLM_MODEL=haiku .venv/bin/python run.py advise --group VN30 --require-mcp

`--require-mcp` bắt buộc dùng dữ liệu TCBS real-time (rating 7 chiều + khối ngoại ròng + đồng thuận CTCK). Nếu TCBS chưa đăng nhập / quá hạn, lệnh **báo lỗi** thay vì âm thầm chạy rule-based → đăng nhập lại (mục 5) rồi chạy lại. Bỏ `--require-mcp` nếu chấp nhận fallback text-mode (kém chính xác, có banner cảnh báo).

Danh mục + ngân sách (tiền mặt ví bank) lấy realtime từ everyday, không nhập tay.

### Đọc output — 5 khối từ trên xuống

1. **Dòng `===`** — rổ, nguồn dữ liệu (`tcbs-mcp` = TCBS thật; `fallback-…` = rule-based), vĩ mô voz, ngân sách.
2. **Dòng `▶ QUYẾT ĐỊNH ĐỢT NÀY`** — chốt nhanh: giải ngân bao nhiêu (mấy %) hay HOLD TIỀN. Đây là câu trả lời "đợt này nên xuống tiền hay đứng ngoài".
3. **Bảng hành động** — mỗi mã: Hành động (MUA MỚI / GOM THÊM / GIỮ / BÁN) · Lô · Tiền · % ngân sách · lý do. `◆` = mã đang giữ (kèm tỷ trọng).
4. **Bảng chỉ số** — Giá / RSI / P·E / P·B / ROE rule-based từng mã (số nền tảng để tự đối chiếu).
5. **Phân tích chi tiết** — diễn giải sâu từng mã theo TCBS real-time: rating, khối ngoại, đồng thuận CTCK, giá mục tiêu, điểm vào chia lệnh.

### Ví dụ output (rút gọn)

```
=== Kế hoạch VN30 | nguồn: tcbs-mcp | vĩ mô voz: BULLISH (net 4) | ngân sách: 122,7tr ===

▶ QUYẾT ĐỊNH ĐỢT NÀY: GIẢI NGÂN 84,5tr (69%) · giữ lại 38,2tr (31%) — giải ngân phần lớn.

┌──────────┬───────────┬────┬────────┬───────┬──────────────────────────────────┐
│ Mã       │ Hành động │ Lô │   Tiền │  % NS │ Tín hiệu / Lý do                 │
├──────────┼───────────┼────┼────────┼───────┼──────────────────────────────────┤
│ HDB      │ MUA MỚI   │  8 │ 21,8tr │ 17.7% │ NH mid-cap, P/E 7.1, ROE 25.8%   │
│ SSI      │ MUA MỚI   │  2 │  4,2tr │  3.4% │ rsRank 83 momentum, ROE thấp     │
│ FPT ◆68% │ GOM THÊM  │  5 │ 36,4tr │ 29.7% │ khối ngoại MUA +960k, rating 3/5 │
│ MBB ◆11% │ GOM THÊM  │  7 │ 14,4tr │ 11.7% │ P/E 6.9 rẻ nhất NH, cổ tức 4.9%  │
│ VNM ◆10% │ GIỮ       │  — │      — │     — │ RSI 54 · P/E 11.8 · ROE 34%      │
│ HPG ◆4%  │ GIỮ       │  — │      — │     — │ RSI 48 · P/E 7.9 · ROE 18%       │
└──────────┴───────────┴────┴────────┴───────┴──────────────────────────────────┘

Chỉ số chi tiết (rule-based vnstock — TCBS real-time xem phần phân tích dưới):
┌─────┬─────┬─────┬──────┬─────┬─────┬──────┐
│ Mã  │ Giá │ RSI │  P/E │ P/B │ ROE │ Rule │
├─────┼─────┼─────┼──────┼─────┼─────┼──────┤
│ FPT │ 73k │  59 │ 12.5 │ 3.1 │ 27% │ BUY  │
│ …   │     │     │      │     │     │      │
└─────┴─────┴─────┴──────┴─────┴─────┴──────┘

--- Phân tích chi tiết từng mã (LLM/TCBS) ---
### FPT — GOM THÊM … (khối ngoại mua ròng, rating, điểm vào chia lệnh…)
…
[LLM: 1 spawn, 124s]
```

**Việc của bạn:** máy chỉ *gợi ý*. Muốn làm theo thì tự vào app chứng khoán đặt lệnh tay — không có gì tự đặt lệnh thật.

### Quét nhanh im lặng (tuỳ chọn)

Chỉ muốn biết "có gì bất thường không" mà không cần bảng đầy đủ → máy quét EOD im lặng khi danh mục ổn, chỉ lên tiếng khi có trigger (RSI cao / tập trung / thủng SMA50 / tin xấu) hoặc đủ tiền mua 1 lô:

.venv/bin/python run.py watch --group VN30

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

- Cuối mỗi phiên: `advise --group VN30 --require-mcp` — bảng quyết định mua/bán/giữ + giải ngân hay hold. (`watch` = quét nhanh im lặng khi chỉ muốn biết có bất thường không.)
- Mỗi tuần: `recommend` + `paper mark`.
- Mỗi tháng: rà `advise` kỹ + `paper score`.
- Khi bơm/rút vốn thật: `paper cash` cho khớp sổ.
