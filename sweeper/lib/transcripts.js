const fs = require("fs");
const path = require("path");
const { encodeCwd } = require("./config");

function safeParse(line) {
  try {
    return JSON.parse(line);
  } catch (_) {
    return null;
  }
}

function readRecords(file, fromOffset = 0) {
  const buf = fs.readFileSync(file);
  const text = buf.slice(fromOffset).toString("utf8");
  return {
    records: text.split("\n").filter((l) => l.trim()).map(safeParse).filter(Boolean),
    endOffset: buf.length,
  };
}

function textOf(msg) {
  const c = msg && msg.content;
  if (typeof c === "string") return c;
  if (Array.isArray(c))
    return c.filter((p) => p && p.type === "text" && p.text).map((p) => p.text).join("\n");
  return "";
}

function isRealTurn(rec, role) {
  if (rec.type !== role) return false;
  return textOf(rec.message).trim().length > 0;
}

// 원장 오프셋 이후 "실질 턴"(user+assistant 쌍) 존재 여부 — mtime만으론 재매칭하지 않는다
function hasNewTurns(file, fromOffset) {
  const { records } = readRecords(file, fromOffset);
  return records.some((r) => isRealTurn(r, "user")) && records.some((r) => isRealTurn(r, "assistant"));
}

// 처리 후보 스캔. 제외: 진행 중(mtime 최근), 자기 세션, 스위퍼 전용 cwd 폴더(자기 꼬리 재귀 차단)
function scanCandidates(cfg, ledger, sweepStartMs) {
  const excludedDir = encodeCwd(cfg.analysisCwd);
  const idleCutoff = sweepStartMs - cfg.idleGuardMinutes * 60 * 1000;
  const staleMs = cfg.inProgressStaleHours * 3600 * 1000;
  const selfUuid = process.env.AE_SELF_SESSION_UUID || "";
  const out = [];
  if (!fs.existsSync(cfg.projectsDir)) return out;
  for (const dir of fs.readdirSync(cfg.projectsDir)) {
    if (dir === excludedDir) continue;
    const full = path.join(cfg.projectsDir, dir);
    let stat;
    try {
      stat = fs.statSync(full);
    } catch (_) {
      continue;
    }
    if (!stat.isDirectory()) continue;
    for (const f of fs.readdirSync(full)) {
      if (!f.endsWith(".jsonl")) continue;
      const uuid = f.slice(0, -6);
      if (uuid === selfUuid) continue;
      const file = path.join(full, f);
      const fstat = fs.statSync(file);
      if (fstat.mtimeMs >= idleCutoff) continue; // 진행 중 세션 제외 (자기 자신 포함)
      const entry = ledger.get(uuid);
      let offset = 0;
      if (entry) {
        if (entry.status === "in-progress" && sweepStartMs - entry.ts < staleMs) continue; // 크래시 재시도 유예
        if (entry.status === "done") {
          if (!hasNewTurns(file, entry.offset)) continue; // 책갈피 이후 실질 턴 없으면 스킵
          offset = entry.offset;
        }
      }
      out.push({ uuid, file, dir, offset, prevRecord: entry && entry.record });
    }
  }
  return out;
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function extractExcerpt(records, exCfg) {
  const firstUser = records.find((r) => isRealTurn(r, "user"));
  const msgs = records.filter((r) => isRealTurn(r, "user") || isRealTurn(r, "assistant"));
  const last = msgs.slice(-exCfg.lastMessages);
  const summaries = records.filter((r) => r.type === "summary" && r.summary).slice(-2);
  return {
    firstPrompt: firstUser ? truncate(textOf(firstUser.message), exCfg.firstPromptMaxChars) : "",
    lastMessages: last.map((r) => ({ role: r.type, text: truncate(textOf(r.message), exCfg.maxChars) })),
    summaries: summaries.map((r) => r.summary),
  };
}

// 활동 시간(시간 단위): 턴 간격 gapCap 초과 gap 제외 — 방치 시간 포함하면 η가 부당하게 낮아짐
function activeHours(records, gapCapMinutes) {
  const ts = records
    .filter((r) => r.timestamp && (r.type === "user" || r.type === "assistant"))
    .map((r) => new Date(r.timestamp).getTime())
    .filter((t) => Number.isFinite(t))
    .sort((a, b) => a - b);
  const cap = gapCapMinutes * 60 * 1000;
  let sum = 0;
  for (let i = 1; i < ts.length; i++) {
    const d = ts[i] - ts[i - 1];
    if (d > 0 && d <= cap) sum += d;
  }
  return sum / 3600000;
}

function sumTokens(records) {
  const tot = { input: 0, output: 0, cacheRead: 0, cacheCreation: 0 };
  for (const r of records) {
    const u = r.message && r.message.usage;
    if (!u) continue;
    tot.input += u.input_tokens || 0;
    tot.output += u.output_tokens || 0;
    tot.cacheRead += u.cache_read_input_tokens || 0;
    tot.cacheCreation += u.cache_creation_input_tokens || 0;
  }
  return tot;
}

module.exports = { readRecords, scanCandidates, extractExcerpt, activeHours, sumTokens, hasNewTurns };
