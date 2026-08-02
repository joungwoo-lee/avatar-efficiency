const { execFileSync } = require("child_process");
const fs = require("fs");

// Windows 로그인 계정 ID. WSL 안에서도 interop으로 Windows 값을 읽는다 (Linux 계정명 아님).
function getWindowsLoginId() {
  if (process.platform === "win32") {
    if (process.env.USERNAME) return process.env.USERNAME;
    const who = execFileSync("whoami", { encoding: "utf8" }).trim();
    return who.includes("\\") ? who.split("\\").pop() : who;
  }
  // WSL 감지
  let isWsl = false;
  try {
    isWsl = /microsoft/i.test(fs.readFileSync("/proc/version", "utf8"));
  } catch (_) {}
  if (isWsl) {
    // 전체 경로 호출: PATH 공유가 꺼져 있어도 동작
    const out = execFileSync("/mnt/c/Windows/System32/cmd.exe", ["/c", "echo %USERNAME%"], {
      encoding: "utf8",
    }).trim();
    if (!out || out === "%USERNAME%") {
      throw new Error("WSL interop disabled ([interop] enabled=false) — cannot read Windows login id");
    }
    return out;
  }
  throw new Error("unsupported platform for Windows login id: " + process.platform);
}

module.exports = { getWindowsLoginId };
