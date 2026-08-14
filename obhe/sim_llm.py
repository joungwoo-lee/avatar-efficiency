# -*- coding: utf-8 -*-
"""LLM 미연결 데모용 결정론적 시뮬레이터.

프롬프트에 포함된 Artifact Manifest JSON을 파싱해 파일별로 그럴듯한
completed outcome / action ledger를 만든다. 실운영에서는
complete_json(prompt, max_tokens) -> dict 계약의 실제 LLM 클라이언트로 교체.
"""
import json
import re

try:
    from .workload import MANIFEST_BEGIN, MANIFEST_END
except ImportError:
    from workload import MANIFEST_BEGIN, MANIFEST_END


def _loc(text):
    return len([ln for ln in (text or "").splitlines() if ln.strip()])


class SimLLM:
    def complete_json(self, prompt, max_tokens=4000):
        m = re.search(re.escape(MANIFEST_BEGIN) + r"\n(.*?)\n" + re.escape(MANIFEST_END),
                      prompt, re.DOTALL)
        manifest = json.loads(m.group(1)) if m else {"artifacts": []}
        outcomes, ledger = [], []
        n = 0
        for a in manifest.get("artifacts", []):
            n += 1
            oid = f"O{n}"
            text = a.get("content") or a.get("diff") or ""
            if a.get("type") == "answer":
                ev = a.get("review_evidence", {})
                claims = max(1, len(re.findall(r"\d+(?:\.\d+)?%?", text)))
                outcomes.append({
                    "outcome_id": oid, "outcome": "리뷰·분석 답변 전달",
                    "done_criteria": "최종 답변이 transcript에 존재",
                    "evidence": "(대화 답변) artifact"})
                ledger.append({"action_id": f"A{n}r", "outcome_id": oid,
                               "action": "read_material", "workload_unit": "loc_100",
                               "workload": max(1, round(ev.get("read_loc_total", 100) / 100, 1)),
                               "complexity": "normal",
                               "evidence": f"실측 read_loc_total={ev.get('read_loc_total', 0)}",
                               "shared": False})
                ledger.append({"action_id": f"A{n}v", "outcome_id": oid,
                               "action": "verify", "workload_unit": "claim",
                               "workload": min(claims, 30), "complexity": "normal",
                               "evidence": "답변 내 수치 포함 주장", "shared": False})
                ledger.append({"action_id": f"A{n}w", "outcome_id": oid,
                               "action": "construct", "workload_unit": "document",
                               "workload": 1, "complexity": "normal",
                               "evidence": "리뷰 의견서 1건", "shared": False})
                continue
            loc = max(1, _loc(text))
            is_test = "test" in a["path"].lower()
            outcomes.append({
                "outcome_id": oid,
                "outcome": f"{a['path']} {'테스트 확보' if is_test else '기능 반영'}",
                "done_criteria": "최종 net diff에 존재",
                "evidence": f"{a['path']} ({a['status']}, {a['attribution']})",
            })
            ledger.append({"action_id": f"A{n}r", "outcome_id": oid, "action": "read_material",
                           "workload_unit": "loc_100", "workload": max(1, round(loc / 100, 1)),
                           "complexity": "normal", "evidence": f"{a['path']} 변경 {loc}줄 이해",
                           "shared": False})
            if is_test:
                cases = max(1, len(re.findall(r"\bdef test|\bit\(|\btest_", text)))
                ledger.append({"action_id": f"A{n}t", "outcome_id": oid, "action": "construct",
                               "workload_unit": "testcase", "workload": cases,
                               "complexity": "normal", "evidence": f"testcase {cases}개",
                               "shared": False})
                asserts = max(cases, len(re.findall(r"assert|expect\(", text)))
                ledger.append({"action_id": f"A{n}v", "outcome_id": oid, "action": "verify",
                               "workload_unit": "assertion", "workload": asserts,
                               "complexity": "normal", "evidence": f"assertion {asserts}개",
                               "shared": False})
            else:
                funcs = max(1, len(re.findall(r"\bdef |\bfunction |\bclass ", text)))
                ledger.append({"action_id": f"A{n}c", "outcome_id": oid, "action": "construct",
                               "workload_unit": "function_point", "workload": funcs,
                               "complexity": "normal", "evidence": f"기능 단위 {funcs}개",
                               "shared": False})
        if manifest.get("artifacts"):
            ledger.append({"action_id": "A0", "outcome_id": outcomes[0]["outcome_id"],
                           "action": "understand_context", "workload_unit": "module",
                           "workload": min(4, len(manifest["artifacts"])),
                           "complexity": "normal", "evidence": "변경 대상 모듈 이해 (공유 선행 행동)",
                           "shared": True})
            ledger.append({"action_id": "A9", "outcome_id": outcomes[-1]["outcome_id"],
                           "action": "finalize", "workload_unit": "artifact_review",
                           "workload": 1, "complexity": "normal",
                           "evidence": "전체 변경 최종 검토", "shared": True})
        return {
            "completed_outcomes": outcomes,
            "action_ledger": ledger,
            "excluded_outputs": [{"item": p, "reason": "최종 net diff에 남지 않음 (TRANSIENT)"}
                                 for p in manifest.get("excluded_transient_paths", [])],
            "measurement_required": [],
        }
