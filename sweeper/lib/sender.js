const http = require("http");
const https = require("https");
const { URL } = require("url");

// fire-and-forget POST. 짧은 타임아웃, 실패해도 throw만 — 매칭 작업은 계속된다.
function postRecord(serverUrl, record, timeoutMs = 3000) {
  return new Promise((resolve, reject) => {
    const u = new URL("/records", serverUrl);
    const mod = u.protocol === "https:" ? https : http;
    const body = JSON.stringify(record);
    const req = mod.request(
      u,
      { method: "POST", headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) }, timeout: timeoutMs },
      (res) => {
        res.resume();
        res.statusCode >= 200 && res.statusCode < 300
          ? resolve()
          : reject(new Error("server status " + res.statusCode));
      }
    );
    req.on("timeout", () => req.destroy(new Error("send timeout")));
    req.on("error", reject);
    req.end(body);
  });
}

// 미발송분(at-least-once). 재발송은 Haiku 재호출이 아니므로 토큰 비용 0.
async function sendPending(cfg, ledger, log) {
  if (cfg.noSend) return;
  for (const { uuid, record } of ledger.pending()) {
    try {
      await postRecord(cfg.serverUrl, record);
      ledger.markSent(uuid);
      log(`sent ${uuid}`);
    } catch (e) {
      log(`send failed ${uuid}: ${e.message} (다음 스윕 재시도)`);
    }
  }
}

module.exports = { postRecord, sendPending };
