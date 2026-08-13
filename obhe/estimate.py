# -*- coding: utf-8 -*-
"""OBHE CLI — Claude Code trajectory 기반 Human Equivalent Effort.

여러 trajectory 입력 시 산출물(수정 경로) 겹침으로 이어지는 세션끼리
job 그룹으로 묶고(LLM 미사용), 그룹마다 net artifact → OBHE를 낸다.

사용법:
  # trajectory에서 그룹핑 → 산출물 확정 → LLM 1회/그룹(기본 SimLLM) → 시간 계산
  python estimate.py --trajectory s1.jsonl s2.jsonl --base <commit>
                     [--repo <repo>] [--end <commit>] [--min-common 1]
                     [--ai-hours 2] [--rates rates.json] [--json out.json]

  # 로컬 층만 실행해 그룹핑 + Artifact Manifest 확인 (LLM 미사용)
  python estimate.py --trajectory s1.jsonl --base <commit> --manifest-only

--repo 생략 시 그룹 첫 세션의 cwd를 프로젝트 경로로 사용한다.
--base/--end는 모든 그룹에 동일 적용되므로, 그룹이 여러 개면 그룹별로
따로 실행하는 것을 권장한다.
"""
import argparse
import io
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fsstate
    import gitstate
    import manifest as manifest_mod
    import rate_engine
    import trajectory
    import workload
    from cursor_llm import CursorProxyLLM
    from sim_llm import SimLLM
else:
    from . import fsstate, gitstate, rate_engine, trajectory, workload
    from . import manifest as manifest_mod
    from .cursor_llm import CursorProxyLLM
    from .sim_llm import SimLLM


def _fmt_h(minutes):
    return f"{minutes / 60.0:5.1f}h"


def _union(sessions, key):
    out = set()
    for s in sessions:
        out |= s[key]
    return out


def build_group_manifest(job_id, group, repo, base, end,
                         claimed_elsewhere=frozenset(), exclusive=False):
    """로컬 결정론 층: 세션 그룹 → Git → Artifact Manifest (LLM 미사용).

    claimed_elsewhere: 다른 job 그룹이 직접 건드린 repo상대경로 —
      이 job의 net diff에서 제거해 job 간 이중계산을 막는다.
    exclusive: 다중 job 실행 시 True — 귀속 불가 GIT_NET을 unresolved로.
    """
    sessions = group["sessions"]
    evidence = group.get("grouping_evidence", [])

    # 증거 우선순위 (§3.4): base commit + 로컬 .git이 있으면 Git 검증,
    # 없으면 trajectory 편집 기록 + 현재 filesystem 대조 (§7 — Git 필수 아님)
    use_git = bool(base) and (Path(repo) / ".git").exists()
    if use_git:
        try:
            states = gitstate.resolve_states(repo, base, end)
        except gitstate.GitStateError as e:
            states = {"base": None, "end": None, "recovery": "UNRECOVERABLE", "note": str(e)}
        if states["recovery"] == "UNRECOVERABLE":
            return manifest_mod.build_manifest(job_id, sessions, repo, states, [], [], [],
                                               grouping_evidence=evidence)
        changed = {p: s for p, s in
                   gitstate.net_diff(repo, states["base"], states["end"]).items()
                   if p not in claimed_elsewhere}
        artifacts, transient, unresolved = gitstate.classify(
            _union(sessions, "direct_paths"), _union(sessions, "bash_candidate_paths"),
            changed, repo, git_net_to_unresolved=exclusive)
        gitstate.attach_contents(artifacts, repo, states["base"], states["end"])
    else:
        states, artifacts, transient, unresolved = fsstate.resolve_without_git(sessions, repo)
    return manifest_mod.build_manifest(job_id, sessions, repo, states, artifacts,
                                       transient, unresolved, grouping_evidence=evidence)


