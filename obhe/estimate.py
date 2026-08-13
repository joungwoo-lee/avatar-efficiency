# -*- coding: utf-8 -*-
"""OBHE CLI — 결과물 기반 Human Equivalent Effort 추산.

사용법:
  # 1) 이미 작성된 Human Action Ledger(JSON)로 시간 계산 (LLM 불필요)
  python estimate.py --ledger examples/sample_ledger.json [--ai-hours 20]

  # 2) artifact 파일에서 작업경로 복원(3중 추정) 후 계산 (기본 SimLLM)
  python estimate.py --artifact path/to/artifact.md [--judges 3] [--ai-hours 20]

  공통: [--rates rate_card.json] [--json out.json]

ledger JSON 스키마:
  {"reference_ledger": [{"outcome","action","quantity","drivers","evidence","role","confidence"}...],
   "replication_ledger": [...선택...],
   "outcome_confidence": "A|B|C", "path_confidence": "A|B|C"}
"""
import argparse
import io
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ledger_builder
    import rate_engine
    from sim_llm import SimLLM
else:
    from . import ledger_builder, rate_engine
    from .sim_llm import SimLLM


def _fmt_h(minutes):
    return f"{minutes / 60.0:5.1f}h"


def render_report(report, outcomes=None):
    out = []
    out.append("=" * 78)
    out.append("OBHE — 결과물 기반 Human Equivalent Effort 리포트")
    out.append("=" * 78)

    if outcomes:
        out.append("\n[Net Accepted Outcome]")
        for o in outcomes:
            out.append(f"  - {o.get('unit', '?')}: {o.get('quantity', '?')}  ({o.get('evidence', '')})")

    ref = report["reference"]
    out.append("\n[Human Action Ledger — Reference Human Path]")
    out.append(f"  {'action':<20} {'tax':<4} {'수량':>7} {'단위':<14} {'분/단위':>8} {'P50':>7} {'P80':>7}  근거")
    for r in ref["rows"]:
        out.append(
            f"  {r['action']:<20} {r['taxonomy']:<4} {r['quantity']:>7g} {r['unit']:<14}"
            f" {r['min_per_unit']:>8.1f} {_fmt_h(r['p50_min']):>7} {_fmt_h(r['p80_min']):>7}"
            f"  {r['evidence'][:40]}")
    out.append(f"  {'-' * 74}")
    out.append(f"  작업 소계                      P50 {_fmt_h(ref['work_p50_min'])} / P80 {_fmt_h(ref['work_p80_min'])}")
    out.append(f"  Expected Human Rework (§14)    P50 {_fmt_h(ref['rework_p50_min'])} / P80 {_fmt_h(ref['rework_p80_min'])}")

    out.append("\n[핵심 지표 (§19)]")
    out.append(f"  RHE (Reference Human Effort) : P50 {report['rhe_p50_hours']}h / P80 {report['rhe_p80_hours']}h")
    if "hre_p50_hours" in report:
        out.append(f"  HRE (Human Replication Effort): P50 {report['hre_p50_hours']}h")
        if report.get("output_inflation") is not None:
            out.append(f"  Output Inflation (HRE/RHE)   : {report['output_inflation']}x")
    if "ai_actual_hours" in report:
        out.append(f"  AI Actual Effort             : {report['ai_actual_hours']}h")
        if report.get("naive_efficiency") is not None:
            out.append(f"  겉보기 효율 (HRE/AI)          : {report['naive_efficiency']}x")
        if report.get("realized_efficiency") is not None:
            out.append(f"  현실화 효율 (RHE/AI)          : {report['realized_efficiency']}x")

    cc = report["confidence_components"]
    out.append(f"\n  Confidence: {report['confidence']}"
               f"  (outcome {cc['outcome']} / path {cc['path']} / rate DB {cc['rate_db']})")
    if report.get("human_review_required"):
        out.append("  ** Judge 간 편차 과대 — Human Review Required (§17) **")
    for w in report.get("warnings", []):
        out.append(f"  경고: {w}")
    out.append("=" * 78)
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="OBHE 결과물 기반 Human Equivalent Effort 추산")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--ledger", help="Human Action Ledger JSON 파일")
    src.add_argument("--artifact", help="최종 결과물 텍스트/마크다운 파일")
    ap.add_argument("--rates", default=None, help="rate card JSON 경로 (기본: obhe/rate_card.json)")
    ap.add_argument("--judges", type=int, default=3, help="작업경로 복원 반복 횟수 (§17, 기본 3)")
    ap.add_argument("--requirement", default=None, help="요구사항·배경 텍스트 파일 (선택)")
    ap.add_argument("--ai-hours", type=float, default=None, help="AI Actual Effort (시간)")
    ap.add_argument("--json", dest="json_out", default=None, help="리포트 JSON 저장 경로")
    args = ap.parse_args(argv)

    card = rate_engine.load_rate_card(args.rates)
    outcomes = None

    if args.ledger:
        data = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
        report = rate_engine.build_report(
            data["reference_ledger"], card,
            replication_ledger=data.get("replication_ledger"),
            ai_actual_hours=args.ai_hours,
            outcome_confidence=data.get("outcome_confidence", "B"),
            path_confidence=data.get("path_confidence", "B"))
        outcomes = data.get("outcomes")
    else:
        artifact_text = Path(args.artifact).read_text(encoding="utf-8")
        requirement_text = (Path(args.requirement).read_text(encoding="utf-8")
                            if args.requirement else "")
        restored = ledger_builder.restore_paths(
            artifact_text, SimLLM(), card,
            judges=args.judges, requirement_text=requirement_text)
        report = rate_engine.build_report(
            restored["reference_ledger"], card,
            replication_ledger=restored["replication_ledger"],
            ai_actual_hours=args.ai_hours,
            outcome_confidence=restored["outcome_confidence"],
            path_confidence=restored["path_confidence"],
            human_review_required=restored["human_review_required"])
        outcomes = restored["outcomes"]

    text = render_report(report, outcomes)
    print(text)

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 저장: {args.json_out}")
    return 0


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.exit(main())
