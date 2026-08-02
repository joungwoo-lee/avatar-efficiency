const fs = require("fs");
const os = require("os");
const path = require("path");

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const IS_PKG = !!process.pkg; // pkg 스냅샷 안에서는 __dirname이 가상경로 — 쓰기 가능한 경로는 전부 홈 기준
const DATA_DIR = path.join(os.homedir(), ".sweeper");

function defaults() {
  return {
    projectsDir: path.join(os.homedir(), ".claude", "projects"),
    outboxPath: path.join(DATA_DIR, "outbox.jsonl"),
    lockPath: path.join(DATA_DIR, "sweep.lock"),
    analysisCwd: path.join(DATA_DIR, "analysis"),
    avatarsPath: IS_PKG ? path.join(DATA_DIR, "avatars.json") : path.join(REPO_ROOT, "avatars.sample.json"),
    serverUrl: "http://127.0.0.1:18220",
    throttleHours: 4,
    idleGuardMinutes: 30,
    gapCapMinutes: 15,
    inProgressStaleHours: 1,
    minSessionHours: 0.1,
    model: "haiku",
    claudeCmd: "claude",
    excerpt: { lastMessages: 12, maxChars: 400, firstPromptMaxChars: 1500 },
  };
}

function loadConfig() {
  const cfg = defaults();
  // 사용자 오버라이드: ~/.sweeper/config.json (setup이 생성, 실디스크 — pkg 스냅샷 아님)
  const userPath = path.join(DATA_DIR, "config.json");
  if (fs.existsSync(userPath)) {
    try {
      Object.assign(cfg, JSON.parse(fs.readFileSync(userPath, "utf8")));
    } catch (e) {
      console.error(`[config] ${userPath} parse failed: ${e.message} — defaults 사용`);
    }
  }
  const env = process.env;
  if (env.AE_PROJECTS_DIR) cfg.projectsDir = env.AE_PROJECTS_DIR;
  if (env.AE_OUTBOX_PATH) cfg.outboxPath = env.AE_OUTBOX_PATH;
  if (env.AE_LOCK_PATH) cfg.lockPath = env.AE_LOCK_PATH;
  if (env.AE_ANALYSIS_CWD) cfg.analysisCwd = env.AE_ANALYSIS_CWD;
  if (env.AE_AVATARS_PATH) cfg.avatarsPath = env.AE_AVATARS_PATH;
  if (env.AE_SERVER_URL) cfg.serverUrl = env.AE_SERVER_URL;
  if (env.AE_THROTTLE_HOURS) cfg.throttleHours = Number(env.AE_THROTTLE_HOURS);
  if (env.AE_IDLE_GUARD_MINUTES) cfg.idleGuardMinutes = Number(env.AE_IDLE_GUARD_MINUTES);
  cfg.force = env.AE_FORCE === "1";
  cfg.noSend = env.AE_NO_SEND === "1";
  return cfg;
}

function encodeCwd(p) {
  return String(p).replace(/[^a-zA-Z0-9]/g, "-");
}

module.exports = { loadConfig, encodeCwd, REPO_ROOT, DATA_DIR, IS_PKG, defaults };
