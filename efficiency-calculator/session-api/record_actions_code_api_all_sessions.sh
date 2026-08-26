#!/usr/bin/env bash
# 전 세션 효율 리포트 (리눅스/맥) — 엔터 한 번으로 실행.
# 이 PC 홈(~/.claude/projects)의 세션 전체를 LLM 0회로 측정해
# 실행한 위치(현재 폴더)에 session-efficiency-report.md 저장.
set -e
OUT="$PWD/session-efficiency-report.md"
cd "$(dirname "$0")"
PY="$(command -v python3 || command -v python)"
"$PY" record_actions_code_api_all_sessions.py --out "$OUT"
echo "리포트 저장: $OUT"