def render_report(report, man):
    out = ["=" * 78, f"OBHE 리포트 — {man['job_id']}  (세션 {len(man['sessions'])}개)", "=" * 78]
    if man["grouping_evidence"]:
        out.append("\n[Session Grouping — 산출물 겹침 근거]")
        for ev in man["grouping_evidence"]:
            out.append(f"  {ev['sessions'][0]} ↔ {ev['sessions'][1]}: "
                       + ", ".join(ev["common_paths"][:3])
                       + (" 외" if len(ev["common_paths"]) > 3 else ""))
    out.append(f"\n[Artifact Manifest]  base {man['base_state']} → end {man['end_state']}"
               f"  (복원 상태: {man['recovery']})")
    for a in man["artifacts"]:
        out.append(f"  {a['status']}  {a['path']:<42} {a['attribution']:<11} conf {a['confidence']}")
    for p in man["excluded_transient_paths"]:
        out.append(f"  -  {p:<42} TRANSIENT   (최종 산출물 제외)")

    out.append("\n[Completed Outcomes]")
    for o in report["completed_outcomes"]:
        out.append(f"  {o['outcome_id']}: {o['outcome']}  — 근거: {o['evidence']}")

    out.append("\n[Human Action Ledger]")
    out.append(f"  {'action':<20} {'unit':<15} {'양':>7} {'cx':<7} {'P50':>7} {'P80':>7}  근거")
    for r in report["priced"]["rows"]:
        out.append(f"  {r['action']:<20} {r['workload_unit']:<15} {r['workload']:>7g}"
                   f" {r['complexity']:<7} {_fmt_h(r['p50_min']):>7} {_fmt_h(r['p80_min']):>7}"
                   f"  {r['evidence'][:36]}")
    p = report["priced"]
    out.append(f"  {'-' * 74}")
    out.append(f"  작업 소계        P50 {_fmt_h(p['work_p50_min'])} / P80 {_fmt_h(p['work_p80_min'])}")
    out.append(f"  Human Rework     P50 {_fmt_h(p['rework_p50_min'])} / P80 {_fmt_h(p['rework_p80_min'])}")

    out.append(f"\n[Human Equivalent Effort]")
    out.append(f"  RHE: P50 {report['rhe_p50_hours']}h / P80 {report['rhe_p80_hours']}h"
               f"   (rate confidence {report['rate_confidence']},"
               f" 자동승인 {'가' if report['auto_approved'] else '불가'})")
    if "ai_actual_hours" in report:
        out.append(f"  AI Actual {report['ai_actual_hours']}h → 현실화 효율 {report['realized_efficiency']}x")

    if report["excluded_outputs"]:
        out.append("\n[Excluded Outputs]")
        for e in report["excluded_outputs"]:
            out.append(f"  - {e.get('item', '')}: {e.get('reason', '')}")
    if report["measurement_required"]:
        out.append("\n[Measurement Required]")
        for mr in report["measurement_required"]:
            out.append(f"  - {mr.get('item', '')}: {mr.get('needed_info', '')}")
    for w in report["warnings"]:
        out.append(f"  경고: {w}")
    out.append("=" * 78)
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Trajectory 기반 Human Equivalent Effort 추산")
    ap.add_argument("--trajectory", nargs="+", required=True, help="Claude Code JSONL 파일들")
    ap.add_argument("--repo", default=None,
                    help="Git repository 경로 (생략 시 그룹 첫 세션의 cwd)")
    ap.add_argument("--base", default=None,
                    help="작업 시작 commit (Git 검증용 — 없으면 trajectory+filesystem 증거로 복원)")
    ap.add_argument("--end", default=None, help="작업 종료 commit (미지정 시 현재 working tree)")
    ap.add_argument("--min-common", type=int, default=1,
                    help="같은 job으로 묶는 최소 공통 산출물 경로 수 (기본 1)")
    ap.add_argument("--llm", choices=["cursor", "sim"], default="cursor",
                    help="cursor: cursor-proxy(기본, OBHE_LLM_BASE/MODEL env), sim: 데모 시뮬레이터")
    ap.add_argument("--rates", default=None, help="Human Rate Table JSON (기본: obhe/rates.json)")
    ap.add_argument("--ai-hours", type=float, default=None, help="AI Actual Effort (시간)")
    ap.add_argument("--manifest-only", action="store_true", help="로컬 층 결과만 출력 (LLM 미사용)")
    ap.add_argument("--json", dest="json_out", default=None, help="결과 JSON 저장 경로")
    args = ap.parse_args(argv)

    sessions = [trajectory.parse_trajectory(f) for f in args.trajectory]
    groups = trajectory.group_by_artifacts(sessions, min_common=args.min_common)
    print(f"세션 {len(sessions)}개 → 산출물 겹침 기준 job {len(groups)}개")

    rates = rate_engine.load_rates(args.rates)
    results, failed = [], 0
    multi = len(groups) > 1
    for k, group in enumerate(groups, 1):
        repo = args.repo or group["sessions"][0]["cwd"] or "."
        # 다른 job이 직접 건드린 경로는 이 job의 diff에서 제거 (이중계산 방지)
        claimed = set()
        for other in groups:
            if other is not group:
                for p in (_union(other["sessions"], "direct_paths")
                          | _union(other["sessions"], "bash_candidate_paths")):
                    rel = gitstate.to_repo_relative(p, repo)
                    if rel:
                        claimed.add(rel)
        man = build_group_manifest(f"job-{k}", group, repo, args.base, args.end,
                                   claimed_elsewhere=claimed, exclusive=multi)

        if args.manifest_only or man["recovery"] == "UNRECOVERABLE":
            print(json.dumps(man, ensure_ascii=False, indent=2, default=str))
            if man["recovery"] == "UNRECOVERABLE":
                print(f"\n[{man['job_id']}] {man['recovery_note']}"
                      f" — Human Effort 계산을 진행하지 않음 (§5.3/§14).")
                failed += 1
            results.append({"manifest": man, "report": None})
            continue

        llm = SimLLM() if args.llm == "sim" else CursorProxyLLM()
        estimation = workload.estimate_workload(man, llm, rates)
        report = rate_engine.build_report(man, estimation, rates, ai_actual_hours=args.ai_hours)
        print(render_report(report, man))
        results.append({"manifest": man, "report": report})

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 저장: {args.json_out}")
    return 1 if failed and not args.manifest_only else 0


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.exit(main())
