"""Phân tích qua TCBS MCP — LLM tự gọi tool TCBS real-time (chính xác hơn vnstock).

Điều kiện: đã `claude mcp add --transport http tcbs https://mcp.tcbs.com.vn/mcp/tcinvest/
--scope user` và auth OAuth 1 lần (claude → /mcp → tcbs → Authenticate). Sau đó headless
`claude -p` tái dùng token.

Khác _llm_via_cli (tắt hết tool): path này BẬT mcp__tcbs__* để LLM lấy dữ liệu, vẫn cấm
Bash/Read/Write. Tín hiệu giàu TCBS không tự tính được: getGeneralRating (điểm 7 chiều),
getHistoryRecommendation (đồng thuận CTCK + giá mục tiêu), getVolumeAndForeign (khối ngoại).
"""
from __future__ import annotations
import os
import subprocess

from .agents import _DEFAULT_SYS, _NO_TOOLS
from .profile import profile_system


class TcbsError(RuntimeError):
    pass


_TCBS_SYS = (
    "Bạn là chuyên gia phân tích chứng khoán VN. Dùng các tool mcp__tcbs__* để LẤY DỮ LIỆU "
    "TCBS real-time. KHÔNG dùng Bash/Read/Write/WebSearch. Không nhắc code/thư mục/môi trường. "
    "Trả lời tiếng Việt."
)


def _llm_mcp(prompt: str, system: str = "", timeout: int = 240) -> str:
    """Gọi claude CLI với tool TCBS bật (không --strict-mcp-config để nạp user-scope tcbs)."""
    model = os.environ.get("VN_LLM_MODEL", "sonnet")
    cmd = ["claude", "-p", prompt, "--model", model,
           "--append-system-prompt", system or _TCBS_SYS,
           "--allowedTools", "mcp__tcbs__*",
           "--disallowedTools", *_NO_TOOLS]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd="/tmp")
    except subprocess.TimeoutExpired as e:
        raise TcbsError(f"timeout {timeout}s") from e
    if r.returncode != 0:
        raise TcbsError((r.stderr or "claude cli failed")[:200])
    out = r.stdout.strip()
    if not out or "Needs authentication" in out or "không tìm thấy tool" in out.lower():
        raise TcbsError("MCP TCBS chưa auth / không có tool — chạy: claude → /mcp → tcbs → Authenticate")
    return out


def analyze_tcbs(symbol: str) -> dict:
    """Phân tích 1 mã qua TCBS MCP, hợp khẩu vị PROFILE.md."""
    sym = symbol.upper()
    prompt = (
        f"Phân tích cổ phiếu {sym} để ra quyết định đầu tư, dùng dữ liệu TCBS real-time.\n"
        "Gọi các tool sau và tổng hợp:\n"
        f"- getTickerOverview({sym}): sàn, ngành, sở hữu nước ngoài, stockRating, biến động tuần/tháng/năm.\n"
        f"- getStockRatio({sym}): P/E, P/B, ROE, ROA, EPS, marketCap real-time.\n"
        f"- getGeneralRating({sym}): điểm tổng hợp 7 chiều (business, hiệu quả, sức khỏe TC, định giá...).\n"
        f"- getHistoryRecommendation({sym}): đồng thuận khuyến nghị CTCK gần đây + giá mục tiêu.\n"
        f"- getVolumeAndForeign({sym}): mua/bán ròng khối ngoại + điểm RS.\n"
        f"- getTechnicalIndicator({sym}): RSI, MACD, tín hiệu.\n"
        "Nếu là ngân hàng, dùng thêm getFinancialRatioForBank; phi ngân hàng thì ForNonBank.\n\n"
        "Sau đó ra quyết định cuối HỢP KHẨU VỊ HỒ SƠ NĐT. Trình bày:\n"
        "1) Bảng số liệu chính vừa lấy (ghi rõ nguồn TCBS real-time).\n"
        "2) Đọc rating TCBS + đồng thuận CTCK (giá mục tiêu vs giá hiện tại) + khối ngoại.\n"
        "3) QUYẾT ĐỊNH: BUY/HOLD/SELL + độ tin 0-1 + tỷ trọng gợi ý (theo khẩu vị hồ sơ).\n"
        "4) Rủi ro chính + điểm vào (chia lệnh, tránh mua đuổi).\n"
        "Ngắn gọn, có số. Nhắc: tham khảo, không phải khuyến nghị đầu tư."
    )
    text = _llm_mcp(prompt, system=profile_system(_TCBS_SYS))
    return {"symbol": sym, "source": "tcbs-mcp", "analysis": text}
