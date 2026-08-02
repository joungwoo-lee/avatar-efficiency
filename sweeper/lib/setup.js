const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn, spawnSync } = require("child_process");
const { DATA_DIR, IS_PKG, REPO_ROOT } = require("./config");
const { getWindowsLoginId } = require("./login-id");

const WIN = process.platform === "win32";
const TASK_NAME = "avatar-efficiency-sweep";

function isWsl() {
  try {
    return process.platform === "linux" && /microsoft/i.test(fs.readFileSync("/proc/version", "utf8"));
  } catch (_) {
    return false;
  }
}

function installDir() {
  return WIN
    ? path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local"), "avatar-efficiency")
    : path.join(os.homedir(), ".local", "share", "avatar-efficiency");
}

// ── setup: 바이너리 1회 실행으로 전부 구성 ──────────────────────────────
function runSetup() {
  if (!IS_PKG) {
    console.log("레포 모드에서는 setup 불필요 — hook/install.ps1 사용 또는 build 후 바이너리로 실행.");
    return;
  }
  const log = (m) => console.log("  " + m);
  console.log("avatar-efficiency setup\n");

  // 1. 자가 설치 (다운로드 폴더에서 실행해도 고정 위치로 복사)
  const dir = installDir();
  fs.mkdirSync(dir, { recursive: true });
  const exe = path.join(dir, WIN ? "avatar-efficiency.exe" : "avatar-efficiency");
  if (path.resolve(process.execPath) !== path.resolve(exe)) {
    fs.copyFileSync(process.execPath, exe);
    if (!WIN) fs.chmodSync(exe, 0o755);
    log(`설치: ${exe}`);
  } else {
    log(`설치 위치에서 실행 중: ${exe}`);
  }

  // 2. 데이터 폴더 + 설정 + 아바타 템플릿
  fs.mkdirSync(DATA_DIR, { recursive: true });
  const cfgPath = path.join(DATA_DIR, "config.json");
  if (!fs.existsSync(cfgPath)) {
    fs.writeFileSync(cfgPath, JSON.stringify({ serverUrl: "http://127.0.0.1:18220", throttleHours: 4, model: "haiku" }, null, 2));
    log(`설정 생성: ${cfgPath}`);
  }
  const avatarsPath = path.join(DATA_DIR, "avatars.json");
  if (!fs.existsSync(avatarsPath)) {
    let loginId = "UNKNOWN";
    try {
      loginId = getWindowsLoginId();
    } catch (e) {
      log(`로그인 ID 감지 실패(${e.message}) — avatars.json에서 직접 수정 필요`);
    }
    const tpl = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, "avatars.sample.json"), "utf8")); // pkg asset
    tpl.avatars[0].loginId = loginId;
    fs.writeFileSync(avatarsPath, JSON.stringify(tpl, null, 2));
    log(`아바타 템플릿 생성: ${avatarsPath} (loginId=${loginId})`);
  }

  // 3. SessionStart hook 자동 병합 (~/.claude/settings.json, 백업 후)
  const settingsPath = path.join(os.homedir(), ".claude", "settings.json");
  fs.mkdirSync(path.dirname(settingsPath), { recursive: true });
  let settings = {};
  if (fs.existsSync(settingsPath)) {
    settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
    fs.copyFileSync(settingsPath, settingsPath + ".bak-" + Date.now());
  }
  settings.hooks = settings.hooks || {};
  settings.hooks.SessionStart = settings.hooks.SessionStart || [];
  const already = JSON.stringify(settings.hooks.SessionStart).includes("avatar-efficiency");
  if (!already) {
    settings.hooks.SessionStart.push({
      matcher: "startup",
      hooks: [{ type: "command", command: `"${exe}" hook` }],
    });
    fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2));
    log(`hook 등록: ${settingsPath}`);
  } else {
    log("hook 이미 등록됨 — 스킵");
  }

  // 4. 작업 스케줄러 (Windows) — hook이 schtasks 경유로 env 상속을 끊는다
  if (WIN) {
    const r = spawnSync("schtasks", ["/Create", "/F", "/TN", TASK_NAME, "/SC", "ONCE", "/ST", "00:00", "/TR", `"${exe}" sweep`], { encoding: "utf8" });
    log(r.status === 0 ? `작업 스케줄러 등록: ${TASK_NAME}` : "schtasks 등록 실패 — hook이 직접 스폰 폴백으로 동작");
  }

  console.log(`\n완료. 다음 한 가지만 하면 됩니다:
  ${avatarsPath}
  → 역할·업무 script를 본인 업무로 채우기 (매칭 정확도의 전부)

  이후 클로드를 켤 때마다 자동으로 지난 세션들이 분석됩니다.
  집계 서버가 다른 곳이면 ${path.join(DATA_DIR, "config.json")} 의 serverUrl 수정.
  (로컬 서버 직접 운영 시: "${exe}" server)`);
}

// ── hook: SessionStart에서 호출 — 즉시 리턴, 스위퍼는 분리 실행 ─────────
function hookTrigger() {
  if (process.env.SWEEPER_CHILD === "1") return; // 훅 재귀 가드

  if (WIN) {
    // 1순위: 작업 스케줄러 경유 (세션 env 비상속)
    const r = spawnSync("schtasks", ["/Run", "/TN", TASK_NAME], { timeout: 3000 });
    if (r.status === 0) return;
  }
  // 폴백: 직접 detach 스폰 — CLAUDE* env 스크럽해서 넘긴다
  const env = {};
  for (const [k, v] of Object.entries(process.env)) if (!/^CLAUDE/i.test(k)) env[k] = v;
  const child = spawn(process.execPath, ["sweep"], { detached: true, stdio: "ignore", env });
  child.unref();
}

module.exports = { runSetup, hookTrigger, isWsl, installDir };
