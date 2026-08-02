#!/usr/bin/env node
// 빌드된 exe 스모크: pkg 스냅샷에서 asset 읽기·스윕 전체 경로가 실제로 도는지 검증 (mock Haiku, 송출 생략)
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const exe = path.resolve(process.argv[2]);
const TMP = path.join(__dirname, ".tmp-exe");
fs.rmSync(TMP, { recursive: true, force: true });

const projDir = path.join(TMP, "projects", "C--fake-proj");
fs.mkdirSync(projDir, { recursive: true });
const uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
const t0 = Date.now() - 3 * 3600 * 1000;
const lines = [
  JSON.stringify({ type: "user", timestamp: new Date(t0).toISOString(), message: { role: "user", content: "UVM 시퀀스 만들어줘" } }),
  JSON.stringify({ type: "assistant", timestamp: new Date(t0 + 300000).toISOString(), message: { role: "assistant", content: [{ type: "text", text: "시퀀스 12종 생성 완료" }], usage: { input_tokens: 1000, output_tokens: 200 } } }),
];
const transcript = path.join(projDir, uuid + ".jsonl");
fs.writeFileSync(transcript, lines.join("\n") + "\n");
const old = new Date(Date.now() - 2 * 3600 * 1000);
fs.utimesSync(transcript, old, old);

const doc = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "avatars.sample.json"), "utf8"));
doc.avatars[0].loginId = process.env.USERNAME || "joung";
const avatarsPath = path.join(TMP, "avatars.json");
fs.writeFileSync(avatarsPath, JSON.stringify(doc));

const out = execFileSync(exe, ["sweep"], {
  encoding: "utf8",
  env: {
    ...process.env,
    AE_PROJECTS_DIR: path.join(TMP, "projects"),
    AE_OUTBOX_PATH: path.join(TMP, "outbox.jsonl"),
    AE_LOCK_PATH: path.join(TMP, "sweep.lock"),
    AE_ANALYSIS_CWD: path.join(TMP, "analysis"),
    AE_AVATARS_PATH: avatarsPath,
    AE_FORCE: "1",
    AE_NO_SEND: "1",
    HAIKU_MOCK: "1",
    HAIKU_MOCK_RESULT: '{"taskId":"t4","roleId":"verification","confidence":0.9,"manualHoursEst":6,"quality":1,"rationale":"mock"}',
  },
});
console.log(out);
const ver = execFileSync(exe, ["version"], { encoding: "utf8" }).trim();
if (!/verification\/t4 η=/.test(out)) { console.error("EXE SMOKE FAIL: no match output"); process.exit(1); }
if (!fs.readFileSync(path.join(TMP, "outbox.jsonl"), "utf8").includes('"done"')) { console.error("EXE SMOKE FAIL: outbox"); process.exit(1); }
fs.rmSync(TMP, { recursive: true, force: true });
console.log(`EXE SMOKE OK (v${ver})`);
