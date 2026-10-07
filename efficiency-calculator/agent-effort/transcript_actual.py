# -*- coding: utf-8 -*-
"""분자 모듈: Claude Code 트랜스크립트 → 실제 수행된 기계·HITL 동작 × 요율 (분).

측정 기조: 분모 = "AI를 쓰는 사람의 에포트(분)" + "AI가 실제 소모한 시간".
- hitl(사람 몫)은 wall-clock이 아니라 **단서 × 요율**로 추정한다 — 사람 노동은
  트랜스크립트에 단서(지시 건수·AI 출력 분량)로만 남고, 산출물 검토·후작업은
  세션 종료 후 몰아서 할 수 있어 세션 시간 측정으로는 잡히지 않는다.
- AI 몫은 **타임스탬프 실측** (§62·§65·§87): 턴을 연 입력 → 그 턴의 AI 기록들
  사이 간격을 합산한다. 기준 = 전체 러닝타임 − 방치 − 사람이 쓴 시간.
  §87부터 방치는 재기록 중복 레코드 무시(R0)와 AI를 깨운 입력(isMeta·압축
  요약)을 경계로 쓰는 것(R1)으로 빼고, 10분 상한(§65)은 방치·승인 대기가
  섞일 수 있는 간격(실행 시간이 막힌 도구·즉시 끝나는 도구·사람을 기다리는
  도구·오류 결과·완료 아닌 배경 알림)에만 남긴다. 답 생성·정상 완료 배경
  대기·감시(Monitor) 이벤트 대기(§88)·제한 없는 도구의 정상 결과는 끝까지
  센다 (DESIGN-ai-time-87.md). 단 이미 종료 알림을 받은 작업의 종료 알림이
  다시 오면(세션 재개 때 재전달) 그 앞 공백은 대기가 아니다(§93).
  §94: 이 "끝까지"는 10분까지는 그대로, 10분을 넘는 부분은 실제로 돌았다는
  별도 기록(WaitEvidence 증거)과 겹치는 만큼만 센다 (DESIGN-wait-evidence-94.md).
  AI가 끝낸 뒤 다음 입력까지는 사람 시간이라 제외. 병렬 실행(서브에이전트)은
  메인 타임라인에 이미 흐른 시간이므로 별도 가산하지 않는다.

LLM을 쓰지 않는다 — 트랜스크립트에 기록된 동작을 결정론적으로 세고
rates.json의 agent/hitl 카드 요율을 곱한다.

동작 → 요율 매핑 (rates.json):
  기계(machine): **실측**(ai_wall_min). 아래 요율 계산은 타임스탬프가 없는
  구 기록의 폴백이자 대조용(breakdown.machine_rate_estimate):
    execute  = tool_use 블록 수            × agent.execute (tool_call_count)
    read     = tool_result 내용 단어수      × agent.read    (word_count)
    draft    = (assistant 텍스트 + 파일 본문·서브에이전트 지시문 등
               도구 입력으로 생산된 글) 단어수 × agent.draft (word_count, §52)
  사람(hitl) — 동작 카운트는 실측이나 요율은 추정이므로 hitl_min은
  "실제 비용"이 아니라 **추정 감독 비용**이다 (instruct만 실측 보정, §49):
    instruct = 사용자 텍스트 메시지 수       × hitl.instruct (instruction_count)
    review   = assistant 텍스트 단어수      × hitl.review   (word_count)
               (사람이 읽어야 하는 AI 출력. §50 턴 확인 모델: 확인
               시점마다 결론 정독 + 진행 보고 훑기 + 코드 동작 확인
               (+ 변경 규모 비례 확인, §61)
               1회 — 전량 정독 아님. 파일당 과금 폐지 §49→§50)
    correct  = 사용자 중단(interrupt) 횟수  × hitl.correct  (correction_count)
               (정의: 끊고 다시 방향 잡는 **재정향 추가 비용** — 새 지시
               작성 노동은 instruct가 별도 계상. 발화형 교정("아니 그게
               아니라…")은 결정론으로 못 갈라 미계상 — 알려진 과소.
               interrupt 직후 첫 지시는 corrective_instructions로 표시만)

hitl 축약 모드 (§79, actual_effort_minutes(hitl_compact=True), §85부터 기본 ON —
    hitl_compact=False 가 §76 전체 모델):
    review의 파일 몫을 통째로 바꾼다 — 확인 시점(실질 지시 턴·세션 끝)에
    그 구간에 파일 생성·수정이 있으면 유형 무관 1건
    min(cap, a·ln(1 + 구간 쓴 단어/b)) (hitl_compact_model.file_check, 기본
    cap 2.0분). 확인 시점의 마지막 테스트가 통과면 그 테스트 이전에 쓴 코드
    파일은 구간 단어에서 제외(테스트가 대신 봤다, automation_saved_min).
    correct는 계상하지 않는다(interrupt 뒤 재지시는 instruct가 세고 instruct
    요율이 "직전 응답→지시 간격" 실측이라 이중 계상). 근거: 사람은 수단(생성
    스크립트)이 아니라 결과물을 보고, 실측(§63)은 확인 비용이 규모와 거의
    무관했다. 기본 모드의 코드 동작 확인·규모 비례 대조·문서 훑기·표본
    확인·비례 강등은 축약 모드에서 쓰지 않는다.

집계 제외: thinking 블록(사용자 비노출), meta·snapshot 라인, tool_result만 있는
user 턴(사람 발화 아님). sidechain(서브에이전트)은 기계 동작으로 포함.
"""
import json
import math
from datetime import datetime
import re
from pathlib import Path

# user 레코드 안 시스템 주입 텍스트 접두 — 사람 지시 집계에서 제외
_SYSTEM_TEXT_PREFIXES = (
    "<system-reminder", "<task-notification", "<command-name",
    "<command-message", "<local-command", "<system-warning",
    "<user-prompt-submit-hook")

# 산출물 유형 — 검토 방식이 다르다: 코드는 동작 확인, 문서는 내용 정독
_CODE_EXT = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
             ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".ps1", ".bat", ".sql"}
_DOC_EXT = {".md", ".txt", ".rst", ".html", ".htm", ".tex",
            ".docx", ".pptx", ".xlsx", ".csv"}


# 자동 테스트 실행 명령 — 검증 위임의 결정론 신호
_TEST_CMD_RE = re.compile(
    r"pytest|py\.test|unittest|npm +test|yarn +test|pnpm +test|jest|vitest"
    r"|go +test|cargo +test|mvn +test|gradle +test|make +test|tox\b",
    re.IGNORECASE)
_PASSED_RE = re.compile(r"(\d+)\s+passed|Ran\s+(\d+)\s+tests?")
_FAILED_RE = re.compile(r"\d+\s+failed|FAILED|ERRORS?\b")
_COVERAGE_RE = re.compile(r"TOTAL\s+.*?(\d+)%")

# 결론 승격 문턱 (§49): 이 미만 단어수의 짧은 이어가기 지시("계속해" 등)는
# 직전 답변을 결론(정독)으로 승격하지 않는다 — 중간 보고가 정독 요율로
# 과금되는 오차 방지. 세션 마지막 답변은 문턱과 무관하게 결론(최종 flush).
# seed 문턱 — 짧은 승인("좋아 커밋해")도 걸러지는 과소 방향 트레이드오프.
_CONCL_PROMOTE_MIN_WORDS = 5


def _artifact_class(fp):
    ext = Path(str(fp)).suffix.lower()
    if ext in _CODE_EXT:
        return "code"
    if ext in _DOC_EXT:
        return "doc"
    return "other"  # 설정·데이터 등 — 표본 확인

try:
    from .agent_effort import DEFAULT_RATES_PATH, load_rates
except ImportError:
    from agent_effort import DEFAULT_RATES_PATH, load_rates


def _words(text):
    return len(text.split()) if isinstance(text, str) else 0


