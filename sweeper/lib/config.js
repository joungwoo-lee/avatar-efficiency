const fs = require("fs");
const path = require("path");

const REPO_ROOT = path.resolve(__dirname, "..", "..");

function expand(v) {
  if (typeof v !== "string") return v;
  return v
    .replace(/%USERPROFILE%/g, process.env.USERPROFILE || process.env.HOME || "")
    .replace(/<repo>/g, REPO_ROOT);
}

function loadConfig() {
  const raw = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, "config.json"), "utf8"));
  const cfg = {};
  for (const [k, v] of Object.entries(raw)) cfg[k] = expand(v);
  cfg.excerpt = raw.excerpt;

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

module.exports = { loadConfig, encodeCwd, REPO_ROOT };
