---
title: Runbook vận hành vn-trading-agents
scope: sử dụng hàng ngày — quét EOD, kế hoạch tháng, paper-trade
updated: 2026-08-31
---

# Runbook vận hành vn-trading-agents

Chạy từ thư mục `~/dev/vn-trading-agents`. Điều kiện: đã cài đặt xong theo README (môi trường, hồ sơ khẩu vị, đăng nhập TCBS).

## 1. Hàng ngày — cuối phiên (sau ~15:00)

Quét danh mục cuối ngày. Máy tự im lặng khi không có gì đáng làm; chỉ lên tiếng khi cần.

.venv/bin/python run.py watch --group VN30

**Về dữ liệu:** lệnh này chỉ đạt chất lượng cao nhất khi TCBS MCP đăng nhập còn hiệu lực. Trong phiên headless (`run.py`), token TCBS thường KHÔNG kết nối → dù header in `nguồn: mcp`, thực chất mô hình chạy **rule-based** (RSI, score, P/E, P/B, ROE có sẵn), không có rating/đồng thuận CTCK/khối ngoại real-time. Dấu hiệu: trong phần đề xuất có dòng "Server TCBS chưa kết nối". Muốn dữ liệu thật → đăng nhập lại TCBS (mục 5) ngay trước khi chạy.

Việc quét trigger (RSI cao / tập trung / thủng SMA50 / tin xấu) và kiểm tiền rảnh **luôn là rule-based**, chạy được không cần TCBS.

Đọc kết quả:
- Báo "không có tín hiệu" → danh mục ổn, không có tiền rảnh đáng kể. Đóng máy, không làm gì.
- Có đề xuất GIỮ / GIẢM / BÁN kèm mã rotate hoặc giải ngân → xem lý do từng mã, rồi tự quyết có đặt lệnh hay không.
- Nếu đề xuất có dòng "Server TCBS chưa kết nối" (hoặc banner "TCBS không dùng được") → đang là rule-based, thiếu real-time; đăng nhập lại (mục 5) rồi chạy lại nếu cần chắc.

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

- Cuối mỗi phiên: `watch` — im lặng thì thôi.
- Mỗi tuần: `recommend` + `paper mark`.
- Mỗi tháng: `advise` (rót tiền) + `paper score`.
- Khi bơm/rút vốn thật: `paper cash` cho khớp sổ.