def json_text_words(v):
    """구조화 값 안의 텍스트 단어수 (재귀, 숫자=1단어). §34 공용 헬퍼 —
    분자 쪽(requirement_actions)도 이 함수를 가져다 쓴다."""
    if isinstance(v, str):
        return len(v.split())
    if isinstance(v, dict):
        return sum(json_text_words(x) for x in v.values())
    if isinstance(v, list):
        return sum(json_text_words(x) for x in v)
    return 1 if isinstance(v, (int, float)) else 0


def _content_blocks(message):
    content = (message or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


_WAIT_THRESHOLD_SEC = 30.0   # 이 시간을 넘는 도구만 실측 초과분 가산 (§59)

# AI 시간 실측의 **간격 상한** (§65). 턴 안에서 기록 사이가 이보다 벌어지면
# 그 초과분은 AI가 일한 시간이 아니라 방치로 본다.
#
# 왜 필요한가 — §62는 상한 없이 "턴 시작 → 그 턴 마지막 AI 기록"을 통째로
# 셌다. 이 PC 기록에서는 방치가 전부 턴 끝 도장(system 레코드) 뒤에 있어
# 문제가 없었지만, **그 도장 없이 며칠 벌어진 턴**이 실제로 보고됐다:
# 9.1일 열려 있던 세션에서 ai_wall_min이 12,013분(8.3일)으로 잡혔다.
# 세션이 며칠 방치되다 나중에 tool_result가 도착한 경우다.
#
# 값 10분의 근거 — 이 PC 실측에서 **도구 실행 간격의 최대가 10.0분**
# (Bash 타임아웃)이다. 즉 10분이면 실제로 관측된 가장 긴 도구 실행을 그대로
# 담는다. 그 외 간격은 최대 78.8시간이고 상한으로 30,893분이 잘려나가는데
# 전부 방치다.
#
# §87(DESIGN-ai-time-87.md): 상한은 "방치가 섞일 수 있는 간격"에만 남긴다.
# 답 생성 간격·정상 완료 배경 대기·제한 없는 도구의 정상 결과는 상한 없음.
# 방치는 상한 대신 R0(중복·역행 레코드 무시)·R1(AI를 깨운 입력을 경계로)로
# 뺀다. 이 PC 실측: 상한이 가려 온 긴 간격 7건(84~336분)은 전부 파일 끝에
# 같은 uuid·옛 시각으로 다시 붙은 재기록 레코드가 만든 가짜 간격이었다.
_AI_GAP_CAP_SEC = 600.0

# §87 R3: 10분 넘게 걸렸다면 방치·승인 대기뿐인 도구 — 상한 유지.
# Claude Code가 실행 시간을 막는 도구 + 즉시 끝나는 파일·관리 도구.
_BOUNDED_TOOLS = frozenset((
    "Bash", "PowerShell", "TaskOutput", "BashOutput", "KillShell",
    "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Grep", "Glob",
    "LS", "TodoWrite", "ToolSearch", "TaskCreate", "TaskUpdate", "TaskGet",
    "TaskList", "TaskStop"))
# 사람의 답을 기다리는 도구 — 그 대기는 사람 시간(승인 대기와 같은 취급,
# 상한 10분까지 포함).
_HUMAN_WAIT_TOOLS = frozenset(("AskUserQuestion", "ExitPlanMode"))


class BackgroundExecTracker:
    """배경 실행(§89) 판정기 — 분모(parse_actions)·분자(collect_record_stats)
    공용. 판정을 한 곳에 둬서 배경 실행이 한쪽에만 들어가는 일을 막는다.

    대상: run_in_background로 띄운 Bash·PowerShell, 감시(Monitor). 서브에이전트·
    Workflow는 대상 아님 — 분자는 그 일을 사람이 차례로 하는 일로 세고, 분모는
    병렬이라 메인 대기에 묻힌다.
    시작 = 띄운 tool_use 시각. 끝 = 가장 이른 완료 신호:
      ① <task-notification>(user 기록 또는 queue-operation 기록) — <tool-use-id>
         또는 <task-id>로 짝짓기
      ② TaskOutput·BashOutput 결과의 <task_id>·<status> (running 아닌 것)
    Monitor의 <event> 알림(§88)은 구간을 끊되 계속 도는 것으로 본다.
    attachment 안의 알림은 화면 기록 사본이라 보지 않는다.
    full = 정상 완료(<status>completed</status>)·감시 이벤트 — 그 외 종료는 10분 상한.
    """
    _POLL = ("TaskOutput", "BashOutput")

    def __init__(self):
        self.launch = {}     # 띄운 tool_use id -> 시작 시각 (확인 전)
        self.running = {}    # tool_use id -> 현재 구간 시작 시각
        self.task = {}       # task id -> tool_use id
        self.polls = set()   # 폴링 tool_use id
        self.jobs = []       # [{start, end, full}]

    def _finish(self, use_id, t, status=None, event=False):
        start = self.running.get(use_id)
        if start is None or t is None:
            return
        self.jobs.append({"start": start, "end": t,
                          "full": event or status == "completed"})
        if event:
            self.running[use_id] = t
        else:
            del self.running[use_id]

    def _notice(self, text, t):
        m = re.search(r"<tool-use-id>([^<]+)</tool-use-id>", text)
        use_id = m.group(1).strip() if m else None
        if use_id not in self.running:
            m = re.search(r"<task-id>([^<]+)</task-id>", text)
            use_id = self.task.get(m.group(1).strip()) if m else None
        st = re.search(r"<status>([^<]+)</status>", text)
        if st:
            self._finish(use_id, t, st.group(1).strip())
        elif "<event>" in text:
            self._finish(use_id, t, event=True)

    def feed(self, rec, t):
        rtype = rec.get("type")
        if rtype == "queue-operation":
            c = rec.get("content")
            if isinstance(c, str) and "<task-notification" in c:
                self._notice(c, t)
            return
        if rtype not in ("user", "assistant"):
            return
        for b in _content_blocks(rec.get("message")):
            if not isinstance(b, dict):
                continue
            if rtype == "assistant" and b.get("type") == "tool_use":
                inp = b.get("input") or {}
                name = b.get("name")
                if b.get("id") and t and (
                        name == "Monitor" or (name in ("Bash", "PowerShell")
                                              and isinstance(inp, dict)
                                              and inp.get("run_in_background"))):
                    self.launch[b["id"]] = t
                elif name in self._POLL and b.get("id"):
                    self.polls.add(b["id"])
            elif b.get("type") == "tool_result":
                uid = b.get("tool_use_id")
                text = _result_text(b)
                if uid in self.launch:
                    start = self.launch.pop(uid)
                    tr = rec.get("toolUseResult")
                    tr = tr if isinstance(tr, dict) else {}
                    tid = tr.get("backgroundTaskId") or tr.get("taskId")
                    if not tid:
                        m = re.search(r"(?:running in background with ID:|Monitor started \(task)"
                                      r"\s*([\w-]+)", text, re.I)
                        tid = m.group(1) if m else None
                    if tid and not b.get("is_error"):   # 배경으로 떴을 때만 대상
                        self.task[tid] = uid
                        self.running[uid] = start
                elif uid in self.polls:
                    self.polls.discard(uid)
                    m = re.search(r"<task_id>([^<]+)</task_id>", text)
                    st = re.search(r"<status>([^<]+)</status>", text)
                    if m and st and st.group(1).strip() not in ("running", "pending"):
                        self._finish(self.task.get(m.group(1).strip()), t, st.group(1).strip())
            elif rtype == "user" and b.get("type") == "text":
                text = b.get("text", "")
                if text.lstrip().startswith("<task-notification"):
                    self._notice(text, t)

    def result(self):
        return [j for j in self.jobs if j["start"] < j["end"]]


class WaitEvidence:
    """배경 작업 장부 겸 긴 대기 증거 판정기(§94) — 분모(parse_actions)·분자
    (collect_record_stats) 공용. 배경 작업(서브에이전트·워크플로)의 시작·재개·
    종료·재도착, 메인 도구 호출의 대기 상태를 여기 한 곳에서만 추적한다.

    규칙 하나: 모든 간격은 10분까지 센다. 10분을 넘는 부분은 "AI가 시킨 일이
    실제로 돌고 있었다"는 별도 기록(증거)과 겹친 만큼만 센다 — 모르는 경우가
    생겨도 간격 하나에서 새는 시간은 최대 10분이다.

    증거(메인 기록만). 증거 시각은 그 일이 끝난 순간에 붙인다 — 배달·재도착
    시각에 붙이면 쉬던 시간대를 덮는다.
      E1 system/turn_duration                     [t − durationMs, t]
      E2 그 실행의 첫 정상 완료 신호의 <duration_ms> [t − duration, t]
      E3 Agent 결과 toolUseResult.totalDurationMs  [t − duration, t]
      E4 BackgroundExecTracker 정상 완료·감시 이벤트 구간 — finish()에 넘긴다
      E5 배경 서브에이전트 [띄운·재개 시각, 첫 정상 완료 신호] — E2가 없을 때만
    간격 종류별로 쓰는 증거(covered_for): 답 생성(R2)은 E1~E5, 도구 대기(R3)는
    E2~E5 + 승인 창이 안 뜨는 권한 모드가 확인될 때만 E1(턴 시간은 승인 창에서
    사람을 기다린 시간도 담는다), 배경 대기(R4)는 E2~E5.
    턴 시간 기록은 턴이 끝난 뒤에 나오므로 파일을 다 읽은 뒤 finish()로 판정한다.
    """
    _NO_PROMPT_MODES = frozenset(("bypassPermissions", "dontAsk"))

    def __init__(self):
        self.turn_wins = []     # E1
        self.work_wins = []     # E2·E3·E5 (+E4는 finish)
        self.modes = []         # (시각, 권한 모드)
        self.agent_start = {}   # agentId → 이번 실행 시작 시각 (E5)
        self.agent_alias = {}   # Agent 입력 name → agentId (SendMessage가 이름으로 부를 때)
        self._name_use = {}     # Agent tool_use id → name
        self._ended = set()     # 이번 실행의 종료 신호를 이미 본 task-id (증거 시각 고정)
        self._delivered = {}    # task-id → 이번 실행에서 AI에게 배달된 첫 종료 알림 본문
        self._open = set()      # 결과를 기다리는 메인 도구 호출
        self._ai_final = False  # 직전 메인 기록이 도구 호출 없는 AI 답인가
        self._work = []
        self._all = []

    def feed(self, rec, t):
        """기록 하나를 반영한다. 반환: 이 기록이 이미 끝난 실행의 종료 알림
        재도착(같은 task-id·같은 본문, 그 사이 재개 없음)으로 확인되면 True."""
        if rec.get("isSidechain"):
            return False
        pm = rec.get("permissionMode")
        if isinstance(pm, str) and t:
            self.modes.append((t, pm))
        rtype = rec.get("type")
        if rtype == "system":
            d = rec.get("durationMs")
            if (t and rec.get("subtype") == "turn_duration"
                    and isinstance(d, (int, float)) and d > 0):
                self.turn_wins.append((t - d / 1000.0, t))       # E1
            return False
        if rtype == "queue-operation":
            c = rec.get("content")
            if isinstance(c, str) and "<task-notification" in c:
                self._notice(c, t)
            return False
        if rtype not in ("user", "assistant"):
            return False
        # 메인 흐름 기록 = parse_actions가 지시·AI 답·도구 결과로 보는 기록
        main = not (rec.get("isMeta") or rec.get("isCompactSummary")
                    or rec.get("isVisibleInTranscriptOnly"))
        blocks = [b for b in _content_blocks(rec.get("message"))
                  if isinstance(b, dict)]
        if rtype == "assistant":
            if main:
                self._ai_final = True
            for b in blocks:
                if b.get("type") != "tool_use":
                    continue
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                if main:
                    self._ai_final = False
                    if b.get("id"):
                        self._open.add(b["id"])
                if (b.get("name") in ("Agent", "Task") and b.get("id")
                        and isinstance(inp.get("name"), str)):
                    self._name_use[b["id"]] = inp["name"]
                for k in ("to", "resume"):                       # 재개
                    v = inp.get(k)
                    if isinstance(v, str):
                        aid = self.agent_alias.get(v, v)
                        if t:
                            self.agent_start[aid] = t
                        self._ended.discard(aid)
                        self._delivered.pop(aid, None)
            return False
        has_result = any(b.get("type") == "tool_result" for b in blocks)
        for b in blocks:
            if b.get("type") == "tool_result":
                if main:
                    self._open.discard(b.get("tool_use_id"))
                tr = rec.get("toolUseResult")
                tr = tr if isinstance(tr, dict) else {}
                nm = self._name_use.pop(b.get("tool_use_id"), None)
                aid = tr.get("agentId")
                if aid and nm:
                    self.agent_alias[nm] = aid
                if aid and tr.get("isAsync") and t:              # 배경 띄움 (E5)
                    self.agent_start[aid] = t
                d = tr.get("totalDurationMs")
                if (t and isinstance(d, (int, float)) and d > 0
                        and not b.get("is_error")):
                    self.work_wins.append((t - d / 1000.0, t))   # E3
            elif b.get("type") == "text":
                text = b.get("text", "")
                if text.lstrip().startswith("<task-notification"):
                    self._notice(text, t)
        if not main:
            return False
        self._ai_final = False
        texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        if any(x.strip() and not x.lstrip().startswith(_SYSTEM_TEXT_PREFIXES)
               for x in texts):
            self._open.clear()          # 새 사람 발화 = 앞 호출은 끝난 것
        joined = " ".join(texts)
        if has_result or not joined.lstrip().startswith("<task-notification"):
            return False
        m = re.search(r"<task-id>([^<]+)</task-id>", joined)
        st = re.search(r"<status>([^<]+)</status>", joined)
        if not m or not st or st.group(1).strip() in ("running", "pending"):
            return False
        tid, body = m.group(1).strip(), " ".join(joined.split())
        if self._delivered.get(tid) == body:
            return True
        self._delivered.setdefault(tid, body)
        return False

    def _notice(self, text, t):
        st = re.search(r"<status>([^<]+)</status>", text)
        if not t or not st or st.group(1).strip() in ("running", "pending"):
            return
        m = re.search(r"<task-id>([^<]+)</task-id>", text)
        tid = m.group(1).strip() if m else None
        start = self.agent_start.pop(tid, None) if tid else None
        if tid:
            if tid in self._ended:       # 그 실행의 두 번째 이후 신호 — 증거 아님
                return
            self._ended.add(tid)
        if st.group(1).strip() != "completed":   # 정상 완료만 증거
            return
        d = re.search(r"<duration_ms>(\d+)</duration_ms>", text)
        if d:
            self.work_wins.append((t - int(d.group(1)) / 1000.0, t))  # E2
        elif start is not None and start < t:
            self.work_wins.append((start, t))                      # E5

    def idle(self):
        """AI가 답을 끝냈고 결과 기다리는 도구·돌고 있는 배경 서브에이전트가
        없는가 (§94 R1 "쉬던 중" 확인 — 배경 실행 판정기 쪽은 호출자가 본다)."""
        return self._ai_final and not self._open and not self.agent_start

    @staticmethod
    def _merge(wins):
        merged = []
        for s, e in sorted(wins):
            if merged and s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        return merged

    def finish(self, bg_jobs=()):
        """E4(배경 실행 판정기의 정상 완료·감시 이벤트 구간)를 더하고 합집합."""
        work = self.work_wins + [(j["start"], j["end"]) for j in bg_jobs
                                 if j.get("full")]
        self._work = self._merge(work)
        self._all = self._merge(work + self.turn_wins)
        return self

    def no_prompt(self, a, b):
        """[a, b] 내내 승인 창이 안 뜨는 권한 모드였다고 기록으로 확인되는가."""
        before = [m for t, m in self.modes if t <= a]
        if not before or before[-1] not in self._NO_PROMPT_MODES:
            return False
        return all(m in self._NO_PROMPT_MODES for t, m in self.modes if a < t <= b)

    def covered_for(self, kind, a, b):
        """[a, b] 중 그 간격 종류(R2·R3·R4)에 맞는 증거와 겹친 초."""
        turn = kind == "R2" or (kind == "R3" and self.no_prompt(a, b))
        return sum(max(0.0, min(b, e) - max(a, s))
                   for s, e in (self._all if turn else self._work)
                   if s < b and e > a)

    def credit_for(self, kind, a, b, cap=_AI_GAP_CAP_SEC):
        """센 시간(초) = max(min(간격, cap), 증거와 겹친 길이)."""
        return max(min(max(0.0, b - a), cap), self.covered_for(kind, a, b))


def _resume_artifact(rec):
    """세션을 이어 붙일 때 Claude Code가 만드는 가짜 답("No response requested.")인가.
    §87 R2는 <synthetic> 답 앞 공백을 뺐다. §94: 빼는 건 이 문구로 확인된 것만 —
    API 오류 답(isApiErrorMessage: 529 과부하·응답 도중 끊김 등)도 <synthetic>이지만
    그 호출을 기다리고 일부 생성한 시간이 있다(§87 R2 취지: 과부하 재시도 대기도
    AI 시간). 이 PC: <synthetic> 54건 중 이 문구 10건, 나머지 44건은 API 오류."""
    msg = rec.get("message") or {}
    return msg.get("model") == "<synthetic>" and " ".join(
        b.get("text", "") for b in _content_blocks(msg)
        if isinstance(b, dict) and b.get("type") == "text"
    ).strip() == "No response requested."


def _epoch(x):
    """ISO 타임스탬프 -> epoch 초 (없거나 깨지면 None)."""
    if not x:
        return None
    try:
        return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _result_text(block):
    """tool_result 내용 텍스트 — 문자열 또는 blocks 리스트."""
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content
                        if isinstance(c, dict) and c.get("type") == "text")
    return ""


