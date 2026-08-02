const { spawnSync } = require("child_process");
const fs = require("fs");

function buildPrompt(avatar, excerpt) {
  const tree = avatar.roles.map((r) => ({
    roleId: r.id,
    name: r.name,
    script: r.script,
    tasks: r.tasks.map((t) => ({ taskId: t.id, name: t.name, script: t.script })),
  }));
  return [
    "너는 작업 세션 분류·측량기다. 아래 아바타의 역할·업무 후보 트리와 세션 발췌를 보고,",
    "이 세션이 어느 업무(taskId)에 해당하는지 매칭하고 수작업 대비 측량값을 산정하라.",
    "",
    "## 아바타",
    avatar.script,
    "",
    "## 후보 트리 (역할 → 업무, 각 업무 script의 앵커를 수작업 시간 추정 기준으로 사용)",
    JSON.stringify(tree, null, 1),
    "",
    "## 세션 발췌",
    "첫 프롬프트: " + (excerpt.firstPrompt || "(없음)"),
    excerpt.summaries.length ? "요약: " + excerpt.summaries.join(" / ") : "",
    "마지막 대화:",
    ...excerpt.lastMessages.map((m) => `[${m.role}] ${m.text}`),
    "",
    "## 출력 규칙",
    "JSON 하나만 출력. 다른 텍스트 금지. 스키마:",
    '{ "workSummary": "이 세션이 실제로 수행한 일 1~2문장 (매칭과 무관하게 항상 작성)",',
    '  "taskId": "t1" | "misc", "roleId": "rtl-design" | null, "confidence": 0~1,',
    '  "manualHoursEst": 숫자(사람이 이 세션의 산출물을 수작업으로 만들 때 예상 시간, 시간 단위),',
    '  "quality": 0~1(완료도: 미완·재작업 필요시 할인), "rationale": "한 문장" }',
    '어느 업무에도 해당하지 않으면 taskId를 "misc"(기타 업무)로, roleId는 null로 하되',
    "workSummary에 실제 한 일을 구체적으로 적어라 — 신규 업무 후보 설명으로 쓰인다.",
    "manualHoursEst·quality는 misc여도 산정하라. 억지 매칭 금지.",
  ].join("\n");
}

function extractJson(text) {
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end <= start) throw new Error("no JSON in model output: " + text.slice(0, 200));
  return JSON.parse(text.slice(start, end + 1));
}

// claude -p --model haiku (구독) 호출.
// - cwd = 전용 분석 폴더: 이 호출의 transcript가 한 폴더에만 쌓여 스캔 제외됨 (자기 꼬리 재귀 차단)
// - env: CLAUDE* 제거 + SWEEPER_CHILD=1 (훅 재귀 가드)
function matchSession(cfg, avatar, excerpt) {
  if (process.env.HAIKU_MOCK === "1") {
    return JSON.parse(
      process.env.HAIKU_MOCK_RESULT ||
        '{"workSummary":"mock 작업","taskId":"t1","roleId":"rtl-design","confidence":0.9,"manualHoursEst":8,"quality":0.95,"rationale":"mock"}'
    );
  }
  fs.mkdirSync(cfg.analysisCwd, { recursive: true });
  const env = { SWEEPER_CHILD: "1" };
  for (const [k, v] of Object.entries(process.env)) {
    if (!/^CLAUDE/i.test(k)) env[k] = v;
  }
  const prompt = buildPrompt(avatar, excerpt);
  const res = spawnSync(cfg.claudeCmd, ["-p", "--model", cfg.model], {
    cwd: cfg.analysisCwd,
    env,
    input: prompt,
    encoding: "utf8",
    timeout: 180000,
    shell: process.platform === "win32", // claude.cmd shim
  });
  if (res.error) throw res.error;
  if (res.status !== 0) throw new Error("claude -p failed: " + (res.stderr || "").slice(0, 300));
  return extractJson(res.stdout || "");
}

module.exports = { matchSession, buildPrompt };
