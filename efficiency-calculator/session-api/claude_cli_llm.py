# -*- coding: utf-8 -*-
"""Claude Code CLI를 LLM 백엔드로 꽂는 어댑터 — 하이쿠 등 모델 지정 가능.

이 폴더의 모든 측정 API는 llm 자리에 `complete_json(prompt, max_tokens) -> dict`
메서드 하나만 있는 객체를 받는다. 이 모듈은 그 계약을 Claude Code CLI
(`claude -p --model <model>`)로 구현한 예시다 — 클로드 코드가 깔린 PC면
프록시·API 키 설정 없이 바로 쓸 수 있다.

사용 (하이쿠로 세션 측정):
    from claude_cli_llm import ClaudeCliLLM
    from session_api import measure_session, JsonRetryLLM

    llm = JsonRetryLLM(ClaudeCliLLM())            # 기본 모델 haiku
    r = measure_session(llm, "session.jsonl")     # req-actions, LLM 1회
    r = measure_session(llm, "session.jsonl", human="record-actions")

    ClaudeCliLLM(model="sonnet")                  # 다른 모델로 교체

비용 주의: 호출마다 실제 과금된다. 저렴한 검증은 haiku(기본) 권장.
"""
import os
import subprocess
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent.parent / "human-effort" / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from onprem_llm_sim import _extract_json  # noqa: E402 (JSON 추출 공용)


class ClaudeCliLLM:
    """`claude -p --model <model>` 서브프로세스 백엔드.

    runner: 테스트용 주입점 — prompt를 받아 응답 텍스트를 돌려주는 함수.
            생략하면 실제 CLI를 부른다.
    """

    def __init__(self, model="haiku", timeout=300, runner=None):
        self.model = model
        self.timeout = timeout
        self._run = runner or self._run_cli

    def _run_cli(self, prompt):
        p = subprocess.run(
            ["claude", "-p", "--model", self.model,
             "--output-format", "text"],
            input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=self.timeout,
            shell=(os.name == "nt"))  # Windows: claude가 .cmd 심이라 셸 필요
        if p.returncode != 0:
            raise RuntimeError(
                f"claude CLI rc={p.returncode}: {(p.stderr or '')[:300]}")
        return p.stdout

    def complete_json(self, prompt, max_tokens):
        # max_tokens는 CLI가 자체 관리하므로 미사용 (계약 시그니처 유지)
        return _extract_json(self._run(prompt))
