# -*- coding: utf-8 -*-
"""OBHE CLI — Claude Code trajectory 기반 Human Equivalent Effort.

사용법:
  # trajectory + repo에서 산출물 확정 → LLM 1회(기본 SimLLM) → 시간 계산
  python estimate.py --trajectory s1.jsonl s2.jsonl --repo <repo> --base <commit>
                     [--end <commit>] [--ai-hours 2] [--rates rates.json] [--json out.json]

  # 로컬 층만 실행해 Artifact Manifest 확인 (LLM 미사용)
  python estimate.py --trajectory s1.jsonl --repo <repo> --base <commit> --manifest-only
"""
import argparse
import io
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gitstate
    import manifest as manifest_mod
    import rate_engine
    import trajectory
    import workload
    from sim_llm import SimLLM
else:
    from . import gitstate, rate_engine, trajectory, workload
    from . import manifest as manifest_mod
    from .sim_llm import SimLLM


def _fmt_h(minutes):
    return f"{minutes / 60.0:5.1f}h"


def build_local_manifest(trajectory_files, repo, base, end):
    """로컬 결정론 층: trajectory → Git → Artifact Manifest (LLM 미사용)."""
    sessions = [trajectory.parse_trajectory(f) for f in trajectory_files]
    states = gitstate.resolve_states(repo, base, end)
    if states["recovery"] == "UNRECOVERABLE":
        return manifest_mod.build_manifest("job-1", sessions, repo, states, [], [], [])
    changed = gitstate.net_diff(repo, states["base"], states["end"])
    direct = set().union(*(s["direct_paths"] for s in sessions)) if sessions else set()
    bash = set().union(*(s["bash_candidate_paths"] for s in sessions)) if sessions else set()
    artifacts, transient, unresolved = gitstate.classify(direct, bash, changed, repo)
    gitstate.attach_contents(artifacts, repo, states["base"], states["end"])
    return manifest_mod.build_manifest("job-1", sessions, repo, states, artifacts,
                                       transient, unresolved)


def render_report(report, man):
    out = ["=" * 78, "OBHE — Trajectory 기반 Human Equivalent Effort 리포트", "=" * 78]
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
    ap.add_argument("--repo", required=True, help="작업이 수행된 Git repository 경로")
    ap.add_argument("--base", default=None, help="작업 시작 commit (미지정 시 UNRECOVERABLE)")
    ap.add_argument("--end", default=None, help="작업 종료 commit (미지정 시 현재 working tree)")
    ap.add_argument("--rates", default=None, help="Human Rate Table JSON (기본: obhe/rates.json)")
    ap.add_argument("--ai-hours", type=float, default=None, help="AI Actual Effort (시간)")
    ap.add_argument("--manifest-only", action="store_true", help="로컬 층 결과만 출력 (LLM 미사용)")
    ap.add_argument("--json", dest="json_out", default=None, help="결과 JSON 저장 경로")
    args = ap.parse_args(argv)

    man = build_local_manifest(args.trajectory, args.repo, args.base, args.end)

    if args.manifest_only or man["recovery"] == "UNRECOVERABLE":
        print(json.dumps(man, ensure_ascii=False, indent=2, default=str))
        if man["recovery"] == "UNRECOVERABLE":
            print(f"\n{man['recovery_note']} — Human Effort 계산을 진행하지 않음 (§5.3/§14).")
        return 0 if args.manifest_only else 1

    rates = rate_engine.load_rates(args.rates)
    estimation = workload.estimate_workload(man, SimLLM(), rates)
    report = rate_engine.build_report(man, estimation, rates, ai_actual_hours=args.ai_hours)

    print(render_report(report, man))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"manifest": man, "report": report}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"\nJSON 저장: {args.json_out}")
    return 0


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.exit(main())
