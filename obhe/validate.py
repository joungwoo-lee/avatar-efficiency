# -*- coding: utf-8 -*-
"""trajectory 파서 검증 도구 — 추정 없이 추출 결과 요약만 출력.

실제 trajectory를 OBHE에 넣기 전에 파서가 무엇을 뽑아내는지 확인한다.
기본은 통계만 출력 (파일 내용·요청 본문 비노출). --show-requests로 요청 머리만 표시.

사용법:
  python validate.py --trajectory s1.jsonl s2.jsonl [--show-requests] [--min-common 1]
"""
import argparse
import collections
import io
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import trajectory
else:
    from . import trajectory


def main(argv=None):
    ap = argparse.ArgumentParser(description="trajectory 파서 검증 (추정 미수행)")
    ap.add_argument("--trajectory", nargs="+", required=True)
    ap.add_argument("--show-requests", action="store_true", help="task request 앞 60자 표시")
    ap.add_argument("--min-common", type=int, default=1)
    args = ap.parse_args(argv)

    sessions = []
    for f in args.trajectory:
        s = trajectory.parse_trajectory(f)
        sessions.append(s)
        ops = collections.Counter(op["tool"] for op in s["file_ops"])
        ts = (s["timestamps"][0][:19] + " ~ " + s["timestamps"][-1][:19]) if s["timestamps"] else "-"
        print(f"[{Path(f).name}]")
        print(f"  session_id : {s['session_id'] or '(없음)'}")
        print(f"  cwd        : {s['cwd'] or '(없음)'}")
        print(f"  기간        : {ts}")
        print(f"  직접 수정 경로: {len(s['direct_paths'])}개, file_ops: {dict(ops) or '없음'}")
        print(f"  shell 후보 경로: {len(s['bash_candidate_paths'])}개, git 명령: {len(s['git_commands'])}건")
        print(f"  task request: {len(s['task_requests'])}건")
        if args.show_requests:
            for i, t in enumerate(s["task_requests"][:10]):
                print(f"    {i + 1}. ({len(t)}자) {t[:60]!r}")

    if len(sessions) > 1:
        groups = trajectory.group_by_artifacts(sessions, min_common=args.min_common)
        print(f"\n그룹핑: 세션 {len(sessions)}개 → job {len(groups)}개")
        for k, g in enumerate(groups, 1):
            ids = [s["session_id"] or Path(s["file"]).name for s in g["sessions"]]
            print(f"  job-{k}: {ids}")
            for ev in g["grouping_evidence"]:
                print(f"    근거: {ev['sessions'][0]} ↔ {ev['sessions'][1]} 공통 {len(ev['common_paths'])}개")
    return 0


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.exit(main())
