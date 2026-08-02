#!/usr/bin/env node
// 단일 바이너리 CLI. 인자 없이 실행 = setup (원샷 설치).
const cmd = process.argv[2] || "setup";
if (process.argv.includes("--force")) process.env.AE_FORCE = "1";

switch (cmd) {
  case "setup":
    require("../sweeper/lib/setup").runSetup();
    break;
  case "hook":
    require("../sweeper/lib/setup").hookTrigger();
    break;
  case "sweep":
    require("../sweeper/sweep").main().catch((e) => {
      console.error("[sweep] fatal:", e);
      process.exit(1);
    });
    break;
  case "server":
    require("../server/server").start();
    break;
  case "version":
    console.log(require("../package.json").version);
    break;
  default:
    console.log("usage: avatar-efficiency [setup|sweep [--force]|server|hook|version]");
    process.exit(cmd === "help" ? 0 : 1);
}
