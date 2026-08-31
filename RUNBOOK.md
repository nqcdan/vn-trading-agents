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

### Ví dụ output thật (rút gọn)

```
=== Watch EOD | rổ VN30 | nguồn: fallback-mcp-offline (rule-based, TCBS ngắt) ===
• FPT: tỷ trọng 75.3% > 25.0% NAV (tập trung)
• HPG: thủng SMA50 (close 22.1 < sma50 22.16)

TCBS server chưa kết nối được sau 3 lần thử — phân tích dựa trên dữ liệu trong prompt.

### FPT — tỷ trọng 75.3% (ngưỡng cảnh báo >25%)
Vấn đề: gần như toàn bộ dồn vào 1 mã, rủi ro tập trung cao.
Không bán hôm nay; mua HDB bằng tiền rảnh sẽ pha loãng FPT 75.3% → ~42.8%.
Khuyến nghị: GIỮ FPT + pha loãng bằng tiền mới.

### HPG — thủng SMA50 (22.1 < 22.16)
Mức thủng ~0.3% (rất nhẹ), tỷ trọng chỉ 4.2%. Xoay đi tốn ~0.5% phí, không đủ lời.
Kết luận: GIỮ HPG.

## Tiền rảnh 44,577,682 VND → Mua HDB
Score=4 (cao nhất), P/E=9.7 (rẻ), ROE=18%, RSI=61.3 (chưa nóng), ngành ngân hàng.
Giá HDB 27,800đ/cp → 1 lô=2,780,000đ → mua 16 lô (1.600 cp) = 44,480,000đ, dư 97,682đ.

## Tóm tắt hành động
| Mã | Hành động | Lý do |
| FPT | GIỮ | pha loãng tự nhiên khi mua HDB, thiếu biên bán hôm nay |
| HPG | GIỮ | thủng SMA50 chỉ 0.3%, không đủ biên xoay |
| HDB | MUA 16 lô | score cao nhất, P/E rẻ, RSI an toàn |

```json
[{"action":"BUY","symbol":"HDB","lots":16,"price":27800,"reason":"..."}]
```

Ngân sách (ví bank realtime): 44,577,682đ

⚠️  TCBS MCP KHÔNG dùng được — đang chạy TEXT-MODE (kém chính xác...).
[LLM: 1 spawn, 98s]
```

### Cách đọc (dành cho người mới)

Đọc từ trên xuống theo 5 khối:

1. **Dòng `===` đầu tiên** — máy quét cái gì và bằng dữ liệu nào. `nguồn: mcp` = có dữ liệu TCBS thật; `nguồn: fallback-mcp-offline (rule-based…)` = TCBS không kết nối, chỉ dùng số liệu tự tính (kém chắc hơn).

2. **Các dòng `•`** — "vì sao máy lên tiếng". Đây là các *cảnh báo tự động* (trigger). Không có dòng `•` nào thì máy im lặng. Ví dụ trên: FPT chiếm quá nhiều danh mục, và giá HPG vừa tụt dưới đường trung bình 50 ngày.

3. **Phân tích từng mã** — với mỗi cảnh báo, máy giải thích và chốt GIỮ / GIẢM / BÁN. Ở đây cả hai đều **GIỮ** vì bán ra lúc này tốn phí mà lợi ích không rõ.

4. **Phần "Tiền rảnh → Mua …"** — bạn đang có tiền trong ví, máy gợi ý mua mã nào, **bao nhiêu lô**, hết bao nhiêu tiền, còn dư bao nhiêu. Đây là phần hành động cụ thể nhất.

5. **Bảng "Tóm tắt hành động" + khối `json`** — tóm gọn mọi việc. Khối `json` là để máy tự ghi vào *sổ tập dượt* (mục 4), bạn có thể bỏ qua khi đọc.

**Việc của bạn:** máy chỉ *gợi ý*. Muốn làm theo thì bạn tự vào app chứng khoán của mình đặt lệnh tay. Không có gì tự động đặt lệnh thật.

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

- Cuối mỗi phiên: `watch` — im lặng thì thôi.
- Mỗi tuần: `recommend` + `paper mark`.
- Mỗi tháng: `advise` (rót tiền) + `paper score`.
- Khi bơm/rút vốn thật: `paper cash` cho khớp sổ.
