# -*- coding: utf-8 -*-
"""human_effort 패키지 — 사람 w/o 생성형AI Human-Equivalent Effort (분자).

폴더째 언더스코어 이름으로 복사해 import하거나 sys.path에 놓고 사용.
분모(agent_min)는 ../agent-effort, 구 API 어댑터는 ../counterfactual-api.
"""
from .estimator import (
    HumanEffortEstimator,
    DEFAULT_CATALOG_PATH,
    METHODOLOGY_VERSION,
    validate_effort_input,
    validate_requirements_output,
)
from .transcript_requirements import extract_requirements

__all__ = [
    "HumanEffortEstimator", "DEFAULT_CATALOG_PATH", "METHODOLOGY_VERSION",
    "validate_effort_input", "validate_requirements_output",
    "extract_requirements",
]
