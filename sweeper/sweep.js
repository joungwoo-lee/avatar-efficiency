#!/usr/bin/env node
// SessionStart 스위퍼 — 미처리 transcript를 골라 Haiku 매칭 + η 산정 후 집계 서버로 비동기 송출.
// 설계: docs/{session-matching-design,efficiency-metrics-design}.md
const fs = require("fs");
const path = require("path");
const { loadConfig } = require("./lib/config");
const { getWindowsLoginId } = require("./lib/login-id");
const { Ledger } = require("./lib/ledger");
const { scanCandidates, readRecords, extractExcerpt, activeHours, sumTokens } = require("./lib/transcripts");
const { matchSession } = require("./lib/haiku");
const { sendPending } = require("./lib/sender");

const log = (m) => console.log(`[sweep ${new Date().toISOString()}] ${m}`);

// 락파일 단일 인스턴스 (30분 지나면 stale 간주)
function acquireLock(lockPath) {
  fs.mkdirSync(path.dirname(lockPath), { recursive: true });
  try {
    fs.writeFileSync(lockPath, JSON.stringify({ pid: process.pid, ts: Date.now() }), { flag: "wx" });
    return true;
  } catch (_) {
    try {
      const prev = JSON.parse(fs.readFileSync(lockPath, "utf8"));
      if (Date.now() - prev.ts > 30 * 60 * 1000) {
        fs.writeFileSync(lockPath, JSON.stringify({ pid: process.pid, ts: Date.now() }));
        return true;
      }
    } catch (_) {}
    return false;
  }
}

async function main() {
  const cfg = loadConfig();
  const sweepStart = Date.now();

  // 실행 순서 고정: 락 획득 → 스로틀 확인 → 원장 읽기
  if (!acquireLock(cfg.lockPath)) {
    log("another sweeper holds the lock — exit");
    return;
  }
  try {
    const ledger = new Ledger(cfg.outboxPath);
    if (!cfg.force && ledger.lastSweep && sweepStart - ledger.lastSweep < cfg.throttleHours * 3600 * 1000) {
      log(`throttled (last sweep ${new Date(ledger.lastSweep).toISOString()}) — exit`);
      return;
    }

    const loginId = getWindowsLoginId();
    const avatarsDoc = JSON.parse(fs.readFileSync(cfg.avatarsPath, "utf8"));
    const avatar = avatarsDoc.avatars.find((a) => a.loginId.toLowerCase() === loginId.toLowerCase());
    if (!avatar) {
      log(`no avatar for loginId=${loginId} — nothing to do`);
      return;
    }
    log(`loginId=${loginId} → avatar=${avatar.avatarId}`);

    const candidates = scanCandidates(cfg, ledger, sweepStart);
    log(`${candidates.length} candidate transcript(s)`);

    for (const cand of candidates) {
      const { records, endOffset } = readRecords(cand.file, 0);
      const excerpt = extractExcerpt(records, cfg.excerpt);
      if (!excerpt.firstPrompt && excerpt.lastMessages.length === 0) {
        ledger.finalize(cand.uuid, endOffset, null); // 내용 없는 파일 — 원장만 마감
        continue;
      }

      ledger.markInProgress(cand.uuid, cand.offset); // Haiku 호출 직전 마킹 (크래시 낭비 유계)
      let match;
      try {
        match = matchSession(cfg, avatar, excerpt);
      } catch (e) {
        log(`match failed ${cand.uuid}: ${e.message} (in-progress로 남김 — stale 후 재시도)`);
        continue;
      }

      const hours = Math.max(activeHours(records, cfg.gapCapMinutes), cfg.minSessionHours);
      // 미매칭도 버리지 않는다: taskId="misc"(기타 업무)로 workSummary를 달아 송신 — 신규 업무 제안 재료
      const taskId = match.taskId && match.taskId !== "null" ? match.taskId : "misc";
      const record = {
        sessionUuid: cand.uuid,
        loginId,
        avatarId: avatar.avatarId,
        roleId: taskId === "misc" ? null : match.roleId,
        taskId,
        workSummary: match.workSummary,
        confidence: match.confidence,
        manualHoursEst: match.manualHoursEst,
        quality: match.quality,
        sessionHoursActive: Math.round(hours * 100) / 100,
        eta: Math.round(((match.manualHoursEst / hours) * match.quality) * 100) / 100,
        tokens: sumTokens(records),
        cwd: cand.dir,
        matchedAt: new Date().toISOString(),
        rationale: match.rationale,
        schemaVer: 1,
      };
      ledger.finalize(cand.uuid, endOffset, record);
      log(`${cand.uuid} → ${taskId === "misc" ? "misc(기타)" : `${match.roleId}/${taskId}`} η=${record.eta}`);
    }

    await sendPending(cfg, ledger, log);
    ledger.setLastSweep();
    log("sweep done");
  } finally {
    try {
      fs.unlinkSync(cfg.lockPath);
    } catch (_) {}
  }
}

if (require.main === module) {
  main().catch((e) => {
    console.error("[sweep] fatal:", e);
    process.exit(1);
  });
}

module.exports = { main };
