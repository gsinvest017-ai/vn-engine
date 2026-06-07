#!/usr/bin/env bash
# E2E 一鍵跑：起 server → 跑全部 tests/e2e/*.cjs → 清理測試產物
# 用法：./tests/e2e/run-all.sh
# 環境：PORT（預設 8123）、NODE_PATH（playwright 所在 node_modules，CI 內 npm i 後免設）
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PORT="${PORT:-8123}"
export BASE_URL="http://localhost:${PORT}"

cd "$ROOT"

python3 serve.py "$PORT" --no-browser >/tmp/vn-e2e-serve.log 2>&1 &
SERVER_PID=$!
cleanup() {
  kill "$SERVER_PID" 2>/dev/null
  rm -rf "$ROOT/scripts/e2e-ci"          # 測試建立的劇本目錄
  find "$ROOT/scripts" -name '*.bak' -delete 2>/dev/null
}
trap cleanup EXIT

# 等 server ready
for _ in $(seq 1 20); do
  curl -s -m 1 "$BASE_URL/api/status" >/dev/null && break
  sleep 0.5
done

FAIL=0
for f in "$ROOT"/tests/e2e/*.cjs; do
  case "$f" in *lib.cjs) continue;; esac
  echo "── $(basename "$f") ──"
  node "$f" || FAIL=1
done

exit $FAIL