def _result_words(block):
    """tool_result 내용 단어수."""
    return _words(_result_text(block))


def parse_actions(jsonl_path, count_window=None):
    """트랜스크립트 1개 → 동작 카운트. 반환 dict:
    tool_calls, tool_result_words, assistant_words, user_instructions,
    user_words, interrupts, session_id, first_ts, last_ts

    count_window=(start, end) (epoch 초, 닫힌 구간) — §80 구간 계상. 판정
    (결론 승격·테스트 상태·확인 시점·파일 첫 쓰기)은 기록 전체로, 계상은
    사건 시각이 구간 안인 것만: 지시·중단·도구 호출·결과 단어·AI 시간 조각·
    결론(답변 시각)·확인 사건(확인 시점 시각)·산출물 단어(쓰기 시각).
    시각 없는 레코드는 직전 시각을 물려받는다. None이면 종전과 동일.
    """
    win = tuple(count_window) if count_window else None

    def _inw(t):
        return win is None or (win[0] <= (t or 0.0) <= win[1])
    counts = {"tool_calls": 0, "tool_result_words": 0, "assistant_words": 0,
              "user_instructions": 0, "user_words": 0, "interrupts": 0,
              "instruction_word_list": [],
              # interrupt 직후 첫 지시 = 교정성 지시 (§49, 표시만 — 과금 없음)
              "corrective_instructions": 0,
              # 유형별 검토용: 산출물 파일 {유형: {경로: 단어수}}, 결론 단어수
              "artifact_files": {"code": {}, "doc": {}, "other": {}},
              # 기계 draft 보충 (§52): 파일 본문·서브에이전트 지시문 등
              # 도구 입력으로 생산된 글 — AI 생산 비용에만 가산 (사람 검토는
              # 산출물 채널로 별도 계상되므로 assistant_words에는 안 섞음)
              "tool_input_draft_words": 0,
              "conclusion_words": 0,
              # 결론별 단어수 목록 (§51): 정독 상한을 결론 건별로 적용
              "conclusion_word_list": [],
              # 검증 위임 신호: 마지막 테스트 실행의 통과 수·실패 여부·커버리지
              # + 사건 순서 (§49): 코드 파일별 마지막 쓰기 순번·마지막 테스트
              # 결과 순번 — 테스트 이후 수정된 파일은 강등에서 제외
              "tests_passed_last": 0, "last_test_failed": False,
              "coverage_pct": None,
              "code_write_seq": {}, "last_test_seq": None,
              # 턴 확인 모델 (§50): 확인 시점(실질 지시 턴·세션 끝)마다
              # 그 구간에 코드 변경이 있으면 동작 확인 사건 1건 —
              # 그 시점의 테스트 상태 스냅샷을 함께 기록
              "code_check_events": [],
              # 긴 도구 실측 대기 — **분모에 가산하지 않는다** (§60).
              # §59에서 "건당 0.3분 고정은 10분짜리 벤치를 18초로 친다"며
              # 초과분을 얹었으나, 타임스탬프 실측과 대조하니 **얹기 전이 더
              # 정확했다**: 모델/실측 0.98(얹으면 1.11), 세션별 |log오차|
              # 0.625(얹으면 0.643), 허용범위(0.5~2.0배) 42/63(얹으면 40/63).
              # 이유 — 0.3분 고정이 0.5초짜리 수천 건에서 과금한 몫이 드문
              # 장시간 호출을 이미 상쇄하고 있었다. 개별 호출로는 틀리지만
              # 총합에서는 맞는 구조. 감사용으로 집계만 남긴다.
              "long_wait_min": 0.0, "long_wait_events": 0,
              # AI 동작 시간 실측 (§62·§65·§87): 턴을 연 입력 → 그 턴의 AI
              # 기록들 사이 간격 합. 방치는 R0·R1로 빼고, 10분 상한은 방치·
              # 승인 대기가 섞일 수 있는 간격에만 남긴다(§87, 위 주석).
              # AI가 끝낸 뒤 다음 사람 발화까지는 사람 시간이라 제외.
              "ai_wall_min": 0.0, "ai_turns": 0,
              # 배경작업 대기 (§84·§87·§88): AI가 답을 끝낸 뒤 배경 서브에이전트·
              # 배경 명령·감시(Monitor)가 <task-notification>으로 깨운 경우, 직전
              # AI 기록 → 알림 간격을 ai_wall_min에 가산한다. completed·감시
              # 이벤트는 상한 없음, failed·killed·stopped는 _AI_GAP_CAP_SEC 상한.
              # bg_wait_min = 가산분, bg_wait_cut_min = 상한에 잘린 초과분.
              "bg_wait_min": 0.0, "bg_wait_events": 0, "bg_wait_cut_min": 0.0,
              # §93 이미 끝난 작업의 종료 알림 재도착 — 대기로 안 센 건수·간격
              # (감사용). 세션을 며칠 뒤 다시 열면 같은 task-id 완료 알림이
              # 또 온다: 그 앞 공백은 방치다.
              "bg_dup_events": 0, "bg_dup_skip_min": 0.0,
              # §94 10분 넘는 상한 없는 간격(R2·R3·R4) — 증거와 겹친 만큼만 셌다.
              # long_gaps: [{kind, start, end, gap_min, evidence_min, counted_min}],
              # unproven_cut_min: 증거가 없어 잘린 시간 합 (감사용)
              "long_gaps": [], "unproven_cut_min": 0.0,
              # §89 배경 실행(Bash·PowerShell) 목록 — BackgroundExecTracker,
              # 분자도 같은 판정기를 쓴다 (감사·대칭 확인용, 분모 계산엔 안 씀)
              "bg_exec_jobs": [],
              # 세션 러닝타임 (§64): 첫 기록 ~ 마지막 기록. 초소형 세션
              # 제외 판정에 쓴다 — 5분 안에 끝난 세션은 측정 가치가 없다.
              "session_span_min": 0.0,
              "session_id": None, "first_ts": None, "last_ts": None}
    pending_calls = {}  # tool_use id -> 시작 시각(초)
    turn_start = None   # 이 턴을 연 입력 시각 (§62)
    turn_prev = None    # 이 턴에서 마지막으로 시간을 센 지점 (§65)
    last_answer_w = 0  # 직전 assistant 발언 단어수 (턴 마무리 = 결론 후보)
    pending_tests = {}  # 테스트 실행 tool_use id → 결과 대기
    seq = 0             # 도구 사건 순번 (§49 쓰기↔테스트 선후 판정용)
    after_interrupt = False  # 직전 사람 발화가 interrupt였는가 (§49)
    seg_code = {}       # 이번 확인 구간에 변경된 코드 파일 {fp: 마지막 seq}
    seg_files = {}      # §79 이번 구간에 생성·수정된 파일 {fp: 쓴 단어 누적}
    last_tw = 0.0       # §80 직전 시각(시각 없는 레코드가 물려받음)
    last_answer_t = 0.0 # 직전 assistant 발언 시각 (결론 귀속용, §80)
    art_ops = {}        # fp → [(t, words)] 쓰기 사건 (Write는 목록 초기화, §80)
    art_first_t = {}    # fp → 첫 쓰기 시각 (파일당 항목 귀속, §80)

    def _flush_check_event(t=None):
        """확인 시점 도달: 구간에 파일 생성·수정이 있으면 사건 기록 (§50·§79)."""
        if not seg_files:
            return
        lt = counts["last_test_seq"]
        dirty = (sum(1 for s in seg_code.values() if s > lt)
                 if lt is not None else 0)
        # §79 축약 모드용 검증 위임: 확인 시점의 마지막 테스트가 통과 상태면
        # 그 테스트 이전에 쓴 코드 파일은 확인 단어에서 **뺀다**(테스트가 대신
        # 봤다). 테스트 뒤에 또 고친 파일(dirty)·코드 아닌 파일은 남는다.
        # 기본 모드는 words를 쓰지 않는다(files·dirty·테스트 상태만).
        verified = (lt is not None and not counts["last_test_failed"])
        excluded = {fp for fp, sq in seg_code.items()
                    if verified and sq <= lt}
        words_raw = sum(seg_files.values())
        words = sum(w for fp, w in seg_files.items() if fp not in excluded)
        counts["code_check_events"].append({
            "files": len(seg_code), "dirty": dirty,
            "has_test": lt is not None,
            "tests_passed": counts["tests_passed_last"],
            "test_failed": counts["last_test_failed"],
            "coverage": counts["coverage_pct"],
            # §79 축약 모드 입력: 구간에 쓴 파일 수·단어 (코드 외 포함).
            # words = 검증 제외 후, words_raw = 제외 전
            "all_files": len(seg_files), "verified_files": len(excluded),
            "words": words, "words_raw": words_raw,
            "t": t if t is not None else last_tw})   # §80 확인 시점 시각
        seg_code.clear()
        seg_files.clear()
    seen_uuid = set()    # §87 R0 재기록 중복 레코드 판별
    tool_names = {}      # §87 R3 tool_use id → 도구 이름
    bg_exec = BackgroundExecTracker()
    evidence = WaitEvidence()   # §94 배경 작업 장부 겸 긴 대기 증거
    long_gaps = []              # §94 (종류, 시작, 끝) — 10분 넘는 간격, 끝에서 판정

    def _gap(kind, a, b, eligible):
        """§94 간격 하나를 센다 — 규칙은 하나: 10분까지는 바로 센다. 넘는 부분은
        eligible(상한 없이 셀 수 있는 종류)일 때만 보관해 끝에서 증거만큼 더한다.
        반환 (간격 초, 바로 센 초)."""
        gap = max(0.0, b - a)
        add = min(gap, _AI_GAP_CAP_SEC)
        counts["ai_wall_min"] += add / 60
        if eligible and gap > _AI_GAP_CAP_SEC:
            long_gaps.append((kind, a, b))
        return gap, add
    with open(jsonl_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            # §87 R0: 같은 uuid가 다시 나오면 파일 끝에 다시 붙은 옛 레코드다
            # (옛 시각 그대로). 시간·집계 모두 이미 반영됐으므로 건너뛴다.
            uid = rec.get("uuid")
            if uid:
                if uid in seen_uuid:
                    continue
                seen_uuid.add(uid)
            counts["session_id"] = counts["session_id"] or rec.get("sessionId")
            rec_t = _epoch(rec.get("timestamp"))
            tw = rec_t if rec_t else last_tw   # §80 귀속 시각(물려받기)
            last_tw = tw
            redelivered = False
            if not rec.get("isSidechain"):
                bg_exec.feed(rec, rec_t)       # §89 공용 배경 실행 판정
                # §94 장부: 이 기록이 이미 끝난 실행의 종료 알림 재도착인가
                redelivered = evidence.feed(rec, rec_t)
            inw = _inw(tw)
            ts = rec.get("timestamp")
            if ts:
                counts["first_ts"] = counts["first_ts"] or ts
                counts["last_ts"] = ts
            rtype = rec.get("type")
            # §87 R1: AI를 깨운 입력(isMeta: 예약 타이머·다른 세션 메시지 등 /
            # isCompactSummary: 압축 요약)은 지시로는 안 세지만 AI 시간의
            # 경계다 — 그 앞 공백은 AI가 쉬던 시간(방치)이므로 시계만 옮긴다.
            # §94: "쉬던 중"이 확인될 때만 — AI가 답을 끝냈고(직전 메인 기록이
            # 도구 호출 없는 답) 결과 기다리는 도구·돌고 있는 배경 실행·배경
            # 서브에이전트가 없을 때. isMeta에는 스킬 본문·그림 첨부·이어가기
            # 안내도 섞여 있다(이 PC: 그림 46건 중 11건은 도구가 돌던 중).
            # 확인 안 되면 종전대로 경계로 안 쓴다(간격은 10분 + 증거만큼).
            # 압축 요약은 경계가 아니다 — 요약이 있다는 것 자체가 그 앞에서 AI가
            # 압축하던 증거다(외부 보고: 자동 압축 14지점 0.4~6.5분이 빠졌다).
            # 쉬던 시간은 압축을 시킨 입력(사람 발화·/compact)이 이미 끊는다.
            if (rtype == "user" and rec_t and turn_prev
                    and not rec.get("isSidechain")
                    and rec.get("isMeta") and not rec.get("isCompactSummary")
                    and not any(isinstance(x, dict)
                                and x.get("type") == "tool_result"
                                for x in _content_blocks(rec.get("message")))
                    and evidence.idle() and not bg_exec.running):
                turn_prev = max(turn_prev, rec_t)
            if (rtype not in ("user", "assistant") or rec.get("isMeta")
                    or rec.get("isSidechain")          # 병렬 — 시간 가산 금지
                    or rec.get("isCompactSummary")     # 압축 요약 ≠ 사용자 지시
                    or rec.get("isVisibleInTranscriptOnly")):
                continue
            blocks = _content_blocks(rec.get("message"))

            if rtype == "assistant":
                if turn_start is not None and rec_t and turn_prev:
                    # §87 R2: 답 생성 간격 — 느린 응답·서버 과부하 재시도 대기도
                    # AI 시간(§94: 10분 넘는 부분은 증거만큼). 세션 이어 붙이기용
                    # 가짜 답은 빼고(_resume_artifact), 시계는 뒤로 안 간다.
                    if inw and not _resume_artifact(rec) and rec_t > turn_prev:
                        # §80 시간 조각은 끝나는 레코드 시각에 귀속
                        _gap("R2", turn_prev, rec_t, True)
                    turn_prev = max(turn_prev, rec_t)
                ans_w = 0
                for b in blocks:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        if inw:
                            counts["tool_calls"] += 1
                        if b.get("id") and rec_t:
                            pending_calls[b["id"]] = rec_t
                        if b.get("id"):
                            tool_names[b["id"]] = b.get("name")
                        seq += 1
                        inp = b.get("input") or {}
                        if b.get("name") == "StructuredOutput":
                            # 구조화 보고 채널 (§34): 최종 산출물이 답변 텍스트
                            # 대신 이 도구 입력(JSON)으로 나간다 — AI가 써낸
                            # 분량(draft)이자 사람이 읽을 결론(review 정독)으로
                            # 답변 텍스트와 동급 계상
                            ans_w += json_text_words(inp)
                        cmd = inp.get("command")
                        if (b.get("name") in ("Bash", "PowerShell")
                                and isinstance(cmd, str)
                                and _TEST_CMD_RE.search(cmd) and b.get("id")):
                            pending_tests[b["id"]] = True
                        fp = inp.get("file_path")
                        name = b.get("name")
                        if name in ("Agent", "Task") and inw:  # §52 서브 지시문
                            counts["tool_input_draft_words"] += _words(
                                inp.get("prompt") or "")
                        if fp and name in ("Write", "Edit", "NotebookEdit"):
                            body = (inp.get("content")
                                    or inp.get("new_string")
                                    or inp.get("new_source") or "")
                            if inw:
                                counts["tool_input_draft_words"] += _words(body)
                            acls = _artifact_class(fp)
                            art_first_t.setdefault(fp, tw)
                            if name == "Write":  # 전체 재작성 — 마지막 판만
                                art_ops[fp] = [(tw, _words(body), acls)]
                            else:                # 부분 수정 — 누적
                                art_ops.setdefault(fp, []).append(
                                    (tw, _words(body), acls))
                            seg_files[fp] = (seg_files.get(fp, 0)   # §79
                                             + _words(body))
                            if acls == "code":   # §49 마지막 쓰기 순번
                                counts["code_write_seq"][fp] = seq
                                seg_code[fp] = seq  # §50 이번 구간 코드 변경
                    elif b.get("type") == "text":
                        ans_w += _words(b.get("text", ""))
                if inw:
                    counts["assistant_words"] += ans_w
                if ans_w:
                    last_answer_w = ans_w
                    last_answer_t = tw
                continue

            # §62 AI 구간 경계: tool_result가 아닌 user 레코드는 무엇이든
            # AI를 깨운 입력이다(사람 발화·배경작업 알림·시스템 주입·중단).
            # 그 직전까지 AI는 놀고 있었으므로 여기서 구간을 끊는다 — 안 끊으면
            # 알림이 몇 시간 뒤에 와도 그 대기가 AI 시간에 들어간다.
            if not any(isinstance(b, dict) and b.get("type") == "tool_result"
                       for b in blocks):
                # §84 배경작업 알림(<task-notification>)은 예외 — 포그라운드
                # tool_result처럼 센다. 배경 서브에이전트·배경 명령은 사람이
                # 아니라 AI가 시킨 일이고 결과가 올 때까지 일은 안 끝난 것
                # (사람 관점 벽시계)이므로, 같은 일을 배경으로 돌렸다고 분모가
                # 줄면 안 된다.
                # §87 R4: 정상 완료(completed)는 상한 없음 — 작업이 실제로 돈
                # 시간이다(실측: 5시간 야간 배치). failed·killed·stopped는
                # 상한 유지 — 켜 두었다 끈 서버, 사용량 한도로 5초 만에 멈춘
                # 서브에이전트의 알림이 238분 뒤 온 사례 등 일한 시간이 아니다.
                # §88: 감시(Monitor) 이벤트 알림(<status> 없이 <event>만)도
                # 상한 없음 — AI가 걸어 둔 감시 대상(학습·일괄 실행)이 돌던
                # 시간이다(실측 62건 전부 진행 신호, 종료·타임아웃 0건; 5d38d92b
                # 84·46·44·43분 이벤트가 10분씩으로 잘려 180분 미계상).
                # 초과분은 bg_wait_cut_min에 감사용으로만 남긴다.
                # §93: 이미 종료 알림을 받은 task-id의 종료 알림이 또 오면(세션을
                # 며칠 뒤 다시 열 때 재전달) 기다릴 작업이 없었다 — 대기 0, 경계만.
                # 사이에 SendMessage·resume으로 다시 돌렸으면 정상 대기.
                # §94: 재도착은 본문이 첫 알림과 같을 때만 확인된 것으로 본다. 다르면
                # 모르는 경우 — 보통 대기로 세고 10분 넘는 부분은 증거만큼.
                bg_text = " ".join(
                    b.get("text", "") for b in blocks
                    if isinstance(b, dict) and b.get("type") == "text")
                is_bg_notif = bg_text.lstrip().startswith("<task-notification")
                if (is_bg_notif and turn_start is not None and rec_t
                        and turn_prev):
                    full = ("<status>completed</status>" in bg_text
                            or ("<status>" not in bg_text     # §88
                                and "<event>" in bg_text))
                    if inw and redelivered:       # §93 확인된 재도착 → 0
                        counts["bg_dup_events"] += 1
                        counts["bg_dup_skip_min"] += max(0.0, rec_t - turn_prev) / 60
                    elif inw:
                        gap, add = _gap("R4", turn_prev, rec_t, full)
                        counts["bg_wait_min"] += add / 60
                        counts["bg_wait_events"] += 1
                        counts["bg_wait_cut_min"] += (gap - add) / 60
                    turn_prev = max(turn_prev, rec_t)
                if turn_start is not None and turn_prev is not None \
                        and turn_prev > turn_start:
                    if _inw(turn_start):
                        counts["ai_turns"] += 1
                if rec_t:
                    turn_start = rec_t
                    turn_prev = rec_t
                else:
                    turn_start = turn_prev = None

            # user 턴: 사람 발화 vs tool_result 구분.
            # 시스템 주입 블록(<system-reminder> 등)은 사람 지시가 아님 — 제외
            human_text = ""
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_result":
                    if turn_start is not None and rec_t and turn_prev:
                        if inw and rec_t > turn_prev:
                            # §87 R3: 정상 결과 + 제한 없는 도구(포그라운드
                            # 서브에이전트·MCP 등)는 상한 없음. 실행 시간이
                            # 막히거나 즉시 끝나는 도구·사람을 기다리는 도구·
                            # 오류 결과는 §65 상한 유지(넘으면 방치·승인 대기).
                            gap = rec_t - turn_prev
                            name = tool_names.get(b.get("tool_use_id"))
                            full = (not b.get("is_error") and name
                                    and name not in _BOUNDED_TOOLS
                                    and name not in _HUMAN_WAIT_TOOLS)
                            _gap("R3", turn_prev, rec_t, full)
                        turn_prev = max(turn_prev, rec_t)
                    if inw:
                        counts["tool_result_words"] += _result_words(b)
                    seq += 1
                    t0 = pending_calls.pop(b.get("tool_use_id"), None)
                    if t0 and rec_t and 0 <= rec_t - t0 < 3600 and inw:
                        # 문턱 초과분만 실측으로 (§59): 건당 고정 요율이
                        # 짧은 호출을 이미 과금하므로 이중계상 방지
                        over = (rec_t - t0) - _WAIT_THRESHOLD_SEC
                        if over > 0:
                            counts["long_wait_min"] += over / 60
                            counts["long_wait_events"] += 1
                    if pending_tests.pop(b.get("tool_use_id"), None):
                        counts["last_test_seq"] = seq  # §49 테스트 결과 순번
                        out = _result_text(b)
                        if _FAILED_RE.search(out):
                            counts["last_test_failed"] = True
                        else:
                            m = _PASSED_RE.search(out)
                            if m:
                                counts["tests_passed_last"] = int(
                                    m.group(1) or m.group(2))
                                counts["last_test_failed"] = False
                        cv = _COVERAGE_RE.search(out)
                        if cv:
                            counts["coverage_pct"] = int(cv.group(1))
                elif b.get("type") == "text":
                    t = b.get("text", "")
                    if not t.lstrip().startswith(_SYSTEM_TEXT_PREFIXES):
                        human_text += t + " "
            human_text = human_text.strip()
            if human_text:
                if human_text.startswith("[Request interrupted"):
                    if inw:
                        counts["interrupts"] += 1
                    after_interrupt = True
                else:
                    if inw:
                        counts["user_instructions"] += 1
                    if after_interrupt:  # §49 교정성 지시 표시 (과금 없음)
                        if inw:
                            counts["corrective_instructions"] += 1
                        after_interrupt = False
                    w = _words(human_text)
                    if inw:
                        counts["user_words"] += w
                        counts["instruction_word_list"].append(w)
                    # 새 사용자 발화 = 직전 답변이 그 턴의 결론(정독 대상).
                    # 단, 짧은 이어가기("계속해" 등, 문턱 미만)는 승격 안 함
                    # (§49) — 직전 답변은 유지되어 다음 답변이 나오면 진행
                    # 보고(훑기)로, 세션 끝이면 최종 flush로 결론이 된다.
                    # 같은 문턱이 산출물 확인 시점(§50)도 정한다 — 실질
                    # 지시 턴 = 사람이 멈춰서 결과를 살펴본 시점.
                    if w >= _CONCL_PROMOTE_MIN_WORDS:
                        if last_answer_w and _inw(last_answer_t):  # §80 답변 시각
                            counts["conclusion_words"] += last_answer_w
                            counts["conclusion_word_list"].append(last_answer_w)
                        last_answer_w = 0
                        _flush_check_event(tw)
    if turn_start is not None and turn_prev is not None \
            and turn_prev > turn_start:                      # §62 마지막 턴
        if _inw(turn_start):
            counts["ai_turns"] += 1
    if last_answer_w and _inw(last_answer_t):  # 마지막 턴 결론
        counts["conclusion_words"] += last_answer_w
        counts["conclusion_word_list"].append(last_answer_w)
    _flush_check_event(last_tw)  # 세션 끝 = 마지막 확인 시점 (§50)
    # §80 구간 계상 마무리: 확인 사건은 확인 시점 시각으로, 산출물 단어는
    # 쓰기 사건 시각으로, 파일당 항목(표본 확인)은 첫 쓰기 시각으로 귀속
    counts["code_check_events_all"] = counts["code_check_events"]
    counts["code_check_events"] = [ev for ev in counts["code_check_events"]
                                   if _inw(ev.get("t"))]
    first_files = {"code": 0, "doc": 0, "other": 0}
    for fp, ops in art_ops.items():
        acls = ops[-1][2]
        w = sum(n for t, n, _c in ops if _inw(t))
        if w or any(_inw(t) for t, _n, _c in ops):
            counts["artifact_files"][acls][fp] = w
        if _inw(art_first_t.get(fp)):
            first_files[acls] += 1
    counts["artifact_first_files"] = first_files
    counts["count_window"] = list(win) if win else None
    f0 = _epoch(counts.get("first_ts")); f1 = _epoch(counts.get("last_ts"))
    if f0 and f1 and f1 >= f0:
        counts["session_span_min"] = (f1 - f0) / 60      # §64
    counts["bg_exec_jobs"] = bg_exec.result()
    # §94 10분 넘는 간격: 증거와 겹친 만큼만 더 센다 (이미 10분은 넣었다)
    evidence.finish(counts["bg_exec_jobs"])
    for kind, a, b in long_gaps:
        cov = evidence.covered_for(kind, a, b)
        extra = max(0.0, cov - _AI_GAP_CAP_SEC)
        counts["ai_wall_min"] += extra / 60
        if kind == "R4":
            counts["bg_wait_min"] += extra / 60
            counts["bg_wait_cut_min"] -= extra / 60
        counts["unproven_cut_min"] += (b - a - _AI_GAP_CAP_SEC - extra) / 60
        counts["long_gaps"].append({
            "kind": kind, "start": a, "end": b,
            "gap_min": round((b - a) / 60, 2),
            "evidence_min": round(cov / 60, 2),
            "counted_min": round((_AI_GAP_CAP_SEC + extra) / 60, 2)})
    return counts


def actual_effort_minutes(counts, rates=None, hitl_compact=True):
    """동작 카운트 × rates.json 요율 → 분. 반환:
    {machine_min, hitl_min, total_min, breakdown{...}}

    hitl_compact: §79 hitl 축약 모드 — 파일 확인을 확인 시점당 로그·상한
    1건으로, 테스트 통과 파일 제외, correct 미계상. §85부터 기본 True;
    False 는 §76 전체 모델.
    """
    r = rates or load_rates(DEFAULT_RATES_PATH)
    a, h = r["agent"], r["hitl"]
    # AI 몫은 **실측 우선** (§62). 요율 계산은 실측 대비 1.29배 과대였고
    # 세션별로 1.25~3.94배로 흩어졌다. 타임스탬프가 없는 구 기록에서만
    # 요율 계산으로 폴백한다.
    rate_machine = {
        "execute": counts["tool_calls"] * a["execute"]["min_per_unit"],
        "read": counts["tool_result_words"] * a["read"]["min_per_unit"],
        # draft = 답변 + 도구 입력으로 생산된 글(파일 본문·서브에이전트
        # 지시문, §52) — 파일에 쓴 2,000단어가 채팅에 쓴 2,000단어와 같은
        # 생산 비용이 되도록. 셸 명령 텍스트는 execute 건당 요율에 포함된
        # 것으로 보고 제외(이중과금 방지).
        "draft": (counts["assistant_words"]
                  + counts.get("tool_input_draft_words", 0))
                 * a["draft"]["min_per_unit"],
    }
    wall = counts.get("ai_wall_min", 0.0)
    # 타임스탬프가 없는 구 기록만 요율 계산으로 폴백
    machine = {"measured": wall} if wall > 0 else dict(rate_machine)
    im = r.get("hitl_instruct_model")
    if im:  # 실측 보정 모델: base + per_word×min(단어수, cap) — 붙여넣기 과금 방지
        wl = counts.get("instruction_word_list") or              [0] * counts["user_instructions"]
        instruct_min = sum(im["base_min"]
                           + im["per_word_min"] * min(w, im["word_cap"])
                           for w in wl)
    else:  # 폴백: 건당 평균 요율
        instruct_min = counts["user_instructions"] * h["instruct"]["min_per_unit"]
    rm = r.get("hitl_review_model")
    fc = (r.get("hitl_compact_model") or {}).get("file_check") \
        if hitl_compact else None
    if hitl_compact and not (rm and fc):
        raise ValueError("hitl_compact=True needs rates.hitl_compact_model."
                         "file_check and hitl_review_model")
    if fc:  # §79 축약 모드: 파일 확인 — 확인 시점당 로그·상한, 유형 무관
        # 사람은 만든 수단(스크립트)이 아니라 결과물을 본다. 실측(§63)은
        # 확인 비용이 변경 규모와 거의 무관(20배 커져도 7.5→3.6분)이라
        # 선형 대신 로그 + 상한: 구간에 파일 쓰기가 있으면
        # min(cap, a·ln(1 + 구간 쓴 단어/b)). 코드/문서/기타 구분, 동작 확인
        # 2.0, 규모 비례 대조는 안 쓴다. 확인 시점의 테스트가 통과면 그 이전에
        # 쓴 코드 파일은 확인 대상에서 제외(automation_saved_min = 그 차이).
        cap = rm.get("report_deep_word_cap")
        cl = counts.get("conclusion_word_list")
        if cap and cl is not None:
            concl = sum(min(w, cap) for w in cl)
        else:
            concl = counts.get("conclusion_words", 0)
        concl = min(concl, counts["assistant_words"])
        progress = counts["assistant_words"] - concl
        events = counts.get("code_check_events") or []

        def _fc(w):
            if w is None:  # 구 counts 호환 — 단어 미기록이면 상한
                return fc["cap_min"]
            return min(fc["cap_min"], fc["a_min"] * math.log1p(w / fc["b_words"]))
        check_min = 0.0
        automation_saved = 0.0  # §78 테스트가 대신 본 파일만큼 줄어든 확인비
        for ev in events:
            m = _fc(ev.get("words"))
            check_min += m
            automation_saved += _fc(ev.get("words_raw", ev.get("words"))) - m
        automation_saved = round(automation_saved, 2)
        review_min = (check_min
                      + concl * rm["report_deep_min_per_word"]
                      + progress * rm["report_skim_min_per_word"])
    elif rm:  # 기본(§50~§76): 유형별 검토 — 코드=동작 확인, 문서=정독
        af = counts.get("artifact_files") or {}
        code_files = af.get("code") or {}
        doc_files = af.get("doc") or {}
        other_files = af.get("other") or {}
        # 결론 정독 상한 (§51): 사람은 긴 마무리 답변도 요약·결론부까지만
        # 정독하고 나머지는 훑는다 — 결론 건별로 cap 단어까지 정독, 초과분은
        # 훑기로 강등. instruct의 붙여넣기 상한(60단어)과 같은 원리.
        cap = rm.get("report_deep_word_cap")
        cl = counts.get("conclusion_word_list")
        if cap and cl is not None:
            concl = sum(min(w, cap) for w in cl)
        else:  # 구 counts 호환 — 상한 없이 결론 전량 정독
            concl = counts.get("conclusion_words", 0)
        concl = min(concl, counts["assistant_words"])
        progress = counts["assistant_words"] - concl
        # 턴 확인 모델 (§50): 사람은 AI 출력을 전량 정독하지 않는다 —
        # 확인 시점(실질 지시 턴·세션 끝)마다 멈춰서 살펴보고 넘어간다.
        #   대화: 결론만 정독, 나머지 진행 보고는 훑기 (기존과 동일).
        #   산출물: 내용 전량 읽기 대신 ① 그 구간에 코드 변경이 있으면
        #   동작 확인 1회(확인 시점의 테스트 상태로 강등 — 통과면 "결과
        #   서명" 0.3까지, 구간 내 테스트 이후 수정 파일은 검증 분율에서
        #   제외 §49) ② 변경 규모(코드·문서 단어)에 비례하는 확인 — 읽기가
        #   아니다(§61): 수정량이 많으면 돌려보고 대조할 것도 많다. 코드와
        #   문서는 요율이 다르다(§63) ③ 문서·기타
        #   파일은 파일당 표본 확인. 구 문서 전량 정독(0.008/단어)·§49
        #   에피소드+추가파일 과금은 폐지.
        run_rate = rm["code_run_min_per_file"]
        automation_saved = 0.0
        floor = rm.get("verified_check_min_per_file")
        events = counts.get("code_check_events")
        if events is None:  # 구 counts 호환 — 세션 전체를 확인 1회로 근사
            n_code = len(code_files)
            events = [{"files": n_code, "dirty": 0, "has_test":
                       counts.get("last_test_seq") is not None,
                       "tests_passed": counts.get("tests_passed_last", 0),
                       "test_failed": counts.get("last_test_failed", False),
                       "coverage": counts.get("coverage_pct")}] if n_code else []
        check_min = 0.0
        for ev in events:
            if not ev.get("files"):  # 코드 변경 없는 구간(§79 파싱 확장) — 기본 모드는 동작 확인 없음
                continue
            rate = run_rate
            if (floor is not None and ev.get("has_test")
                    and not ev.get("test_failed") and ev.get("files")):
                if ev.get("coverage") is not None:
                    ratio = min(1.0, ev["coverage"] / 100.0)
                else:
                    expected = (ev["files"]
                                * rm.get("expected_tests_per_file", 3))
                    ratio = (min(1.0, ev.get("tests_passed", 0) / expected)
                             if expected else 0.0)
                ratio *= (ev["files"] - ev.get("dirty", 0)) / ev["files"]
                rate = run_rate - (run_rate - floor) * ratio
                automation_saved += run_rate - rate
            check_min += rate
        automation_saved = round(automation_saved, 2)
        # 변경 규모 비례 확인 요율 (§61·§63) — 키 이름의 skim은 이력상
        # 잔재이고 읽는 속도가 아니다. 산출물 규모가 키우는 확인 부담이며,
        # 코드와 문서를 나눈다: 같은 0.002가 문서에선 분당 500단어(훑기,
        # 말 됨)지만 코드에선 시간당 6,073줄(말 안 됨)이 되기 때문.
        # 문서는 code_run(동작 확인)이 안 붙으므로 이 항이 확인의 전부다.
        code_rate = rm["code_skim_min_per_word"]
        doc_rate = rm.get("doc_skim_min_per_word", code_rate)
        _ff = counts.get("artifact_first_files")   # §80 파일당 항목 = 첫 쓰기 구간
        n_sample_files = ((_ff.get("doc", 0) + _ff.get("other", 0)) if _ff
                          else (len(doc_files) + len(other_files)))
        review_min = (
            check_min
            + sum(code_files.values()) * code_rate
            + sum(doc_files.values()) * doc_rate
            + n_sample_files
            * rm["other_check_min_per_file"]
            + concl * rm["report_deep_min_per_word"]
            + progress * rm["report_skim_min_per_word"])
    else:  # 폴백: 보고 전량 × 단일 요율 (구식)
        review_min = counts["assistant_words"] * h["review"]["min_per_unit"]
        automation_saved = 0.0
    hitl = {
        "instruct": instruct_min,
        "review": review_min,
    }
    if not hitl_compact:  # §79 축약 모드는 correct 미계상(instruct와 이중)
        hitl["correct"] = counts["interrupts"] * h["correct"]["min_per_unit"]
    machine_min = round(sum(machine.values()), 2)
    hitl_min = round(sum(hitl.values()), 2)
    return {
        "machine_min": machine_min,
        "hitl_min": hitl_min,
        "total_min": round(machine_min + hitl_min, 2),
        "automation_saved_min": automation_saved,  # 자동 검증이 없앤 사람 노동
        "hitl_compact": hitl_compact,              # §79 축약 모드 여부
        "breakdown": {
            "machine": {k: (round(v, 2) if isinstance(v, (int, float)) else v)
                        for k, v in machine.items()},
            # 참고: 구 요율 계산값 (§62 이전 방식) — 실측과 대조용
            "machine_rate_estimate": {k: round(v, 2)
                                      for k, v in rate_machine.items()},
            "hitl": {k: round(v, 2) for k, v in hitl.items()},
        },
        "counts": counts,
    }


def measure(jsonl_path, rates_path=DEFAULT_RATES_PATH):
    """편의 함수: 파일 경로 → actual_effort_minutes 결과."""
    return actual_effort_minutes(parse_actions(jsonl_path),
                                 load_rates(rates_path))


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for p in sys.argv[1:]:
        m = measure(p)
        c = m["counts"]
        print(f"{Path(p).name}: machine={m['machine_min']}min "
              f"hitl={m['hitl_min']}min total={m['total_min']}min "
              f"(tools={c['tool_calls']}, instr={c['user_instructions']}, "
              f"aw={c['assistant_words']})")
