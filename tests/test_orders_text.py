from vn import orders

MD = """## 3. Quyết định & giải ngân

**Lệnh đặt cụ thể** (LO …):

|   # | Lệnh | Mã  | SL (cp) |  Giá LO |       Tiền | Tiền mặt còn | Khi nào |
| --: | :--- | :-- | ------: | ------: | ---------: | -----------: | :------ |
|   1 | BÁN  | VNM |     100 |  57,700 |  5,755,575 |            — | Đặt trước 9:00 |
|   2 | MUA  | HPG |     200 |  20,100 |  4,026,030 |   ⚠ -100,000 | Đặt trước 9:00 |

Tổng mua 4,026,030đ · tiền bán về 5,755,575đ (T+2, không dùng mua ngay)
"""


def test_morning_text_uses_latest_report_before_today(tmp_path):
    (tmp_path / "2026-10-09-daily.md").write_text("cũ")
    (tmp_path / "2026-10-12-daily.md").write_text(MD)
    (tmp_path / "2026-10-13-daily.md").write_text("hôm nay")
    t = orders.morning_text("2026-10-13", root=str(tmp_path))
    assert "báo cáo tối 2026-10-12" in t
    assert "1. BÁN VNM 100 cp @ 57,700" in t and "2. MUA HPG 200 cp @ 20,100" in t
    assert "Tổng mua" in t and "⚠ Thiếu tiền" in t


def test_morning_text_no_orders(tmp_path):
    (tmp_path / "2026-10-12-daily.md").write_text("## 3. Quyết định\nkhông có bảng")
    assert "Không có lệnh" in orders.morning_text("2026-10-13", root=str(tmp_path))
