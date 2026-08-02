#!/usr/bin/env node
// 집계 서버 — η 레코드 수신(uuid 멱등 upsert), 아바타 효율 E·토큰 가치(V/C/ROI) 산출.
// 설계: efficiency-metrics-design.md §3~4
const http = require("http");
const fs = require("fs");
const path = require("path");

const PORT = Number(process.env.AE_SERVER_PORT || 18220);
const DATA = process.env.AE_RECORDS_PATH || path.join(__dirname, "data", "records.jsonl");
const AVATARS = process.env.AE_AVATARS_PATH || path.join(__dirname, "..", "avatars.sample.json");
const VALUE = JSON.parse(fs.readFileSync(path.join(__dirname, "value-config.json"), "utf8"));

fs.mkdirSync(path.dirname(DATA), { recursive: true });

function loadRecords() {
  const map = new Map(); // sessionUuid → record (last wins = upsert)
  if (fs.existsSync(DATA)) {
    for (const line of fs.readFileSync(DATA, "utf8").split("\n")) {
      if (!line.trim()) continue;
      try {
        const r = JSON.parse(line);
        if (r.sessionUuid) map.set(r.sessionUuid, r);
      } catch (_) {}
    }
  }
  return map;
}

function tokenCostKRW(tokens) {
  const p = VALUE.pricingPerMTokUSD;
  const usd =
    ((tokens.input || 0) * p.input +
      (tokens.output || 0) * p.output +
      (tokens.cacheRead || 0) * p.cacheRead +
      (tokens.cacheCreation || 0) * p.cacheCreation) /
    1e6;
  return usd * VALUE.usdToKrw;
}

// E(아바타) = Σ w_r × [ Σ w_t × η_t ], 세션 없는 업무 η=1.0. 가중합은 서버 책임.
function computeEfficiency(avatar, records) {
  const byTask = new Map();
  for (const r of records.values()) {
    if (r.avatarId !== avatar.avatarId || !r.taskId) continue;
    if (!byTask.has(r.taskId)) byTask.set(r.taskId, []);
    byTask.get(r.taskId).push(r);
  }
  let E = 0;
  const roles = [];
  let totalV = 0, totalC = 0, totalTokens = 0;
  for (const role of avatar.roles) {
    let Er = 0;
    const tasks = [];
    for (const task of role.tasks) {
      const recs = byTask.get(task.id) || [];
      const eta = recs.length ? recs.reduce((s, r) => s + r.eta, 0) / recs.length : 1.0;
      Er += task.weight * eta;
      for (const r of recs) {
        const V =
          r.manualHoursEst * VALUE.ratePerHour * r.quality -
          r.sessionHoursActive * VALUE.supervisionRatePerHour;
        const C = tokenCostKRW(r.tokens || {});
        totalV += V;
        totalC += C;
        totalTokens += (r.tokens && (r.tokens.input + r.tokens.output)) || 0;
      }
      tasks.push({ taskId: task.id, name: task.name, weight: task.weight, sessions: recs.length, eta: round(eta) });
    }
    E += role.weight * Er;
    roles.push({ roleId: role.id, name: role.name, weight: role.weight, efficiency: round(Er), tasks });
  }
  return {
    avatarId: avatar.avatarId,
    efficiency: round(E),
    roles,
    value: {
      savedValueKRW: Math.round(totalV),
      tokenCostKRW: Math.round(totalC),
      roi: totalC > 0 ? round(totalV / totalC) : null,
      valuePerKTokenKRW: totalTokens > 0 ? Math.round((totalV / totalTokens) * 1000) : null,
      note: "V 절대값은 LLM 추정 기반 — 업무 간·기간 간 상대 비교 지표로 운용",
    },
  };
}

const round = (x) => Math.round(x * 100) / 100;

function json(res, code, obj) {
  const body = JSON.stringify(obj, null, 1);
  res.writeHead(code, { "Content-Type": "application/json" });
  res.end(body);
}

const server = http.createServer((req, res) => {
  if (req.method === "POST" && req.url === "/records") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      try {
        const r = JSON.parse(body);
        if (!r.sessionUuid) return json(res, 400, { error: "sessionUuid required" });
        fs.appendFileSync(DATA, JSON.stringify(r) + "\n"); // fold-on-read = 멱등 upsert
        json(res, 200, { ok: true });
      } catch (e) {
        json(res, 400, { error: e.message });
      }
    });
    return;
  }
  if (req.method === "GET" && req.url.startsWith("/efficiency")) {
    const records = loadRecords();
    const avatarsDoc = JSON.parse(fs.readFileSync(AVATARS, "utf8"));
    const u = new URL(req.url, "http://x");
    const want = u.searchParams.get("avatarId");
    const list = avatarsDoc.avatars
      .filter((a) => !want || a.avatarId === want)
      .map((a) => computeEfficiency(a, records));
    return json(res, 200, { avatars: list });
  }
  if (req.method === "GET" && req.url === "/health") return json(res, 200, { ok: true });
  json(res, 404, { error: "not found" });
});

server.listen(PORT, "127.0.0.1", () => console.log(`[server] listening on 127.0.0.1:${PORT}, data=${DATA}`));
