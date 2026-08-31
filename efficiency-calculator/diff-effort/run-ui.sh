#!/usr/bin/env bash
# diff-effort UI 실행 (Linux/macOS/Git Bash). 사용법은 run-ui.bat 과 같다:
#   ./run-ui.sh            로컬판
#   ./run-ui.sh server     서버판 (ratios.json 고정)
#   ./run-ui.sh 9000       포트
#   ./run-ui.sh open       로컬판을 0.0.0.0 으로 연다 (다른 PC 접속 가능 — 이 PC 디스크 노출 주의)
set -e
cd "$(dirname "$0")"
MODE=local; PORT=8765; OPEN=""
for a in "$@"; do
  [ "$a" = server ] && MODE=server
  [ "$a" = open ] && OPEN=--open
  [[ "$a" =~ ^[0-9]+$ ]] && PORT=$a
done
PY=""
for c in python3 python py; do
  if "$c" -c 'import sys;assert sys.version_info>=(3,7)' >/dev/null 2>&1; then PY=$c; break; fi
done
if [ -z "$PY" ]; then
  echo "[오류] Python 3.7 이상을 찾지 못했다. https://www.python.org/downloads/" >&2; exit 1
fi
while (echo >"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; do
  echo "[알림] 포트 $PORT 사용 중 → $((PORT+1))"; PORT=$((PORT+1))
done
echo "diff-effort UI [$MODE]  브라우저가 안 열리면: http://127.0.0.1:$PORT/   (종료 Ctrl+C)"
if [ "$MODE" = server ]; then
  [ -f ratios.json ] || { echo "[오류] 서버판은 ratios.json 이 필요하다. 로컬판 1 칸에서 먼저 재라." >&2; exit 2; }
  exec "$PY" ui_server.py --server --config ratios.json --port "$PORT"
else
  exec "$PY" ui_server.py --port "$PORT" $OPEN
fi
