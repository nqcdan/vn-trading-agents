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
REPORT="$REPO/reports/journal/$TODAY-daily.md"   # tuyệt đối: send() cd sang $EVERYDAY
ts() { date "+%Y-%m-%d %H:%M:%S"; }
# send(): chạy tsx trong $EVERYDAY; trả exit thật (không nuốt) để caller biết gửi có thành công.
send() { (cd "$EVERYDAY" && ./node_modules/.bin/tsx scripts/pdf/send-trading-daily.mts "$@") >>"$REPO/$LOG" 2>&1; }

echo "[$(ts)] === daily-auto slot=$SLOT dow=$DOW ===" >>"$LOG"

if [ "$SLOT" = "crypto" ]; then
  # Crypto 24/7 → không guard cuối tuần, không TCBS.
  REPORT="$REPO/reports/journal/$TODAY-crypto.md"
  HEADER="₿ Crypto $TODAY — BTC/ETH (agent pipeline). Dữ liệu OHLC Binance/CoinGecko."
  .venv/bin/python run.py crypto >>"$LOG" 2>&1
  RC=$?
  BASENAME="crypto-$TODAY"
else
  # Chứng khoán VN: cuối tuần nghỉ → bỏ qua (tiết kiệm LLM).
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
  BASENAME="trading-daily-$TODAY"
fi

if [ $RC -ne 0 ] || [ ! -f "$REPORT" ]; then
  echo "[$(ts)] FAIL rc=$RC" >>"$LOG"
  msg="⚠️ Trading ($SLOT $TODAY) FAIL (rc=$RC)."
  grep -qiE "tcbs|mcp|authenticate" "$LOG" && msg="$msg TCBS có thể hết hạn → claude /mcp tcbs Authenticate rồi chạy lại."
  grep -qi "everyday" "$LOG" && msg="$msg (hoặc everyday API lỗi — kiểm tra cert/service)."
  msg="$msg Log: $REPO/$LOG"
  send --text "$msg"
  exit "${RC:-1}"
fi

if send --pdf "$REPORT" "$BASENAME" "$HEADER"; then
  echo "[$(ts)] OK → sent $REPORT" >>"$LOG"
else
  echo "[$(ts)] báo cáo OK nhưng GỬI TELEGRAM LỖI" >>"$LOG"
  send --text "⚠️ Báo cáo $SLOT $TODAY đã tạo nhưng gửi Telegram lỗi. Xem $REPO/$LOG" || true
  exit 1
fi

# EOD: áp quyết định daily vào sổ paper (không LLM) → đo agent vs giữ nguyên. Thứ 6: gửi scorecard tuần.
if [ "$SLOT" = "eod" ]; then
  .venv/bin/python run.py paper journal >>"$LOG" 2>&1 || echo "[$(ts)] paper journal lỗi" >>"$LOG"
  if [ "$DOW" -eq 5 ]; then
    if .venv/bin/python run.py scorecard >>"$LOG" 2>&1 \
       && send --pdf "$REPO/reports/scorecard/$TODAY.md" "trading-scorecard-$TODAY" "📈 Scorecard tuần $TODAY — tín hiệu vs giá thực tế + sổ paper."; then
      echo "[$(ts)] OK → sent scorecard" >>"$LOG"
    else
      echo "[$(ts)] scorecard/gửi lỗi" >>"$LOG"
    fi
  fi
fi
