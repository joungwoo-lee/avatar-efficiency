# -*- coding: utf-8 -*-
"""Artifact Manifest 생성 (방법론 §8) — LLM에 trajectory 전체가 아니라
정규화된 manifest만 넘긴다. LLM 미사용."""


def build_manifest(job_id, sessions, repo, states, artifacts, transient, unresolved,
                   grouping_evidence=None):
    task_requests = []
    for s in sessions:
        for t in s["task_requests"]:
            if t not in task_requests:
                task_requests.append(t)
    return {
        "job_id": job_id,
        "sessions": [s["session_id"] or s["file"] for s in sessions],
        "repository": str(repo),
        "base_state": states["base"],
        "end_state": states["end"],
        "recovery": states["recovery"],
        "recovery_note": states["note"],
        "grouping_evidence": grouping_evidence or [],
        "task_requests": task_requests[:20],
        "artifacts": artifacts,
        "excluded_transient_paths": transient,
        "unresolved": unresolved,
    }
