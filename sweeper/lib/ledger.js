const fs = require("fs");
const path = require("path");

// outbox.jsonl 단일 파일 = 처리 원장 겸 발송 스풀.
// 레코드 종류: {t:"proc", uuid, status:"in-progress"|"done", offset, record?, ts}
//             {t:"sent", uuid, ts}
//             {t:"lastSweep", ts}
class Ledger {
  constructor(filePath) {
    this.path = filePath;
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    this.entries = new Map(); // uuid -> {status, offset, record, sent, ts}
    this.lastSweep = 0;
    this._load();
  }

  _load() {
    if (!fs.existsSync(this.path)) return;
    for (const line of fs.readFileSync(this.path, "utf8").split("\n")) {
      if (!line.trim()) continue;
      let obj;
      try {
        obj = JSON.parse(line);
      } catch (_) {
        continue;
      }
      if (obj.t === "lastSweep") {
        this.lastSweep = obj.ts;
      } else if (obj.t === "proc") {
        const prev = this.entries.get(obj.uuid) || {};
        this.entries.set(obj.uuid, {
          status: obj.status,
          offset: obj.offset,
          record: obj.record !== undefined ? obj.record : prev.record,
          sent: obj.status === "done" ? false : prev.sent,
          ts: obj.ts,
        });
      } else if (obj.t === "sent") {
        const e = this.entries.get(obj.uuid);
        if (e) e.sent = true;
      }
    }
  }

  _append(obj) {
    fs.appendFileSync(this.path, JSON.stringify(obj) + "\n");
  }

  get(uuid) {
    return this.entries.get(uuid);
  }

  markInProgress(uuid, offset) {
    const e = { status: "in-progress", offset, ts: Date.now() };
    this.entries.set(uuid, { ...(this.entries.get(uuid) || {}), ...e });
    this._append({ t: "proc", uuid, status: "in-progress", offset, ts: e.ts });
  }

  finalize(uuid, offset, record) {
    const e = { status: "done", offset, record, sent: false, ts: Date.now() };
    this.entries.set(uuid, e);
    this._append({ t: "proc", uuid, status: "done", offset, record, ts: e.ts });
  }

  markSent(uuid) {
    const e = this.entries.get(uuid);
    if (e) e.sent = true;
    this._append({ t: "sent", uuid, ts: Date.now() });
  }

  setLastSweep() {
    this.lastSweep = Date.now();
    this._append({ t: "lastSweep", ts: this.lastSweep });
  }

  pending() {
    const out = [];
    for (const [uuid, e] of this.entries) {
      if (e.status === "done" && e.record && e.record.taskId && !e.sent) out.push({ uuid, record: e.record });
    }
    return out;
  }
}

module.exports = { Ledger };
