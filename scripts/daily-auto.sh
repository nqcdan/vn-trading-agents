#!/usr/bin/env bash
# daily-auto.sh — chạy runbook daily (mục 1 RUNBOOK.md) + giao Telegram. Dùng bởi launchd + skill daily-trading.
# Usage: daily-auto.sh [eod|orders|crypto]   (mặc định eod)
#   eod    — tối: báo cáo daily (giá đóng cửa đã chốt) + snapshot danh mục; thứ 6 thêm hiệu suất mục 3
#   orders — sáng trước 9:00: gửi phiếu lệnh từ báo cáo tối hôm trước (không LLM)
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

if [ "$SLOT" = "orders" ]; then
  [ "$DOW" -ge 6 ] && { echo "[$(ts)] cuối tuần, bỏ qua." >>"$LOG"; exit 0; }
  if MSG="$(.venv/bin/python run.py orders 2>>"$LOG")" && send --text "$MSG"; then
    echo "[$(ts)] OK → sent orders" >>"$LOG"; exit 0
  fi
  echo "[$(ts)] orders lỗi" >>"$LOG"; exit 1
fi

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
  HEADER="📊 Trading tối $TODAY — rổ VN30. Chốt lệnh tối nay; 8:30 sáng mai gửi phiếu lệnh."
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

# EOD: chụp danh mục ngày; thứ 6 gửi thêm hiệu suất lệnh mục 3.
if [ "$SLOT" = "eod" ]; then
  .venv/bin/python run.py snapshot >>"$LOG" 2>&1 || echo "[$(ts)] snapshot lỗi" >>"$LOG"
  if [ "$DOW" -eq 5 ]; then
    if .venv/bin/python run.py scorecard >>"$LOG" 2>&1 \
       && send --pdf "$REPO/reports/scorecard/$TODAY.md" "trading-scorecard-$TODAY" "📈 Hiệu suất lệnh mục 3 — tuần $TODAY."; then
      echo "[$(ts)] OK → sent scorecard" >>"$LOG"
    else
      echo "[$(ts)] scorecard/gửi lỗi" >>"$LOG"
    fi
  fi
fi
