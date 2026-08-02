#!/usr/bin/env node
// 스모크 테스트: mock Haiku + 실서버로 전 구간 실증.
// 1) 가짜 transcript 1건 → 스윕 → 매칭·η·outbox·서버 수신 확인
// 2) 재스윕 → 중복 처리 0건 (책갈피 검증)
// 3) 새 턴 append → 재스윕 → 재매칭 발생 (증분 검증)
const fs = require("fs");
const path = require("path");
const { execFileSync, spawn } = require("child_process");
const http = require("http");

const ROOT = path.resolve(__dirname, "..");
const TMP = path.join(__dirname, ".tmp");
const PORT = 18221;

function rmrf(p) { fs.rmSync(p, { recursive: true, force: true }); }
function assert(cond, msg) {
  if (!cond) { console.error("ASSERT FAIL: " + msg); process.exit(1); }
  console.log("ok - " + msg);
}
function get(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let b = "";
      res.on("data", (c) => (b += c));
      res.on("end", () => resolve(JSON.parse(b)));
    }).on("error", reject);
  });
}

function makeTranscript(file, turns) {
  const t0 = Date.now() - 3 * 3600 * 1000;
  const lines = [];
  for (let i = 0; i < turns; i++) {
    const ts = (m) => new Date(t0 + (i * 10 + m) * 60 * 1000).toISOString();
    lines.push(JSON.stringify({ type: "user", timestamp: ts(0), message: { role: "user", content: `Spyglass 린트 위반 ${128 - i * 60}건 자동 수정해줘` } }));
    lines.push(JSON.stringify({ type: "assistant", timestamp: ts(5), message: { role: "assistant", content: [{ type: "text", text: `린트 위반 수정 완료 (배치 ${i + 1})` }], usage: { input_tokens: 50000, output_tokens: 3000, cache_read_input_tokens: 20000 } } }));
  }
  fs.appendFileSync(file, lines.join("\n") + "\n");
  const old = new Date(Date.now() - 2 * 3600 * 1000);
  fs.utimesSync(file, old, old); // 진행중 가드(30분) 통과용으로 오래된 mtime
}

async function main() {
  rmrf(TMP);
  const projectsDir = path.join(TMP, "projects", "C--fake-proj");
  fs.mkdirSync(projectsDir, { recursive: true });
  const uuid = "11111111-2222-3333-4444-555555555555";
  const transcript = path.join(projectsDir, uuid + ".jsonl");
  makeTranscript(transcript, 2);

  const recordsPath = path.join(TMP, "records.jsonl");
  const server = spawn("node", [path.join(ROOT, "server", "server.js")], {
    env: { ...process.env, AE_SERVER_PORT: String(PORT), AE_RECORDS_PATH: recordsPath },
    stdio: "inherit",
  });
  await new Promise((r) => setTimeout(r, 700));

  const loginId = process.env.USERNAME || "joung";
  const avatarsPath = path.join(TMP, "avatars.json");
  const doc = JSON.parse(fs.readFileSync(path.join(ROOT, "avatars.sample.json"), "utf8"));
  doc.avatars[0].loginId = loginId; // 이 PC 로그인 ID로 아바타 선별되도록
  fs.writeFileSync(avatarsPath, JSON.stringify(doc));

  const env = {
    ...process.env,
    AE_PROJECTS_DIR: path.join(TMP, "projects"),
    AE_OUTBOX_PATH: path.join(TMP, "outbox.jsonl"),
    AE_LOCK_PATH: path.join(TMP, "sweep.lock"),
    AE_ANALYSIS_CWD: path.join(TMP, "analysis"),
    AE_AVATARS_PATH: avatarsPath,
    AE_SERVER_URL: `http://127.0.0.1:${PORT}`,
    AE_FORCE: "1",
    HAIKU_MOCK: "1",
    HAIKU_MOCK_RESULT: '{"taskId":"t2","roleId":"rtl-design","confidence":0.92,"manualHoursEst":10,"quality":0.95,"rationale":"린트 자동수정 세션"}',
  };
  const sweep = () => execFileSync("node", [path.join(ROOT, "sweeper", "sweep.js")], { env, encoding: "utf8" });

  try {
    // 1) 첫 스윕: 매칭 + 송출
    let out = sweep();
    console.log(out);
    assert(/1 candidate/.test(out), "첫 스윕이 후보 1건을 찾음");
    assert(/rtl-design\/t2 η=/.test(out), "매칭 + η 산정됨");
    assert(/sent 1111/.test(out), "서버 송출 성공");
    const eff1 = await get(`http://127.0.0.1:${PORT}/efficiency`);
    const a = eff1.avatars[0];
    const t2 = a.roles[0].tasks.find((t) => t.taskId === "t2");
    assert(t2.sessions === 1 && t2.eta > 1, `서버 집계 반영 (t2 η=${t2.eta})`);
    assert(a.efficiency > 1, `아바타 효율 E=${a.efficiency} 계산됨`);
    assert(a.value.tokenCostKRW > 0 && a.value.roi > 0, `토큰 가치 산출 (ROI=${a.value.roi})`);

    // 2) 재스윕: 내용 그대로 → 중복 처리 0건 (mtime만 갱신해 과발화 함정 재현)
    const old = new Date(Date.now() - 90 * 60 * 1000);
    fs.utimesSync(transcript, old, old);
    out = sweep();
    console.log(out);
    assert(/0 candidate/.test(out), "재스윕 중복 처리 0건 (책갈피 dedup)");

    // 3) 새 턴 append → 재매칭 발생
    makeTranscript(transcript, 1);
    out = sweep();
    console.log(out);
    assert(/1 candidate/.test(out) && /η=/.test(out), "새 턴 append 후 재매칭 (증분 감지)");

    console.log("\nSMOKE OK");
  } finally {
    server.kill();
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
