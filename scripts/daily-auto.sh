#!/usr/bin/env bash
# daily-auto.sh — chạy runbook daily (mục 1 RUNBOOK.md) + giao Telegram. Dùng bởi launchd + skill daily-trading.
# Usage: daily-auto.sh [eod|morning]   (mặc định eod)
# Số liệu danh mục + ngân sách lấy realtime từ everyday API (cần cert everyday còn hạn).
# TCBS real-time qua `claude -p` headless (token OAuth cache); hết hạn → báo lỗi Telegram nhắc re-auth.
set -uo pipefail

SLOT="${1:-eod}"
REPO="/Users/nqcdan/dev/vn-trading-agents"
EVERYDAY="/Users/nqcdan/dev/everyday"
NODE_BIN="/Users/nqcdan/.nvm/versions/node/v24.9.0/bin"
export PATH="$NODE_BIN:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "$REPO" || exit 1
mkdir -p logs
TODAY="$(date +%F)"
DOW="$(date +%u)"          # 1=Mon .. 7=Sun
LOG="logs/daily-auto-$TODAY.log"
REPORT="reports/journal/$TODAY-daily.md"
ts() { date "+%Y-%m-%d %H:%M:%S"; }
send() { (cd "$EVERYDAY" && ./node_modules/.bin/tsx scripts/pdf/send-trading-daily.mts "$@") >>"$REPO/$LOG" 2>&1 || true; }

echo "[$(ts)] === daily-auto slot=$SLOT dow=$DOW ===" >>"$LOG"

# Cuối tuần thị trường nghỉ → bỏ qua (tiết kiệm LLM). Mon-Fri mới chạy.
if [ "$DOW" -ge 6 ]; then
  echo "[$(ts)] cuối tuần, bỏ qua." >>"$LOG"
  exit 0
fi

if [ "$SLOT" = "morning" ]; then
  HEADER="☀️ Trading sáng $TODAY — xem trước khi đặt LO ~9:15. Số liệu = đóng cửa phiên trước + tin qua đêm."
else
  HEADER="📊 Trading EOD $TODAY — rổ VN30. Đọc để chuẩn bị lệnh phiên sau."
fi

VN_MCP_TIMEOUT=600 .venv/bin/python run.py daily --group VN30 --require-mcp >>"$LOG" 2>&1
RC=$?

if [ $RC -ne 0 ] || [ ! -f "$REPORT" ]; then
  echo "[$(ts)] FAIL rc=$RC" >>"$LOG"
  msg="⚠️ Trading daily ($SLOT $TODAY) FAIL (rc=$RC)."
  grep -qiE "tcbs|mcp|authenticate" "$LOG" && msg="$msg TCBS có thể hết hạn → claude /mcp tcbs Authenticate rồi chạy lại."
  grep -qi "everyday" "$LOG" && msg="$msg (hoặc everyday API lỗi — kiểm tra cert/service)."
  msg="$msg Log: $REPO/$LOG"
  send --text "$msg"
  exit "${RC:-1}"
fi

send --pdf "$REPORT" "trading-daily-$TODAY" "$HEADER"
echo "[$(ts)] OK → sent $REPORT" >>"$LOG"
